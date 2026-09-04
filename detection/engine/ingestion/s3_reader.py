"""
engine/source/ingestion/s3_reader.py — Read new log objects from a client S3 bucket.

Responsibilities:
  - List S3 objects with the client's prefix, sorted by LastModified.
  - Skip objects up to and including last_processed_key.
  - Yield raw lines (str) from each new object in chronological order.
  - Return the key of the last successfully read object.

The caller (Celery task) is responsible for updating last_processed_key
in the DB after a successful run — this module never touches the DB.

Supports gzip-compressed objects (.gz extension) transparently.
"""

from __future__ import annotations

import gzip
import io
import logging
from datetime import datetime
from typing import Generator, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Reader:
    """
    Lazy reader — yields log lines from new S3 objects since last_processed_key.

    Args:
        bucket:             S3 bucket name.
        prefix:             Key prefix to filter objects (e.g. "logs/my-api/").
        aws_region:         AWS region the bucket is in.
        last_processed_key: The S3 key of the last object that was fully processed.
                            Objects with a key <= this value are skipped.
                            Pass None to start from the beginning.
        max_objects:        Safety cap — process at most this many objects per
                            invocation to prevent a single task from running for
                            hours if a client has a huge backlog.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str,
        aws_region: str,
        last_processed_key: Optional[str] = None,
        max_objects: int = 500,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self.aws_region = aws_region
        self.last_processed_key = last_processed_key
        self.max_objects = max_objects
        self._s3 = boto3.client("s3", region_name=aws_region)

    def list_new_objects(self) -> list[dict]:
        """
        Return a list of S3 object metadata dicts for objects not yet processed,
        sorted by LastModified ascending (oldest first).

        Each dict has: Key, LastModified, Size.
        """
        paginator = self._s3.get_paginator("list_objects_v2")
        all_objects: list[dict] = []

        try:
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for obj in page.get("Contents", []):
                    all_objects.append({
                        "Key": obj["Key"],
                        "LastModified": obj["LastModified"],
                        "Size": obj["Size"],
                    })
        except ClientError as exc:
            logger.error("S3Reader.list_new_objects failed: %s", exc)
            raise

        # Sort chronologically
        all_objects.sort(key=lambda o: o["LastModified"])

        if self.last_processed_key:
            # Skip everything up to and including the last processed key
            try:
                idx = next(
                    i for i, o in enumerate(all_objects)
                    if o["Key"] == self.last_processed_key
                )
                all_objects = all_objects[idx + 1:]
            except StopIteration:
                # last_processed_key no longer exists — start from beginning
                logger.warning(
                    "S3Reader: last_processed_key %r not found in bucket, "
                    "processing all objects",
                    self.last_processed_key,
                )

        return all_objects[:self.max_objects]

    def list_objects_since(self, cutoff: datetime) -> list[dict]:
        """
        Return object metadata for everything under this prefix with
        LastModified >= cutoff, sorted oldest first. Ignores
        last_processed_key entirely — used by item 45 Gap A's one-off
        calibration pass (last 24h of logs), which is a separate read from
        the normal incremental last_processed_key cursor and must not
        disturb it.

        No max_objects cap here: calibration reads a fixed, bounded time
        window rather than "everything since last cursor", so an unbounded
        backlog can't accumulate the way it could for list_new_objects().
        """
        paginator = self._s3.get_paginator("list_objects_v2")
        all_objects: list[dict] = []

        try:
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for obj in page.get("Contents", []):
                    if obj["LastModified"] >= cutoff:
                        all_objects.append({
                            "Key": obj["Key"],
                            "LastModified": obj["LastModified"],
                            "Size": obj["Size"],
                        })
        except ClientError as exc:
            logger.error("S3Reader.list_objects_since failed: %s", exc)
            raise

        all_objects.sort(key=lambda o: o["LastModified"])
        return all_objects

    def iter_lines(
        self, objects: Optional[list[dict]] = None
    ) -> Generator[tuple[str, str], None, None]:
        """
        Yield (key, line) tuples for every non-empty line across all new objects.

        Args:
            objects: Pre-fetched list from list_new_objects(). If None, fetches
                     them automatically.

        Yields:
            (key, raw_line) — the S3 object key and the raw log line (str, stripped).
        """
        if objects is None:
            objects = self.list_new_objects()

        for obj in objects:
            key = obj["Key"]
            logger.debug("S3Reader: reading s3://%s/%s (%d bytes)", self.bucket, key, obj["Size"])
            try:
                response = self._s3.get_object(Bucket=self.bucket, Key=key)
                body_bytes = response["Body"].read()

                if key.endswith(".gz"):
                    body_bytes = gzip.decompress(body_bytes)

                for raw_line in io.StringIO(body_bytes.decode("utf-8", errors="replace")):
                    line = raw_line.rstrip("\n\r")
                    if line:
                        yield key, line

            except ClientError as exc:
                # Log and skip — don't let one bad object abort the whole run.
                logger.error("S3Reader: failed to read s3://%s/%s: %s", self.bucket, key, exc)
                continue

    def read_all(self) -> tuple[list[str], Optional[str]]:
        """
        Convenience method: collect all new lines and return the last key seen.

        Returns:
            (lines, last_key) — flat list of raw log lines and the S3 key of
            the last object successfully read. last_key should be saved as
            last_processed_key in the DB.
        """
        objects = self.list_new_objects()
        if not objects:
            return [], self.last_processed_key

        lines: list[str] = []
        last_key: Optional[str] = self.last_processed_key

        for key, line in self.iter_lines(objects):
            lines.append(line)
            last_key = key

        logger.info(
            "S3Reader: read %d lines from %d objects (bucket=%s prefix=%s)",
            len(lines), len(objects), self.bucket, self.prefix,
        )
        return lines, last_key

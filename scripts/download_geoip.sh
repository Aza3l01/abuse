#!/usr/bin/env bash
# Download GeoLite2 databases from MaxMind.
# Requires MAXMIND_LICENSE_KEY to be set in environment or .env
# Run this on any new server after deploy, and monthly to keep the DBs current.
#
# Usage:
#   MAXMIND_LICENSE_KEY=xxxxx ./scripts/download_geoip.sh
#   or add MAXMIND_LICENSE_KEY to .env and run: source .env && ./scripts/download_geoip.sh

set -euo pipefail

if [[ -z "${MAXMIND_LICENSE_KEY:-}" ]]; then
  # Try sourcing .env if it exists
  if [[ -f ".env" ]]; then
    set -a
    source .env
    set +a
  fi
fi

if [[ -z "${MAXMIND_LICENSE_KEY:-}" ]]; then
  echo "Error: MAXMIND_LICENSE_KEY is not set."
  echo "Set it in .env or export it before running this script."
  exit 1
fi

DEST="engine/datasets"
mkdir -p "$DEST"

download_db() {
  local edition="$1"
  local filename="${edition}.mmdb"
  local tarball="${edition}.tar.gz"

  echo "Downloading ${edition}..."
  curl -fsSL \
    "https://download.maxmind.com/app/geoip_download?edition_id=${edition}&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" \
    -o "/tmp/${tarball}"

  echo "Extracting ${edition}..."
  tar -xzf "/tmp/${tarball}" -C /tmp
  # MaxMind extracts to a dated folder e.g. GeoLite2-ASN_20250101/
  local extracted
  extracted=$(find /tmp -maxdepth 1 -type d -name "${edition}_*" | sort | tail -1)
  cp "${extracted}/${filename}" "${DEST}/${filename}"
  rm -rf "${extracted}" "/tmp/${tarball}"

  echo "  -> ${DEST}/${filename}"
}

download_db "GeoLite2-ASN"
download_db "GeoLite2-City"

echo ""
echo "Done. Files written to ${DEST}/:"
ls -lh "${DEST}"/*.mmdb

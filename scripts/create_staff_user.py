"""
scripts/create_staff_user.py: create (or re-enrol) a staff user for the internal
ops panel (Phase 6). This is the ONLY way a staff row is created: there is no
API endpoint for it.

It prompts for a password (not echoed), generates a TOTP secret, prints the
secret and the otpauth URI to scan into an authenticator app, then asks for one
valid code. The account only becomes usable (totp_active) once that code checks
out.

Usage (run on the server, from the repo root, with the production env loaded):
  python scripts/create_staff_user.py founder@example.com
  python scripts/create_staff_user.py founder@example.com --reset-totp
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load env BEFORE importing anything that reads it (db.session, api.auth_utils).
from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT / ".env.local", override=True)

import pyotp  # noqa: E402

from api.auth_utils import encrypt_secret, hash_password  # noqa: E402
from api.staff_auth import verify_totp  # noqa: E402
from db.models import StaffUser  # noqa: E402
from db.session import SessionLocal  # noqa: E402

MIN_PASSWORD_LENGTH = 14


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("Password (min %d characters): " % MIN_PASSWORD_LENGTH)
        if len(password) < MIN_PASSWORD_LENGTH:
            print("Too short.")
            continue
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match.")
            continue
        return password


def _enrol(db, staff: StaffUser, secret: str, email: str) -> bool:
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Clew Staff")
    print("\nAdd this to your authenticator app:")
    print(f"  Secret: {secret}")
    print(f"  URI:    {uri}\n")
    code = input("Enter the current 6 digit code to confirm: ").strip()
    step = verify_totp(secret, code, None)
    if step is None:
        print("That code is not valid. The account stays disabled. Run the script again with --reset-totp.")
        return False
    staff.totp_active = True
    staff.last_totp_step = step
    db.commit()
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--reset-totp", action="store_true", help="re-enrol the authenticator of an existing staff user")
    args = parser.parse_args()
    email = args.email.strip().lower()

    db = SessionLocal()
    try:
        staff = db.query(StaffUser).filter(StaffUser.email == email).first()
        secret = pyotp.random_base32()
        if staff is None:
            if args.reset_totp:
                print("No such staff user.")
                return 1
            staff = StaffUser(
                email=email,
                password_hash=hash_password(_prompt_password()),
                totp_secret=encrypt_secret(secret),
                totp_active=False,
                is_active=True,
            )
            db.add(staff)
            db.commit()
            print(f"Created staff user {email}.")
        elif args.reset_totp:
            staff.totp_secret = encrypt_secret(secret)
            staff.totp_active = False
            staff.last_totp_step = None
            db.commit()
            print(f"Authenticator reset for {email}.")
        else:
            print("That staff user already exists. Use --reset-totp to re-enrol the authenticator.")
            return 1
        if not _enrol(db, staff, secret, email):
            return 1
        print("Done. The staff user can log in.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

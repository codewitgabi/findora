"""Create (or promote) an administrator account.

Usage:
    uv run python -m scripts.create_admin <email> <full_name> <password>

The full name may be quoted or not (e.g. Jane Doe). The password must be the
last argument and must not contain spaces unless quoted.

If a user with that email already exists it is promoted to admin and
reactivated; its password is left untouched.
"""

import argparse
import asyncio
from datetime import datetime, timezone

from api.database import db
from api.v1.models.user import COLLECTION_NAME, AccountStatus, UserRole
from api.v1.utils.security import hash_password


async def main(email: str, full_name: str, password: str) -> None:
    await db.connect()
    try:
        users = db.get_db()[COLLECTION_NAME]
        existing = await users.find_one({"email": email})
        if existing:
            await users.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "role": UserRole.ADMIN.value,
                        "account_status": AccountStatus.ACTIVE.value,
                    }
                },
            )
            print(f"Promoted existing user {email} to admin")
            return

        await users.insert_one(
            {
                "full_name": full_name,
                "email": email,
                "phone": None,
                "password_hash": hash_password(password),
                "role": UserRole.ADMIN.value,
                "account_status": AccountStatus.ACTIVE.value,
                "created_at": datetime.now(timezone.utc),
            }
        )
        print(f"Created admin {email}")
    finally:
        await db.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create (or promote) an administrator account."
    )
    parser.add_argument("email")
    parser.add_argument("full_name", nargs="+", help="Full name; quoting is optional")
    parser.add_argument("password")
    args = parser.parse_args()

    asyncio.run(main(args.email, " ".join(args.full_name), args.password))

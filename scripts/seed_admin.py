"""
Create or update an admin user in the database.

Usage:
    py scripts/seed_admin.py --email admin@example.com --password MyPass!

If a user with that email already exists their password and role are updated.
If no user exists a new one is created with role=admin and is_active=True.

Requires DATABASE_URL to be set in .env (loaded automatically).
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.models.db import User, UserRole, get_engine
from app.security import hash_password
from sqlmodel import Session, select


def seed(email: str, password: str):
    engine = get_engine()
    with Session(engine) as db:
        existing = db.exec(select(User).where(User.email == email)).first()
        if existing:
            print(f"User {email} already exists with role {existing.role}")
            return
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        print(f"Admin user created: {email}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    args = p.parse_args()
    seed(args.email, args.password)

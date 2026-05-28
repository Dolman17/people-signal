import os
from getpass import getpass

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User


def get_field_names(model):
    return {column.name for column in model.__table__.columns}


def main():
    app = create_app()

    with app.app_context():
        fields = get_field_names(User)

        email = input("Email: ").strip().lower()
        name = input("Name: ").strip()
        password = getpass("Password: ").strip()

        if not email:
            raise ValueError("Email is required.")

        if not password:
            raise ValueError("Password is required.")

        user = User.query.filter_by(email=email).first()

        if user:
            print(f"Existing user found: {email}")
        else:
            user = User()
            db.session.add(user)
            print(f"Creating new user: {email}")

        if "email" in fields:
            user.email = email

        if "name" in fields:
            user.name = name

        if "full_name" in fields:
            user.full_name = name

        if "password_hash" in fields:
            user.password_hash = generate_password_hash(password)
        elif "password" in fields:
            user.password = generate_password_hash(password)
        else:
            raise ValueError("Could not find password_hash or password field on User model.")

        if "role" in fields:
            user.role = "superuser"

        if "admin_level" in fields:
            user.admin_level = "superuser"

        if "is_admin" in fields:
            user.is_admin = True

        if "is_superuser" in fields:
            user.is_superuser = True

        if "is_active" in fields:
            user.is_active = True

        db.session.commit()

        print("Superuser created/updated successfully.")
        print(f"Email: {email}")


if __name__ == "__main__":
    main()
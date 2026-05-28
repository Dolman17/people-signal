from getpass import getpass

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import Organisation, User


app = create_app()


def create_superuser():
    with app.app_context():
        print("Create PeopleSignal superuser")
        print("-" * 35)

        organisation_name = input("Organisation name: ").strip()
        email = input("Email: ").strip().lower()
        password = getpass("Password: ").strip()
        confirm_password = getpass("Confirm password: ").strip()

        if not organisation_name or not email or not password:
            print("Organisation, email and password are required.")
            return

        if password != confirm_password:
            print("Passwords do not match.")
            return

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            existing_user.role = "superuser"
            existing_user.password_hash = generate_password_hash(password)

            db.session.commit()

            print(f"Existing user updated to superuser: {email}")
            return

        organisation = Organisation.query.filter_by(name=organisation_name).first()

        if not organisation:
            organisation = Organisation(name=organisation_name)
            db.session.add(organisation)
            db.session.flush()

        user = User(
            organisation_id=organisation.id,
            email=email,
            password_hash=generate_password_hash(password),
            role="superuser"
        )

        db.session.add(user)
        db.session.commit()

        print(f"Superuser created: {email}")


if __name__ == "__main__":
    create_superuser()
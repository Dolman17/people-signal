from getpass import getpass

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User


app = create_app()


def reset_password():
    with app.app_context():
        print("Reset PeopleSignal user password")
        print("-" * 40)

        email = input("User email: ").strip().lower()
        password = getpass("New password: ").strip()
        confirm_password = getpass("Confirm new password: ").strip()

        if not email or not password:
            print("Email and password are required.")
            return

        if password != confirm_password:
            print("Passwords do not match.")
            return

        user = User.query.filter_by(email=email).first()

        if not user:
            print(f"No user found with email: {email}")
            return

        user.password_hash = generate_password_hash(password)

        db.session.commit()

        print(f"Password reset successfully for: {email}")


if __name__ == "__main__":
    reset_password()
"""Load the fictional Kalingalinga boarding house.

Safe to run again. It replaces the sample landlord and leaves any
account you registered yourself.
"""

from app import create_app
from app.copy import SAMPLE_EMAIL, SAMPLE_PASSWORD
from app.seed_data import load_sample


def main() -> None:
    app = create_app()
    with app.app_context():
        load_sample()
        print("Sample book ready. These tenants are fictional.")
        print(f"Email:    {SAMPLE_EMAIL}")
        print(f"Password: {SAMPLE_PASSWORD}")
        print(app.config["SQLALCHEMY_DATABASE_URI"])


if __name__ == "__main__":
    main()

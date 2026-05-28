import os
from dotenv import load_dotenv

load_dotenv()


database_url = os.getenv("DATABASE_URL")

if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    SQLALCHEMY_DATABASE_URI = database_url or "sqlite:///people_signal.db"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
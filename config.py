import os


class Config:
    _BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    _INSTANCE_DIR = os.path.join(_BASE_DIR, 'instance')
    os.makedirs(_INSTANCE_DIR, exist_ok=True)

    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'
    # Default to SQLite for local development; override with DATABASE_URL for MySQL/Postgres
    # Example MySQL: mysql+pymysql://user:password@localhost/hackhub
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or (
        'sqlite:///' + os.path.join(_INSTANCE_DIR, 'hackhub.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload config for gallery/images if needed
    UPLOAD_FOLDER = os.path.join(_BASE_DIR, 'app', 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max limit

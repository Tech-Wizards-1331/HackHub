import os


class Config:
    _BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    _INSTANCE_DIR = os.path.join(_BASE_DIR, 'instance')
    os.makedirs(_INSTANCE_DIR, exist_ok=True)

    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'
    # Prefer PostgreSQL when configured via environment.
    # Supported env vars (first match wins):
    # - SQLALCHEMY_DATABASE_URI (explicit override)
    # - DATABASE_URL (common on Render/Heroku)
    # - POSTGRES_URL / POSTGRESQL_URL (common locally/CI)
    _db_url = (
        os.environ.get('SQLALCHEMY_DATABASE_URI')
        or os.environ.get('DATABASE_URL')
        or os.environ.get('POSTGRES_URL')
        or os.environ.get('POSTGRESQL_URL')
    )
    if _db_url and _db_url.startswith('postgres://'):
        # Some platforms provide postgres://; SQLAlchemy expects postgresql://.
        _db_url = _db_url.replace('postgres://', 'postgresql+psycopg2://', 1)

    SQLALCHEMY_DATABASE_URI = _db_url or ('sqlite:///' + os.path.join(_INSTANCE_DIR, 'hackhub.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload config for gallery/images if needed
    UPLOAD_FOLDER = os.path.join(_BASE_DIR, 'app', 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max limit

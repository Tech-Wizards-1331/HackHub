import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'
    # Default to SQLite for local development; override with DATABASE_URL for MySQL/Postgres
    # Example MySQL: mysql+pymysql://user:password@localhost/hackhub
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///hackhub.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload config for gallery/images if needed
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'app/static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max limit

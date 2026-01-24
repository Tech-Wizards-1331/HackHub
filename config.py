import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'mysql+pymysql://root:@localhost/hackhub'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload config for gallery/images if needed
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'app/static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max limit

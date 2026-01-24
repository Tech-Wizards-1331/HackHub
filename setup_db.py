import sqlalchemy
from sqlalchemy import create_engine, text

def create_database():
    # Connect to MySQL server (no database selected)
    engine = create_engine("mysql+pymysql://root:@localhost")
    with engine.connect() as conn:
        conn.execute(text("CREATE DATABASE IF NOT EXISTS hackhub"))
        print("Database 'hackhub' created or already exists.")

if __name__ == "__main__":
    create_database()

from app import create_app, db
from app.models import User, AccessSetting
import uuid
from sqlalchemy import text

app = create_app()

with app.app_context():
    # 1. Add qr_token column if missing
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN qr_token VARCHAR(36)"))
            conn.commit()
        print("Added qr_token column to users table.")
    except Exception as e:
        print(f"Note: Could not add column (it might exist): {e}")

    # 2. Create tables that don't exist (AccessSetting, ScanLog)
    db.create_all()
    print("Created new tables.")

    # 3. Backfill qr_token for existing users
    try:
        # Use simple text query to avoid ORM issues if column not fully mapped in session yet
        users_without_token = User.query.filter(User.qr_token == None).all()
        count = 0
        for user in users_without_token:
            if not user.qr_token:
                user.qr_token = str(uuid.uuid4())
                count += 1
        
        if count > 0:
            db.session.commit()
            print(f"Updated {count} users with QR tokens.")
        else:
            print("No users needed QR token backfill.")
    except Exception as e:
        print(f"Error backfilling users: {e}")
        
    # 4. Initialize Access Settings
    try:
        if not AccessSetting.query.first():
            setting = AccessSetting(active_access_type='ENTRY')
            db.session.add(setting)
            db.session.commit()
            print("Initialized Access Setting to ENTRY")
        else:
            print("Access Setting already exists")
    except Exception as e:
        print(f"Error initializing settings: {e}")

    print("Database update complete.")

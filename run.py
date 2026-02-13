from app import create_app, db
import os

app = create_app()

with app.app_context():
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    try:
        dialect = db.session.get_bind().dialect.name
    except Exception:
        dialect = 'unknown'
    print(f"SQLALCHEMY_DATABASE_URI: {uri}")
    print(f"DB dialect: {dialect}")
    db.create_all()

if __name__ == '__main__':
    ssl_context = None
    if os.environ.get('HH_HTTPS') == '1':
        try:
            import cryptography  # noqa: F401
            ssl_context = 'adhoc'
            print('HH_HTTPS=1 enabled: serving with a temporary (adhoc) HTTPS certificate')
        except Exception:
            print('HH_HTTPS=1 requested, but HTTPS could not be enabled (missing dependency).')
            print('Install with: pip install cryptography')
            ssl_context = None

    app.run(debug=True, port=5000, ssl_context=ssl_context)

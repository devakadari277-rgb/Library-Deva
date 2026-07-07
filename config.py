import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'supersecretkey123')
    # Handle postgres:// vs postgresql:// for SQLAlchemy
    db_url = os.environ.get('DATABASE_URL')
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    if not db_url:
        # On Vercel serverless platform, write to /tmp directory
        if os.environ.get('VERCEL') or os.environ.get('NOW_REGION'):
            db_path = "/tmp/database.db"
            initial_db = os.path.join(BASE_DIR, "database.db")
            if not os.path.exists(db_path) and os.path.exists(initial_db):
                import shutil
                try:
                    shutil.copy2(initial_db, db_path)
                except Exception:
                    pass
            db_url = f"sqlite:///{db_path}"
        else:
            db_url = f'sqlite:///{os.path.join(BASE_DIR, "database.db")}'
            
    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'images')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    ADMIN_REGISTRATION_CODE = os.environ.get('ADMIN_REGISTRATION_CODE', 'library-admin-secret')

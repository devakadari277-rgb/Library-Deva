from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'main.login_root'
login_manager.login_message_category = 'warning'

csrf = CSRFProtect()

import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_login import LoginManager

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "healthcare-inventory-secret-key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///inventory.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max file size

# initialize the app with the extension
db.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(int(user_id))

with app.app_context():
    # Import models to ensure tables are created
    import models  # noqa: F401
    import routes  # noqa: F401
    
    db.create_all()
    
    # Create default Cabinet bag if it doesn't exist
    from models import Bag, User
    if not Bag.query.filter_by(name='Cabinet').first():
        cabinet = Bag(name='Cabinet', description='Central storage cabinet')
        db.session.add(cabinet)
        db.session.commit()
        logging.info("Created default Cabinet bag")
    
    # Create default user if it doesn't exist
    if not User.query.filter_by(username='Bestdoc').first():
        user = User(username='Bestdoc')
        user.set_password('Bestdoc123!')
        db.session.add(user)
        db.session.commit()
        logging.info("Created default user")

# Register template filters for date formatting
@app.template_filter('datetime_gmt4')
def datetime_gmt4_filter(dt):
    from models import format_datetime_gmt4
    return format_datetime_gmt4(dt)

@app.template_filter('date_gmt4')
def date_gmt4_filter(dt):
    from models import format_date_gmt4
    return format_date_gmt4(dt)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

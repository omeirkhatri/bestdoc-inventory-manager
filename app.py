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
    from models import User, PermanentDeletion
    return User.query.get(int(user_id))

# Register Jinja filters
def datetime_gmt4_filter(dt):
    """Convert datetime to GMT+4 and format as DD/MM/YYYY HH:MM"""
    if not dt:
        return ''
    from pytz import timezone
    import pytz
    
    GMT_PLUS_4 = timezone('Asia/Dubai')  # GMT+4
    
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_dt = dt.astimezone(GMT_PLUS_4)
    return local_dt.strftime('%d/%m/%Y %H:%M')

def date_gmt4_filter(dt):
    """Convert date to GMT+4 and format as MM/YY"""
    if not dt:
        return ''
    from datetime import datetime
    from pytz import timezone
    import pytz
    
    GMT_PLUS_4 = timezone('Asia/Dubai')  # GMT+4
    
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        local_dt = dt.astimezone(GMT_PLUS_4)
        return local_dt.strftime('%m/%y')
    else:
        return dt.strftime('%m/%y')

app.jinja_env.filters['format_datetime_gmt4'] = datetime_gmt4_filter
app.jinja_env.filters['format_date_gmt4'] = date_gmt4_filter

with app.app_context():
    # Import models to ensure tables are created
    import models  # noqa: F401
    import routes  # noqa: F401
    
    db.create_all()
    
    # Initialize default item types
    from models import init_default_types
    init_default_types()




if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

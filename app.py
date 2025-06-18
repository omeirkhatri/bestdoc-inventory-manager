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
    """Convert datetime to GMT+4 and format as DD/MM/YY HH:MM"""
    if not dt:
        return ''
    from pytz import timezone
    import pytz
    
    GMT_PLUS_4 = timezone('Asia/Dubai')  # GMT+4
    
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_dt = dt.astimezone(GMT_PLUS_4)
    return local_dt.strftime('%d/%m/%y %H:%M')

def date_gmt4_filter(dt):
    """Convert date to GMT+4 and format as DD/MM/YY"""
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
        return local_dt.strftime('%d/%m/%y')
    else:
        return dt.strftime('%d/%m/%y')

app.jinja_env.filters['format_datetime_gmt4'] = datetime_gmt4_filter
app.jinja_env.filters['format_date_gmt4'] = date_gmt4_filter

with app.app_context():
    # Import models to ensure tables are created
    import models  # noqa: F401
    import routes  # noqa: F401
    
    db.create_all()
    
    # Create comprehensive dummy data
    from models import Bag, User, Product, Item, BagMinimum, ItemType, init_default_types
    from datetime import datetime, date, timedelta
    import random
    
    # Initialize default item types first
    init_default_types()
    
    # Create default user if it doesn't exist
    if not User.query.filter_by(username='Bestdoc').first():
        user = User(username='Bestdoc')
        user.set_password('Bestdoc123!')
        db.session.add(user)
        db.session.commit()
        logging.info("Created default user")
    
    # Create bags if they don't exist and haven't been permanently deleted
    from models import PermanentDeletion
    
    bags_data = [
        {'name': 'Cabinet', 'description': 'Central storage cabinet', 'location': 'cabinet'},
        {'name': 'Emergency Bag 1', 'description': 'Primary emergency response bag', 'location': 'bag'},
        {'name': 'Emergency Bag 2', 'description': 'Secondary emergency response bag', 'location': 'bag'},
        {'name': 'ICU Mobile Cart', 'description': 'Intensive care unit mobile equipment', 'location': 'bag'},
    ]
    
    created_bags = {}
    for bag_data in bags_data:
        # Check if this bag was permanently deleted and not restored
        permanently_deleted = PermanentDeletion.query.filter_by(
            entity_type='bag',
            entity_name=bag_data['name'],
            is_restored=False
        ).first()
        
        if not permanently_deleted and not Bag.query.filter_by(name=bag_data['name']).first():
            bag = Bag(
                name=bag_data['name'],
                description=bag_data['description'],
                location=bag_data['location']
            )
            db.session.add(bag)
            db.session.flush()
            created_bags[bag_data['name']] = bag
            logging.info(f"Created bag: {bag_data['name']}")
        else:
            existing_bag = Bag.query.filter_by(name=bag_data['name']).first()
            if existing_bag:
                created_bags[bag_data['name']] = existing_bag
    
    # Create products if they don't exist
    products_data = [
        {'name': 'Normal Saline 0.9%', 'type': 'IV Fluids', 'minimum_stock': 10},
        {'name': 'Epinephrine 1:1000', 'type': 'Emergency Medications', 'minimum_stock': 5},
        {'name': '22G IV Cannula', 'type': 'IV Equipment', 'minimum_stock': 20},
        {'name': 'Sterile Gauze 4x4', 'type': 'Consumable Dressings/Swabs', 'minimum_stock': 50},
        {'name': 'Nitrile Gloves Large', 'type': 'Consumable Dressings/Swabs', 'minimum_stock': 100},
        {'name': 'Atropine 1mg/ml', 'type': 'Emergency Medications', 'minimum_stock': 3},
        {'name': 'Morphine 10mg/ml', 'type': 'Controlled Medications', 'minimum_stock': 2},
        {'name': 'Oxygen Mask Adult', 'type': 'Airway Equipment', 'minimum_stock': 15},
        {'name': 'ECG Electrodes', 'type': 'Monitoring Equipment', 'minimum_stock': 30},
        {'name': 'Defibrillator Pads', 'type': 'Emergency Equipment', 'minimum_stock': 8},
    ]
    
    created_products = {}
    for product_data in products_data:
        if not Product.query.filter_by(name=product_data['name']).first():
            product = Product(
                name=product_data['name'],
                type=product_data['type'],
                minimum_stock=product_data['minimum_stock']
            )
            db.session.add(product)
            db.session.flush()
            created_products[product_data['name']] = product
            logging.info(f"Created product: {product_data['name']}")
        else:
            created_products[product_data['name']] = Product.query.filter_by(name=product_data['name']).first()
    
    # Create items with realistic quantities and expiry dates
    items_data = [
        # Cabinet items
        {'name': 'Normal Saline 0.9%', 'type': 'IV Fluids', 'size': '500ml', 'quantity': 25, 'bag': 'Cabinet', 'days_to_expire': 365},
        {'name': 'Epinephrine 1:1000', 'type': 'Emergency Medications', 'size': '1ml', 'quantity': 8, 'bag': 'Cabinet', 'days_to_expire': 180},
        {'name': '22G IV Cannula', 'type': 'IV Equipment', 'size': '22G', 'quantity': 45, 'bag': 'Cabinet', 'days_to_expire': 730},
        {'name': 'Sterile Gauze 4x4', 'type': 'Consumable Dressings/Swabs', 'size': '4x4', 'quantity': 120, 'bag': 'Cabinet', 'days_to_expire': 1095},
        {'name': 'Nitrile Gloves Large', 'type': 'Consumable Dressings/Swabs', 'size': 'Large', 'quantity': 200, 'bag': 'Cabinet', 'days_to_expire': 1460},
        
        # Emergency Bag 1 items
        {'name': 'Normal Saline 0.9%', 'type': 'IV Fluids', 'size': '500ml', 'quantity': 3, 'bag': 'Emergency Bag 1', 'days_to_expire': 365},
        {'name': 'Epinephrine 1:1000', 'type': 'Emergency Medications', 'size': '1ml', 'quantity': 2, 'bag': 'Emergency Bag 1', 'days_to_expire': 180},
        {'name': '22G IV Cannula', 'type': 'IV Equipment', 'size': '22G', 'quantity': 8, 'bag': 'Emergency Bag 1', 'days_to_expire': 730},
        {'name': 'Sterile Gauze 4x4', 'type': 'Consumable Dressings/Swabs', 'size': '4x4', 'quantity': 15, 'bag': 'Emergency Bag 1', 'days_to_expire': 1095},
        {'name': 'Oxygen Mask Adult', 'type': 'Airway Equipment', 'size': 'Adult', 'quantity': 4, 'bag': 'Emergency Bag 1', 'days_to_expire': 1825},
        
        # Emergency Bag 2 items (some below minimum to demonstrate feature)
        {'name': 'Normal Saline 0.9%', 'type': 'IV Fluids', 'size': '500ml', 'quantity': 1, 'bag': 'Emergency Bag 2', 'days_to_expire': 365},
        {'name': 'Epinephrine 1:1000', 'type': 'Emergency Medications', 'size': '1ml', 'quantity': 1, 'bag': 'Emergency Bag 2', 'days_to_expire': 180},
        {'name': 'Sterile Gauze 4x4', 'type': 'Consumable Dressings/Swabs', 'size': '4x4', 'quantity': 5, 'bag': 'Emergency Bag 2', 'days_to_expire': 1095},
        
        # ICU Mobile Cart items
        {'name': 'Morphine 10mg/ml', 'type': 'Controlled Medications', 'size': '1ml', 'quantity': 3, 'bag': 'ICU Mobile Cart', 'days_to_expire': 365},
        {'name': 'Atropine 1mg/ml', 'type': 'Emergency Medications', 'size': '1ml', 'quantity': 4, 'bag': 'ICU Mobile Cart', 'days_to_expire': 730},
        {'name': 'ECG Electrodes', 'type': 'Monitoring Equipment', 'size': 'Adult', 'quantity': 12, 'bag': 'ICU Mobile Cart', 'days_to_expire': 1095},
        {'name': 'Defibrillator Pads', 'type': 'Emergency Equipment', 'size': 'Adult', 'quantity': 2, 'bag': 'ICU Mobile Cart', 'days_to_expire': 730},
        {'name': 'Nitrile Gloves Large', 'type': 'Consumable Dressings/Swabs', 'size': 'Large', 'quantity': 20, 'bag': 'ICU Mobile Cart', 'days_to_expire': 1460},
    ]
    
    for item_data in items_data:
        # Skip items for bags that were permanently deleted
        if item_data['bag'] not in created_bags:
            continue
            
        bag = created_bags[item_data['bag']]
        product = created_products.get(item_data['name'])
        
        # Check if item already exists
        existing_item = Item.query.filter_by(
            name=item_data['name'],
            bag_id=bag.id,
            size=item_data['size']
        ).first()
        
        if not existing_item:
            expiry_date = date.today() + timedelta(days=item_data['days_to_expire'])
            item = Item(
                name=item_data['name'],
                type=item_data['type'],
                size=item_data['size'],
                quantity=item_data['quantity'],
                expiry_date=expiry_date,
                bag_id=bag.id,
                product_id=product.id if product else None
            )
            db.session.add(item)
    
    # Create bag minimums - set minimum quantities for each product in each medical bag
    bag_minimums_data = [
        # Emergency Bag 1 minimums
        {'bag': 'Emergency Bag 1', 'product': 'Normal Saline 0.9%', 'minimum': 2},
        {'bag': 'Emergency Bag 1', 'product': 'Epinephrine 1:1000', 'minimum': 2},
        {'bag': 'Emergency Bag 1', 'product': '22G IV Cannula', 'minimum': 5},
        {'bag': 'Emergency Bag 1', 'product': 'Sterile Gauze 4x4', 'minimum': 10},
        {'bag': 'Emergency Bag 1', 'product': 'Oxygen Mask Adult', 'minimum': 3},
        
        # Emergency Bag 2 minimums (will show as low stock)
        {'bag': 'Emergency Bag 2', 'product': 'Normal Saline 0.9%', 'minimum': 2},
        {'bag': 'Emergency Bag 2', 'product': 'Epinephrine 1:1000', 'minimum': 2},
        {'bag': 'Emergency Bag 2', 'product': 'Sterile Gauze 4x4', 'minimum': 10},
        {'bag': 'Emergency Bag 2', 'product': '22G IV Cannula', 'minimum': 5},
        
        # ICU Mobile Cart minimums
        {'bag': 'ICU Mobile Cart', 'product': 'Morphine 10mg/ml', 'minimum': 2},
        {'bag': 'ICU Mobile Cart', 'product': 'Atropine 1mg/ml', 'minimum': 3},
        {'bag': 'ICU Mobile Cart', 'product': 'ECG Electrodes', 'minimum': 10},
        {'bag': 'ICU Mobile Cart', 'product': 'Defibrillator Pads', 'minimum': 2},
        {'bag': 'ICU Mobile Cart', 'product': 'Nitrile Gloves Large', 'minimum': 15},
    ]
    
    for minimum_data in bag_minimums_data:
        # Skip minimums for bags that were permanently deleted
        if minimum_data['bag'] not in created_bags:
            continue
            
        bag = created_bags[minimum_data['bag']]
        product = created_products[minimum_data['product']]
        
        # Check if minimum already exists
        existing_minimum = BagMinimum.query.filter_by(
            bag_id=bag.id,
            product_id=product.id
        ).first()
        
        if not existing_minimum:
            bag_minimum = BagMinimum(
                bag_id=bag.id,
                product_id=product.id,
                minimum_quantity=minimum_data['minimum']
            )
            db.session.add(bag_minimum)
            logging.info(f"Created minimum for {bag.name} - {product.name}: {minimum_data['minimum']}")
    
    try:
        db.session.commit()
        logging.info("Successfully created comprehensive dummy data with bag minimums")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating dummy data: {e}")

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

from datetime import datetime, date, timedelta
from app import db
from sqlalchemy import func
import pytz

# GMT+4 timezone
GMT_PLUS_4 = pytz.timezone('Asia/Dubai')

def format_datetime_gmt4(dt):
    """Convert datetime to GMT+4 and format as DD/MM/YY HH:MM"""
    if not dt:
        return ''
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_dt = dt.astimezone(GMT_PLUS_4)
    return local_dt.strftime('%d/%m/%y %H:%M')

def format_date_gmt4(dt):
    """Convert date to GMT+4 and format as DD/MM/YY"""
    if not dt:
        return ''
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        local_dt = dt.astimezone(GMT_PLUS_4)
        return local_dt.strftime('%d/%m/%y')
    else:
        return dt.strftime('%d/%m/%y')

class Bag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    location = db.Column(db.String(50), default='bag')  # 'cabinet' or 'bag'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to items
    items = db.relationship('Item', backref='bag', lazy=True)
    
    def __repr__(self):
        return f'<Bag {self.name}>'
    
    def get_total_items(self):
        return sum(item.quantity for item in self.items if item.quantity > 0)
    
    def is_cabinet(self):
        return self.location == 'cabinet'

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    type = db.Column(db.String(100), nullable=False)
    minimum_stock = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to items (batches)
    items = db.relationship('Item', backref='product', lazy=True)
    
    def __repr__(self):
        return f'<Product {self.name}>'
    
    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.items if item.quantity > 0)
    
    @property
    def is_low_stock(self):
        return self.total_quantity <= self.minimum_stock
    
    @property
    def unique_sizes(self):
        return list(set(item.size for item in self.items if item.size))
    
    @property
    def active_batches(self):
        return [item for item in self.items if item.quantity > 0]

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(100), nullable=False)  # Consumables, Pharmacy Vials, IV Vials, etc.
    size = db.Column(db.String(50))  # 22G, 5ml, etc.
    quantity = db.Column(db.Integer, nullable=False, default=0)
    expiry_date = db.Column(db.Date)  # Optional
    date_added = db.Column(db.DateTime, default=datetime.utcnow)  # When item was added
    batch_number = db.Column(db.String(100))  # For tracking different batches
    
    # Foreign keys
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)  # Link to product
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Item {self.name} ({self.quantity})>'
    
    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        return self.expiry_date < date.today()
    
    @property
    def expires_soon(self):
        if not self.expiry_date:
            return False
        days_until_expiry = (self.expiry_date - date.today()).days
        return 0 <= days_until_expiry <= 30
    
    @property
    def expiry_status(self):
        if self.is_expired:
            return 'expired'
        elif self.expires_soon:
            return 'expiring'
        return 'good'
    
    @property
    def is_weekly_check_item(self):
        """Check if this item type requires weekly check (types 4 and 5)"""
        weekly_check_types = ['Consumable Dressings/Swabs', 'Catheters & Containers']
        return self.type in weekly_check_types

class MovementHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(200), nullable=False)
    item_type = db.Column(db.String(100), nullable=False)
    item_size = db.Column(db.String(50))
    quantity = db.Column(db.Integer, nullable=False)
    movement_type = db.Column(db.String(50), nullable=False)  # 'transfer', 'usage', 'addition', 'wastage'
    from_bag = db.Column(db.String(100))
    to_bag = db.Column(db.String(100))
    notes = db.Column(db.Text)
    expiry_date = db.Column(db.Date)  # For wastage tracking
    date_added = db.Column(db.DateTime, default=datetime.utcnow)  # When movement occurred
    patient_name = db.Column(db.String(200))  # For usage tracking
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Movement {self.item_name} ({self.quantity}) - {self.movement_type}>'

class ItemType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    
    def __repr__(self):
        return f'<ItemType {self.name}>'

# Initialize default item types - Updated for simplified system
def init_default_types():
    default_types = [
        'Medications/Vials',
        'IV Fluids/Solutions', 
        'Needles & Syringes',
        'Consumable Dressings/Swabs',
        'Catheters & Containers',
        'Equipment/Waste'
    ]
    
    for type_name in default_types:
        if not ItemType.query.filter_by(name=type_name).first():
            item_type = ItemType(name=type_name)
            db.session.add(item_type)
    
    # Update existing items to type 1 if they have old types
    existing_items = Item.query.all()
    for item in existing_items:
        if item.type not in default_types:
            item.type = 'Medications/Vials'  # Default to type 1
    
    db.session.commit()

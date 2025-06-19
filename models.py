from datetime import datetime, date, timedelta
from app import db
from sqlalchemy import func
import pytz
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# GMT+4 timezone
GMT_PLUS_4 = pytz.timezone('Asia/Dubai')

# User model for authentication
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

def format_datetime_gmt4(dt):
    """Convert datetime to GMT+4 and format as DD/MM/YYYY HH:MM"""
    if not dt:
        return ''
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_dt = dt.astimezone(GMT_PLUS_4)
    return local_dt.strftime('%d/%m/%Y %H:%M')

def format_date_gmt4(dt):
    """Convert date to GMT+4 and format as DD/MM/YYYY"""
    if not dt:
        return ''
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        local_dt = dt.astimezone(GMT_PLUS_4)
        return local_dt.strftime('%d/%m/%Y')
    else:
        return dt.strftime('%d/%m/%Y')

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
    brand = db.Column(db.String(100))  # Brand name - optional
    size = db.Column(db.String(50))  # 22G, 5ml, etc.
    quantity = db.Column(db.Integer, nullable=False, default=0)
    expiry_date = db.Column(db.Date)  # Optional
    date_added = db.Column(db.DateTime, default=datetime.utcnow)  # When item was added

    
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
        # Use GMT+4 timezone for consistent date comparison
        gmt4_now = datetime.now(GMT_PLUS_4)
        today_gmt4 = gmt4_now.date()
        return self.expiry_date < today_gmt4
    
    @property
    def expires_soon(self):
        if not self.expiry_date:
            return False
        # Use GMT+4 timezone for consistent date comparison
        gmt4_now = datetime.now(GMT_PLUS_4)
        today_gmt4 = gmt4_now.date()
        days_until_expiry = (self.expiry_date - today_gmt4).days
        return 0 <= days_until_expiry <= 30
    
    @property
    def expiry_status(self):
        if self.is_expired:
            return 'expired'
        elif self.expires_soon:
            return 'expiring'
        return 'good'
    
    @property
    def is_consumables_audit_item(self):
        """Check if this item type requires consumables audit (types 4 and 5)"""
        consumables_audit_types = ['Consumable Dressings/Swabs', 'Catheters & Containers']
        return self.type in consumables_audit_types

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

class BagMinimum(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    minimum_quantity = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    bag = db.relationship('Bag', backref='minimums')
    product = db.relationship('Product', backref='bag_minimums')
    
    # Unique constraint to prevent duplicate entries
    __table_args__ = (db.UniqueConstraint('bag_id', 'product_id', name='unique_bag_product_minimum'),)
    
    def __repr__(self):
        return f'<BagMinimum {self.bag.name} - {self.product.name}: {self.minimum_quantity}>'
    
    def current_quantity(self):
        """Get current quantity of this product in this bag"""
        total = 0
        for item in Item.query.filter_by(bag_id=self.bag_id, product_id=self.product_id).all():
            total += item.quantity
        return total
    
    def is_below_minimum(self):
        """Check if current quantity is below minimum"""
        return self.current_quantity() < self.minimum_quantity
    
    def shortage_amount(self):
        """Calculate how many items are needed to reach minimum"""
        current = self.current_quantity()
        if current < self.minimum_quantity:
            return self.minimum_quantity - current
        return 0

class UndoAction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(50), nullable=False)  # 'delete_bag', 'add_item', 'transfer', etc.
    action_data = db.Column(db.Text, nullable=False)  # JSON data to reverse the action
    description = db.Column(db.String(200), nullable=False)  # Human readable description
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_used = db.Column(db.Boolean, default=False)  # Track if this undo has been used
    
    # Relationship
    user = db.relationship('User', backref='undo_actions')
    
    def __repr__(self):
        return f'<UndoAction {self.action_type}: {self.description}>'

class PermanentDeletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False)  # 'bag', 'item', 'product'
    entity_name = db.Column(db.String(200), nullable=False)  # Name of deleted entity
    entity_data = db.Column(db.Text, nullable=False)  # JSON of original entity data
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    deletion_timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_restored = db.Column(db.Boolean, default=False)  # Track if this deletion was undone
    
    user = db.relationship('User', backref='permanent_deletions')

    def __repr__(self):
        return f'<PermanentDeletion {self.entity_type}: {self.entity_name}>'

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

class InventoryAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=True)  # Optional: specific bag audited
    audit_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    items_checked = db.Column(db.Integer, default=0)  # Number of items audited
    notes = db.Column(db.Text)
    
    # Relationships
    user = db.relationship('User', backref='inventory_audits')
    bag = db.relationship('Bag', backref='audits')
    
    def __repr__(self):
        return f'<InventoryAudit {self.audit_date}>'

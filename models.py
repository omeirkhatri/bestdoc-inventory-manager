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
    
    # Box/piece tracking fields
    units_per_box = db.Column(db.Integer, nullable=True)  # How many pieces in one box (e.g., 100 for alcohol swabs)
    packaging_unit = db.Column(db.String(50), default='pieces')  # 'pieces', 'vials', 'tablets', etc.
    box_description = db.Column(db.String(100))  # e.g., "Box of 100 swabs", "Box of 5 vials"
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to items (batches)
    items = db.relationship('Item', backref='product', lazy=True)
    
    def __repr__(self):
        return f'<Product {self.name}>'
    
    @property
    def total_quantity(self):
        return sum(item.total_pieces for item in self.items if item.total_pieces > 0)
    
    @property
    def total_boxes(self):
        return sum(item.boxes for item in self.items)
    
    @property
    def total_loose_pieces(self):
        return sum(item.loose_pieces for item in self.items)
    
    @property
    def is_low_stock(self):
        return self.total_quantity <= self.minimum_stock
    
    @property
    def unique_sizes(self):
        return list(set(item.size for item in self.items if item.size))
    
    @property
    def active_batches(self):
        return [item for item in self.items if item.total_pieces > 0]
    
    @property
    def has_box_tracking(self):
        return self.units_per_box is not None and self.units_per_box > 0
    
    def get_packaging_display(self):
        """Get display format for this product's packaging"""
        if self.has_box_tracking:
            return f"Box of {self.units_per_box} {self.packaging_unit}"
        return self.packaging_unit or "pieces"

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(100), nullable=False)  # Consumables, Pharmacy Vials, IV Vials, etc.
    size = db.Column(db.String(50))  # 22G, 5ml, etc.
    
    # Box/piece tracking
    boxes = db.Column(db.Integer, nullable=False, default=0)  # Number of full boxes
    loose_pieces = db.Column(db.Integer, nullable=False, default=0)  # Number of loose pieces
    quantity = db.Column(db.Integer, nullable=False, default=0)  # Legacy field - will be calculated property
    
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
        return f'<Item {self.name} ({self.total_pieces} pieces)>'
    
    @property
    def total_pieces(self):
        """Calculate total pieces = (boxes × units_per_box) + loose_pieces"""
        if self.product and self.product.units_per_box:
            return (self.boxes * self.product.units_per_box) + self.loose_pieces
        return self.loose_pieces
    
    @property
    def packaging_display(self):
        """Display format: '2 boxes + 3 vials' or '15 pieces'"""
        if self.product and self.product.units_per_box and self.boxes > 0:
            if self.loose_pieces > 0:
                return f"{self.boxes} boxes + {self.loose_pieces} {self.product.packaging_unit}"
            else:
                return f"{self.boxes} boxes"
        else:
            unit = self.product.packaging_unit if self.product else "pieces"
            return f"{self.loose_pieces} {unit}"
    
    def add_stock(self, boxes=0, pieces=0):
        """Add boxes and/or pieces to inventory"""
        self.boxes += boxes
        self.loose_pieces += pieces
        self.quantity = self.total_pieces  # Update legacy field
        db.session.commit()
    
    def remove_stock(self, pieces_to_remove):
        """Remove pieces, automatically breaking boxes if needed"""
        if pieces_to_remove > self.total_pieces:
            raise ValueError("Not enough stock available")
        
        remaining = pieces_to_remove
        
        # First remove from loose pieces
        if self.loose_pieces >= remaining:
            self.loose_pieces -= remaining
            remaining = 0
        else:
            remaining -= self.loose_pieces
            self.loose_pieces = 0
        
        # Then break boxes if needed
        if remaining > 0 and self.product and self.product.units_per_box:
            boxes_to_break = (remaining + self.product.units_per_box - 1) // self.product.units_per_box
            if boxes_to_break > self.boxes:
                raise ValueError("Not enough boxes to break")
            
            self.boxes -= boxes_to_break
            pieces_from_boxes = boxes_to_break * self.product.units_per_box
            self.loose_pieces = pieces_from_boxes - remaining
        
        self.quantity = self.total_pieces  # Update legacy field
        db.session.commit()
    
    def can_remove_boxes(self, boxes_to_remove):
        """Check if we can remove full boxes"""
        return self.boxes >= boxes_to_remove
    
    def remove_boxes(self, boxes_to_remove):
        """Remove full boxes"""
        if not self.can_remove_boxes(boxes_to_remove):
            raise ValueError("Not enough full boxes available")
        
        self.boxes -= boxes_to_remove
        self.quantity = self.total_pieces
        db.session.commit()
    
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
    quantity = db.Column(db.Integer, nullable=False)  # Total pieces moved
    
    # Box/piece tracking for movements
    boxes_moved = db.Column(db.Integer, default=0)
    pieces_moved = db.Column(db.Integer, default=0)
    movement_description = db.Column(db.String(200))  # e.g., "2 boxes + 3 vials"
    
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

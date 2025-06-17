from datetime import datetime, date
from app import db
from sqlalchemy import func

class Bag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to items
    items = db.relationship('Item', backref='bag', lazy=True)
    
    def __repr__(self):
        return f'<Bag {self.name}>'
    
    def get_total_items(self):
        return sum(item.quantity for item in self.items if item.quantity > 0)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(100), nullable=False)  # Consumables, Pharmacy Vials, IV Vials, etc.
    size = db.Column(db.String(50))  # 22G, 5ml, etc.
    quantity = db.Column(db.Integer, nullable=False, default=0)
    expiry_date = db.Column(db.Date)  # Optional
    batch_number = db.Column(db.String(100))  # For tracking batches
    
    # Foreign key to bag
    bag_id = db.Column(db.Integer, db.ForeignKey('bag.id'), nullable=False)
    
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

class MovementHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(200), nullable=False)
    item_type = db.Column(db.String(100), nullable=False)
    item_size = db.Column(db.String(50))
    quantity = db.Column(db.Integer, nullable=False)
    movement_type = db.Column(db.String(50), nullable=False)  # 'transfer', 'usage', 'addition'
    from_bag = db.Column(db.String(100))
    to_bag = db.Column(db.String(100))
    notes = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Movement {self.item_name} ({self.quantity}) - {self.movement_type}>'

class ItemType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    
    def __repr__(self):
        return f'<ItemType {self.name}>'

# Initialize default item types
def init_default_types():
    default_types = [
        'Consumables',
        'Pharmacy Vials',
        'IV Vials',
        'Syringes',
        'Needles',
        'Bandages',
        'Medications',
        'Equipment',
        'Supplies'
    ]
    
    for type_name in default_types:
        if not ItemType.query.filter_by(name=type_name).first():
            item_type = ItemType(name=type_name)
            db.session.add(item_type)
    
    db.session.commit()

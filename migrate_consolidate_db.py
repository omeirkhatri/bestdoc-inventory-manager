#!/usr/bin/env python3
"""
Script to consolidate database by removing Product and BagMinimum tables
and updating all references to use Item table exclusively.
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from app import app, db
from models import Item, Bag, MovementHistory, User, UndoAction, PermanentDeletion, InventoryAudit
from sqlalchemy import text

def migrate_database():
    """Migrate existing data and remove Product/BagMinimum dependencies"""
    
    with app.app_context():
        try:
            # First, let's see what tables exist
            result = db.session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
            tables = [row[0] for row in result]
            print(f"Existing tables: {tables}")
            
            # Check if product table exists and has data
            if 'product' in tables:
                result = db.session.execute(text("SELECT COUNT(*) FROM product"))
                product_count = result.scalar()
                print(f"Found {product_count} products")
                
                if product_count > 0:
                    # Copy minimum_stock values from product to items
                    print("Updating item minimum_stock values from product table...")
                    db.session.execute(text("""
                        UPDATE item 
                        SET minimum_stock = p.minimum_stock 
                        FROM product p 
                        WHERE item.name = p.name AND item.type = p.type
                    """))
                
                # Drop product table
                print("Dropping product table...")
                db.session.execute(text("DROP TABLE IF EXISTS product CASCADE"))
            
            # Check if bag_minimum table exists
            if 'bag_minimum' in tables:
                print("Dropping bag_minimum table...")
                db.session.execute(text("DROP TABLE IF EXISTS bag_minimum CASCADE"))
            
            db.session.commit()
            print("Database migration completed successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"Migration failed: {e}")
            raise

if __name__ == "__main__":
    migrate_database()
#!/usr/bin/env python3
"""
Script to consolidate duplicate items in the inventory database.
Items are considered duplicates if they have the same:
- name, type, brand, size, expiry_date, and bag_id
"""

from app import app, db
from models import Item, MovementHistory
from datetime import datetime
from sqlalchemy import func

def consolidate_duplicate_items():
    """Consolidate duplicate items by merging quantities and keeping one record."""
    
    with app.app_context():
        print("Starting item consolidation...")
        
        # Find groups of duplicate items
        duplicate_groups = db.session.query(
            Item.name,
            Item.type,
            Item.brand,
            Item.size,
            Item.expiry_date,
            Item.bag_id,
            func.count(Item.id).label('count')
        ).group_by(
            Item.name,
            Item.type,
            Item.brand,
            Item.size,
            Item.expiry_date,
            Item.bag_id
        ).having(func.count(Item.id) > 1).all()
        
        print(f"Found {len(duplicate_groups)} groups of duplicate items")
        
        total_consolidated = 0
        
        for group in duplicate_groups:
            # Get all items in this duplicate group
            duplicates = Item.query.filter_by(
                name=group.name,
                type=group.type,
                brand=group.brand,
                size=group.size,
                expiry_date=group.expiry_date,
                bag_id=group.bag_id
            ).order_by(Item.id).all()
            
            if len(duplicates) <= 1:
                continue
                
            print(f"Consolidating {len(duplicates)} duplicates of '{group.name}' in bag {group.bag_id}")
            
            # Keep the first item and merge quantities
            primary_item = duplicates[0]
            total_quantity = sum(item.quantity for item in duplicates)
            
            # Update primary item with total quantity
            primary_item.quantity = total_quantity
            primary_item.updated_at = datetime.utcnow()
            
            # Remove duplicate items (keep the first one)
            for duplicate_item in duplicates[1:]:
                print(f"  Removing duplicate item ID {duplicate_item.id} with quantity {duplicate_item.quantity}")
                db.session.delete(duplicate_item)
                total_consolidated += 1
            
            # Log the consolidation
            movement = MovementHistory(
                item_name=primary_item.name,
                item_type=primary_item.type,
                item_size=primary_item.size,
                quantity=total_quantity,
                movement_type='consolidation',
                to_bag=primary_item.bag.name,
                notes=f"Consolidated {len(duplicates)} duplicate entries into one record"
            )
            db.session.add(movement)
        
        # Commit all changes
        db.session.commit()
        print(f"Consolidation complete! Removed {total_consolidated} duplicate items")
        print("All duplicate items have been merged into single records")

if __name__ == "__main__":
    consolidate_duplicate_items()
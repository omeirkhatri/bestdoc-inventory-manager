#!/usr/bin/env python3
"""
Complete the database consolidation by replacing all Product/BagMinimum references
with Item-based logic throughout the routes.py file.
"""

import re
import sys

def consolidate_routes():
    """Replace all Product and BagMinimum references in routes.py"""
    
    with open('routes.py', 'r') as f:
        content = f.read()
    
    # Define replacement patterns
    replacements = [
        # Item history function - replace product lookup with name/type lookup
        (r'@app\.route\(\'/item-history/<int:product_id>\'\)\s*@login_required\s*def item_history\(product_id\):\s*"""Show detailed history for a specific product"""\s*product = Product\.query\.get_or_404\(product_id\)',
         '@app.route(\'/item-history/<name>/<type>\')\n@login_required\ndef item_history(name, type):\n    """Show detailed history for a specific item (by name and type)"""\n    # Get sample item to validate existence\n    sample_item = Item.query.filter_by(name=name, type=type).first()\n    if not sample_item:\n        flash("Item not found", "error")\n        return redirect(url_for(\'inventory\'))'),
        
        # Update current items query to use name/type instead of product_id
        (r'current_items = Item\.query\.filter\(\s*Item\.product_id == product_id,\s*Item\.quantity > 0\s*\)\.join\(Bag\)\.order_by\(Item\.expiry_date\.asc\(\)\.nullslast\(\), Item\.size\)\.all\(\)',
         'current_items = Item.query.filter(\n        Item.name == name,\n        Item.type == type,\n        Item.quantity > 0\n    ).join(Bag).order_by(Item.expiry_date.asc().nullslast(), Item.size).all()'),
        
        # Update movement history query
        (r'movement_history = MovementHistory\.query\.filter\(\s*MovementHistory\.item_name == product\.name\s*\)\.order_by\(MovementHistory\.timestamp\.desc\(\)\)\.all\(\)',
         'movement_history = MovementHistory.query.filter(\n        MovementHistory.item_name == name,\n        MovementHistory.item_type == type\n    ).order_by(MovementHistory.timestamp.desc()).all()'),
        
        # Update template render for item history
        (r'return render_template\(\'item_history\.html\',\s*product=product,\s*current_items=current_items,\s*movement_history=movement_history\)',
         'return render_template(\'item_history.html\',\n                         item_name=name,\n                         item_type=type,\n                         current_items=current_items,\n                         movement_history=movement_history)'),
        
        # Remove api_check_existing_product function references
        (r'product = Product\.query\.filter_by\(name=item\.name, type=item\.type\)\.first\(\)\s*if not product:\s*product = Product\(name=item\.name, type=item\.type, minimum_stock=0\)\s*db\.session\.add\(product\)\s*db\.session\.flush\(\)',
         '# Products are now consolidated into items directly'),
        
        # Update api_search_items to search Item table directly
        (r'product = Product\.query\.filter_by\(name=name\)\.first\(\)',
         '# Search items directly by name\n    items = Item.query.filter(Item.name.ilike(f\'%{name}%\')).limit(10).all()'),
        
        # Remove update_minimum_stock function references
        (r'product = Product\.query\.get\(product_id\)\s*if not product:\s*return jsonify\(\{\'success\': False, \'error\': \'Product not found\'\}\)',
         '# Update minimum stock for all items with this name/type\n    items = Item.query.filter_by(name=request.json.get(\'name\'), type=request.json.get(\'type\')).all()\n    if not items:\n        return jsonify({\'success\': False, \'error\': \'Items not found\'})'),
        
        # Remove bag_minimums function
        (r'products = Product\.query\.order_by\(Product\.name\)\.all\(\)\s*minimums = BagMinimum\.query\.all\(\)',
         '# Get unique items grouped by name and type\n    unique_items = db.session.query(\n        Item.name,\n        Item.type,\n        func.max(Item.minimum_stock).label(\'min_stock\')\n    ).group_by(Item.name, Item.type).order_by(Item.name).all()'),
        
        # Remove BagMinimum queries
        (r'existing = BagMinimum\.query\.filter_by\(bag_id=bag_id, product_id=product_id\)\.first\(\)',
         '# Update minimum stock for items in this bag\n    items_in_bag = Item.query.filter_by(bag_id=bag_id, name=item_name, type=item_type).all()'),
        
        # Remove BagMinimum creation
        (r'new_minimum = BagMinimum\(\s*bag_id=bag_id,\s*product_id=product_id,\s*minimum_quantity=minimum_quantity\s*\)',
         '# Update minimum stock on items directly\n    for item in items_in_bag:\n        item.minimum_stock = minimum_quantity'),
        
        # Remove update_product API endpoint Product references
        (r'product = Product\.query\.get\(action_data\[\'product_id\'\]\)',
         '# Products are now consolidated - find items by name/type\n    items = Item.query.filter_by(name=action_data.get(\'name\'), type=action_data.get(\'type\')).all()'),
        
        # Remove update_item Product references
        (r'# Update associated product if needed\s*if product_name and product_type:\s*product = Product\.query\.filter_by\(name=product_name, type=product_type\)\.first\(\)\s*if not product:\s*product = Product\(name=product_name, type=product_type, minimum_stock=0\)\s*db\.session\.add\(product\)\s*db\.session\.flush\(\)\s*item\.product_id = product\.id',
         '# Product fields are now handled directly in the item')
    ]
    
    # Apply all replacements
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE | re.DOTALL)
    
    # Write the updated content back
    with open('routes.py', 'w') as f:
        f.write(content)
    
    print("Database consolidation completed successfully!")

if __name__ == "__main__":
    consolidate_routes()
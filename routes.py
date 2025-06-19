import os
import csv
import io
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_, func
from flask_login import login_user, logout_user, login_required, current_user
from app import app, db
from models import Item, Bag, MovementHistory, ItemType, Product, User, BagMinimum, UndoAction, PermanentDeletion, InventoryAudit, init_default_types, format_datetime_gmt4, format_date_gmt4, GMT_PLUS_4
import json

# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()  # Clear all session data
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    # Initialize default types if needed
    init_default_types()
    
    # Get cabinet and bag inventories separately
    cabinet = Bag.query.filter_by(location='cabinet').first()
    bags = Bag.query.filter_by(location='bag').all()
    
    # Get summary statistics
    cabinet_items = db.session.query(func.sum(Item.quantity)).join(Bag).filter(Bag.location == 'cabinet').scalar() or 0
    bag_items = db.session.query(func.sum(Item.quantity)).join(Bag).filter(Bag.location == 'bag').scalar() or 0
    total_items = cabinet_items + bag_items
    total_bags = len(bags)
    
    # Count unique products
    total_unique_items = Product.query.count()
    
    # Items expiring soon (within 30 days)
    thirty_days_from_now = date.today() + timedelta(days=30)
    expiring_items = Item.query.filter(
        and_(
            Item.expiry_date.isnot(None),
            Item.expiry_date <= thirty_days_from_now,
            Item.expiry_date >= date.today(),
            Item.quantity > 0
        )
    ).all()
    
    # Expired items
    expired_items = Item.query.filter(
        and_(
            Item.expiry_date.isnot(None),
            Item.expiry_date < date.today(),
            Item.quantity > 0
        )
    ).all()
    
    # Low stock items (using product minimum stock thresholds)
    low_stock_products = Product.query.filter(Product.minimum_stock > 0).all()
    low_stock_items = []
    for product in low_stock_products:
        total_qty = sum(item.quantity for item in product.items if item.quantity > 0)
        if total_qty <= product.minimum_stock:
            low_stock_items.append({
                'product': product,
                'current_qty': total_qty,
                'minimum_stock': product.minimum_stock
            })
    
    # Low stock items in cabinet (quantity <= 10) - for alerts section
    low_stock_cabinet = Item.query.join(Bag).filter(
        and_(
            Bag.location == 'cabinet',
            Item.quantity <= 10,
            Item.quantity > 0
        )
    ).all()
    
    # Empty bags
    empty_bags = [bag for bag in bags if bag.get_total_items() == 0]
    
    # Bags below minimum quantities
    low_stock_bags = []
    for bag in bags:
        bag_low_items = []
        for minimum in bag.minimums:
            if minimum.is_below_minimum():
                bag_low_items.append({
                    'product': minimum.product,
                    'current': minimum.current_quantity(),
                    'minimum': minimum.minimum_quantity,
                    'shortage': minimum.shortage_amount()
                })
        if bag_low_items:
            low_stock_bags.append({
                'bag': bag,
                'low_items': bag_low_items
            })
    
    # Check for overdue inventory audits (over 7 days)
    seven_days_ago = datetime.now() - timedelta(days=7)
    last_audit = InventoryAudit.query.order_by(InventoryAudit.audit_date.desc()).first()
    audit_overdue = not last_audit or last_audit.audit_date < seven_days_ago
    
    # Recent movements
    recent_movements = MovementHistory.query.order_by(
        MovementHistory.timestamp.desc()
    ).limit(20).all()
    
    # Bag statistics
    bags_with_counts = []
    for bag in bags:
        item_count = sum(item.quantity for item in bag.items if item.quantity > 0)
        bags_with_counts.append({
            'name': bag.name,
            'count': item_count,
            'unique_items': len([item for item in bag.items if item.quantity > 0])
        })
    
    return render_template('dashboard.html',
                         total_items=total_items,
                         total_unique_items=total_unique_items,
                         cabinet_items=cabinet_items,
                         bag_items=bag_items,
                         cabinet=cabinet,
                         bags=bags,
                         total_bags=total_bags,
                         expiring_items=expiring_items,
                         expired_items=expired_items,
                         low_stock_items=low_stock_items,
                         low_stock_cabinet=low_stock_cabinet,
                         low_stock_bags=low_stock_bags,
                         empty_bags=empty_bags,
                         recent_movements=recent_movements,
                         bags_with_counts=bags_with_counts,
                         audit_overdue=audit_overdue,
                         last_audit=last_audit)

@app.route('/add_items', methods=['GET', 'POST'])
@login_required
def add_items():
    if request.method == 'POST':
        if 'csv_file' in request.files and request.files['csv_file'].filename:
            # Handle CSV upload
            return handle_csv_upload(request.files['csv_file'])
        else:
            # Handle manual form submission
            return handle_manual_addition()
    
    bags = Bag.query.all()
    item_types = ItemType.query.all()
    
    # Get existing item names for autocomplete with more complete information
    existing_items_query = db.session.query(
        Item.name, 
        Item.type, 
        Item.brand, 
        Item.size,
        func.max(Item.expiry_date).label('latest_expiry'),
        func.count(Item.id).label('frequency')
    ).group_by(Item.name, Item.type, Item.brand, Item.size).all()
    
    history_items = db.session.query(
        MovementHistory.item_name, 
        MovementHistory.item_type,
        MovementHistory.item_size,
        func.count(MovementHistory.id).label('frequency')
    ).group_by(
        MovementHistory.item_name, 
        MovementHistory.item_type, 
        MovementHistory.item_size
    ).all()
    
    # Combine and format items for autocomplete
    autocomplete_items = []
    seen = set()
    
    for item in existing_items_query:
        key = (item.name, item.type, item.brand or '', item.size or '')
        if key not in seen:
            autocomplete_items.append({
                'name': item.name,
                'type': item.type,
                'brand': item.brand or '',
                'size': item.size or '',
                'latest_expiry': item.latest_expiry.isoformat() if item.latest_expiry else None,
                'frequency': item.frequency,
                'source': 'current'
            })
            seen.add(key)
    
    for item in history_items:
        key = (item.item_name, item.item_type, '', item.item_size or '')
        if key not in seen:
            autocomplete_items.append({
                'name': item.item_name,
                'type': item.item_type,
                'brand': '',
                'size': item.item_size or '',
                'latest_expiry': None,
                'frequency': item.frequency,
                'source': 'history'
            })
            seen.add(key)
    
    # Sort by frequency (most used first) then by name
    autocomplete_items.sort(key=lambda x: (-x['frequency'], x['name']))
    
    return render_template('add_items.html', bags=bags, item_types=item_types, autocomplete_items=autocomplete_items)

def handle_csv_upload(file):
    if file and file.filename.endswith('.csv'):
        filename = secure_filename(file.filename)
        
        try:
            # Read CSV file
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_input = csv.DictReader(stream)
            
            items_added = 0
            errors = []
            
            for row_num, row in enumerate(csv_input, start=2):
                try:
                    # Validate required fields
                    if not row.get('name') or not row.get('type') or not row.get('quantity'):
                        errors.append(f"Row {row_num}: Missing required fields (name, type, quantity)")
                        continue
                    
                    # Get or create bag
                    bag_name = row.get('bag', 'Cabinet')
                    bag = Bag.query.filter_by(name=bag_name).first()
                    if not bag:
                        bag = Bag(name=bag_name, description=f"Auto-created from CSV")
                        db.session.add(bag)
                        db.session.flush()
                    
                    # Parse expiry date (MM/YY format, default to 1st of month)
                    expiry_date = None
                    if row.get('expiry_date'):
                        try:
                            date_str = row['expiry_date'].strip()
                            if '/' in date_str:
                                # New MM/YY format (e.g., "04/26")
                                month, year = date_str.split('/')
                                # Convert 2-digit year to 4-digit (assume 20XX)
                                full_year = 2000 + int(year) if int(year) < 50 else 1900 + int(year)
                                expiry_date = datetime(full_year, int(month), 1).date()
                            else:
                                # Try YYYY-MM format (HTML month input)
                                expiry_date = datetime.strptime(f"{date_str}-01", '%Y-%m-%d').date()
                        except (ValueError, IndexError):
                            errors.append(f"Row {row_num}: Invalid expiry date format. Use MM/YY format (e.g., 04/26)")
                            continue
                    
                    # Check if identical item already exists in the same bag
                    existing_item = Item.query.filter_by(
                        name=row['name'].strip(),
                        type=row['type'].strip(),
                        brand=row.get('brand', '').strip() or None,
                        size=row.get('size', '').strip() or None,
                        expiry_date=expiry_date,
                        bag_id=bag.id
                    ).first()
                    
                    if existing_item:
                        # Add to existing item
                        existing_item.quantity += int(row['quantity'])
                        existing_item.updated_at = datetime.utcnow()
                        item = existing_item
                    else:
                        # Create new item
                        item = Item(
                            generic_name=row.get('generic_name', '').strip() or None,
                            name=row['name'].strip(),
                            type=row['type'].strip(),
                            brand=row.get('brand', '').strip() or None,
                            size=row.get('size', '').strip() or None,
                            quantity=int(row['quantity']),
                            expiry_date=expiry_date,
                            bag_id=bag.id
                        )
                        db.session.add(item)
                    
                    # Log the addition
                    movement = MovementHistory(
                        item_name=item.name,
                        item_type=item.type,
                        item_size=item.size,
                        quantity=item.quantity,
                        movement_type='addition',
                        to_bag=bag.name,
                        notes=f"Added via CSV upload: {filename}"
                    )
                    db.session.add(movement)
                    
                    items_added += 1
                    
                except ValueError as e:
                    errors.append(f"Row {row_num}: Invalid quantity value")
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
            
            db.session.commit()
            
            if items_added > 0:
                flash(f"Successfully added {items_added} items from CSV", "success")
            
            if errors:
                for error in errors[:10]:  # Show first 10 errors
                    flash(error, "warning")
                if len(errors) > 10:
                    flash(f"...and {len(errors) - 10} more errors", "warning")
            
        except Exception as e:
            db.session.rollback()
            flash(f"Error processing CSV file: {str(e)}", "danger")
    
    else:
        flash("Please upload a valid CSV file", "danger")
    
    return redirect(url_for('add_items'))

def handle_manual_addition():
    try:
        # Get form data
        generic_names = request.form.getlist('generic_name')
        names = request.form.getlist('name')
        types = request.form.getlist('type')
        brands = request.form.getlist('brand')
        sizes = request.form.getlist('size')
        quantities = request.form.getlist('quantity')
        expiry_dates = request.form.getlist('expiry_date')

        minimum_stocks = request.form.getlist('minimum_stock')

        bag_id = request.form.get('bag_id')
        
        if not bag_id:
            flash("Please select a bag", "danger")
            return redirect(url_for('add_items'))
        
        bag = Bag.query.get_or_404(bag_id)
        items_added = 0
        
        for i in range(len(names)):
            if i < len(names) and i < len(types) and i < len(quantities):
                if names[i].strip() and types[i].strip() and quantities[i].strip():
                    # Parse expiry date (MM/YY format, default to 1st of month)
                    expiry_date = None
                    if i < len(expiry_dates) and expiry_dates[i].strip():
                        try:
                            date_str = expiry_dates[i].strip()
                            if '/' in date_str:
                                # New MM/YY format (e.g., "04/26")
                                month, year = date_str.split('/')
                                # Convert 2-digit year to 4-digit (assume 20XX)
                                full_year = 2000 + int(year) if int(year) < 50 else 1900 + int(year)
                                expiry_date = datetime(full_year, int(month), 1).date()
                            else:
                                # Old YYYY-MM format from HTML month input 
                                expiry_date = datetime.strptime(f"{date_str}-01", '%Y-%m-%d').date()
                        except (ValueError, IndexError):
                            flash(f"Invalid expiry date format for item {i+1}. Use MM/YY format (e.g., 04/26).", "warning")
                            continue
                    
                    # Get additional fields safely
                    generic_name = generic_names[i].strip() if i < len(generic_names) and generic_names[i].strip() else None
                    size = sizes[i].strip() if i < len(sizes) and sizes[i].strip() else None
                    brand = brands[i].strip() if i < len(brands) and brands[i].strip() else None
                    
                    # Handle product creation/lookup
                    product_name = names[i].strip()
                    product_type = types[i].strip()
                    product = Product.query.filter_by(name=product_name).first()
                    
                    if not product:
                        # New product - get minimum stock if provided
                        min_stock = 0
                        if i < len(minimum_stocks) and minimum_stocks[i].strip():
                            try:
                                min_stock = int(minimum_stocks[i])
                            except ValueError:
                                min_stock = 0
                        
                        product = Product(
                            name=product_name,
                            type=product_type,
                            minimum_stock=min_stock
                        )
                        db.session.add(product)
                        db.session.flush()  # Get the product ID
                    
                    # Check if identical item already exists in the same bag
                    existing_item = Item.query.filter_by(
                        name=product_name,
                        type=product_type,
                        brand=brand,
                        size=size,
                        expiry_date=expiry_date,
                        bag_id=bag.id
                    ).first()
                    
                    if existing_item:
                        # Add to existing item
                        existing_item.quantity += int(quantities[i])
                        existing_item.updated_at = datetime.utcnow()
                        item = existing_item
                    else:
                        # Create new item
                        item = Item(
                            generic_name=generic_name,
                            name=product_name,
                            type=product_type,
                            brand=brand,
                            size=size,
                            quantity=int(quantities[i]),
                            expiry_date=expiry_date,
                            bag_id=bag.id,
                            product_id=product.id
                        )
                        db.session.add(item)
                    
                    # Log the addition
                    movement = MovementHistory(
                        item_name=item.name,
                        item_type=item.type,
                        item_size=item.size,
                        quantity=item.quantity,
                        movement_type='addition',
                        to_bag=bag.name,
                        notes="Added manually"
                    )
                    db.session.add(movement)
                    
                    # Create undo action for manual addition
                    undo_data = {
                        'action_type': 'add_item',
                        'item_name': item.name,
                        'item_type': item.type,
                        'brand': item.brand,
                        'size': item.size,
                        'quantity': item.quantity,
                        'expiry_date': item.expiry_date.isoformat() if item.expiry_date else None,
                        'bag_id': bag.id,
                        'bag_name': bag.name,
                        'product_id': product.id if product else None,
                        'product_created': not Product.query.filter_by(name=product_name).first() if product_name else False
                    }
                    
                    undo_action = UndoAction(
                        action_type='add_item',
                        action_data=json.dumps(undo_data),
                        description=f"Added {item.quantity} {item.name} to {bag.name}",
                        user_id=current_user.id
                    )
                    db.session.add(undo_action)
                    
                    items_added += 1
        
        db.session.commit()
        flash(f"Successfully added {items_added} items", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error adding items: {str(e)}", "danger")
    
    return redirect(url_for('add_items'))

@app.route('/inventory')
@login_required
@login_required
def inventory():
    # Get filter parameters
    search = request.args.get('search', '')
    type_filter = request.args.get('type', '')
    bag_filter = request.args.get('bag', '')
    status_filter = request.args.get('status', '')
    
    # Base query - get products with their items
    product_query = Product.query
    
    # Apply product-level filters
    if search:
        # Search in product names and also in item generic names
        product_ids_from_items = db.session.query(Item.product_id).filter(
            Item.generic_name.ilike(f'%{search}%')
        ).distinct().subquery()
        
        product_query = product_query.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.id.in_(db.session.query(product_ids_from_items.c.product_id))
            )
        )
    
    if type_filter:
        product_query = product_query.filter(Product.type == type_filter)
    
    products = product_query.order_by(Product.name).all()
    
    # Filter products based on item-level criteria and group items
    filtered_products = []
    for product in products:
        # Check low stock filter first (applies to entire product)
        if status_filter == 'low_stock':
            if not product.is_low_stock:
                continue
        
        # Get ALL items for this product to collect generic names, then filter for active ones
        all_items_for_product = Item.query.filter(Item.product_id == product.id).all()
        
        # Get active items for this product for display
        item_query = Item.query.filter(Item.product_id == product.id, Item.quantity > 0).join(Bag)
        
        # Apply item-level filters
        if bag_filter:
            item_query = item_query.filter(Bag.name == bag_filter)
        
        if status_filter and status_filter != 'low_stock':
            today = date.today()
            if status_filter == 'expired':
                item_query = item_query.filter(and_(Item.expiry_date.isnot(None), Item.expiry_date < today))
            elif status_filter == 'expiring':
                thirty_days = today + timedelta(days=30)
                item_query = item_query.filter(and_(Item.expiry_date.isnot(None), 
                                                Item.expiry_date >= today, 
                                                Item.expiry_date <= thirty_days))
            elif status_filter == 'expiring_90':
                thirty_days = today + timedelta(days=30)
                ninety_days = today + timedelta(days=90)
                item_query = item_query.filter(and_(Item.expiry_date.isnot(None), 
                                                Item.expiry_date > thirty_days, 
                                                Item.expiry_date <= ninety_days))
        
        items = item_query.order_by(Item.brand, Item.size, Item.expiry_date).all()
        
        if items:  # Only include products that have matching items
            # Group items by brand, size, and expiry date
            grouped_items = []
            current_group = None
            
            for item in items:
                # Create a key for grouping (brand, size, expiry_date, bag_id)
                group_key = (item.brand or 'No Brand', item.size or 'No Size', item.expiry_date, item.bag_id)
                
                if current_group is None or current_group['key'] != group_key:
                    # Start a new group
                    current_group = {
                        'key': group_key,
                        'brand': item.brand,
                        'generic_name': item.generic_name,
                        'size': item.size,
                        'expiry_date': item.expiry_date,
                        'items': [item],
                        'total_quantity': item.quantity,
                        'bags': [item.bag]
                    }
                    grouped_items.append(current_group)
                else:
                    # Add to existing group (should not happen with bag_id in key)
                    current_group['items'].append(item)
                    current_group['total_quantity'] += item.quantity
            
            # Collect unique generic names from ALL items for this product (including zero quantity)
            unique_generic_names = []
            for item in all_items_for_product:
                if item.generic_name and item.generic_name.strip():
                    if item.generic_name not in unique_generic_names:
                        unique_generic_names.append(item.generic_name)
            


            filtered_products.append({
                'product': product,
                'grouped_items': grouped_items,
                'unique_generic_names': unique_generic_names,
                'total_quantity': sum(item.quantity for item in items),
                'is_low_stock': product.is_low_stock
            })
    
    # Get filter options
    bags = Bag.query.all()
    item_types = ItemType.query.all()
    
    return render_template('inventory.html',
                         products=filtered_products,
                         bags=bags,
                         item_types=item_types,
                         today=datetime.now(GMT_PLUS_4).date(),
                         current_filters={
                             'search': search,
                             'type': type_filter,
                             'bag': bag_filter,
                             'status': status_filter
                         })

@app.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    if request.method == 'POST':
        return handle_transfer()
    
    # Get cabinet and bags
    cabinet = Bag.query.filter_by(location='cabinet').first()
    bags = Bag.query.filter_by(location='bag').all()
    
    # Get cabinet items
    cabinet_items = []
    if cabinet:
        cabinet_items = Item.query.filter_by(bag_id=cabinet.id).filter(Item.quantity > 0).order_by(Item.name, Item.expiry_date).all()
    
    # Get items in medical bags for potential return to cabinet
    bag_items = {}
    for bag in bags:
        items = Item.query.filter_by(bag_id=bag.id).filter(Item.quantity > 0).order_by(Item.name).all()
        if items:
            bag_items[bag.name] = items
    
    return render_template('transfer.html', 
                         bags=bags, 
                         cabinet=cabinet,
                         cabinet_items=cabinet_items, 
                         bag_items=bag_items)

def handle_transfer():
    try:
        item_id = request.form.get('item_id')
        to_bag_id = request.form.get('to_bag_id')
        quantity = int(request.form.get('quantity', 0))
        
        if not item_id or not to_bag_id or quantity <= 0:
            flash("Please provide valid transfer details", "danger")
            return redirect(url_for('transfer'))
        
        item = Item.query.get_or_404(item_id)
        to_bag = Bag.query.get_or_404(to_bag_id)
        from_bag = item.bag
        
        if quantity > item.quantity:
            flash("Cannot transfer more items than available", "danger")
            return redirect(url_for('transfer'))
        
        if item.bag_id == int(to_bag_id):
            flash("Cannot transfer to the same bag", "warning")
            return redirect(url_for('transfer'))
        
        # Check if same item exists in destination bag
        existing_item = Item.query.filter_by(
            name=item.name,
            type=item.type,
            size=item.size,
            expiry_date=item.expiry_date,
            brand=item.brand,
            bag_id=to_bag_id
        ).first()
        
        if existing_item:
            # Add to existing item
            existing_item.quantity += quantity
            existing_item.updated_at = datetime.utcnow()
        else:
            # Create new item in destination bag
            new_item = Item(
                name=item.name,
                type=item.type,
                brand=item.brand,
                size=item.size,
                quantity=quantity,
                expiry_date=item.expiry_date,
                bag_id=to_bag_id,
                product_id=item.product_id
            )
            db.session.add(new_item)
        
        # Reduce quantity from source item
        item.quantity -= quantity
        item.updated_at = datetime.utcnow()
        
        # Remove source item if quantity reaches zero
        if item.quantity <= 0:
            db.session.delete(item)
        
        # Log the transfer
        movement = MovementHistory(
            item_name=item.name,
            item_type=item.type,
            item_size=item.size,
            quantity=quantity,
            movement_type='transfer',
            from_bag=from_bag.name,
            to_bag=to_bag.name,
            notes=f"Transferred {quantity} units"
        )
        db.session.add(movement)
        
        # Create undo action
        undo_data = {
            'action_type': 'transfer',
            'item_id': item.id,
            'from_bag_id': from_bag.id,
            'to_bag_id': to_bag.id,
            'quantity': quantity,
            'item_name': item.name,
            'item_type': item.type,
            'item_brand': item.brand,
            'item_size': item.size,
            'item_expiry_date': item.expiry_date.isoformat() if item.expiry_date else None,
            'product_id': item.product_id,
            'existing_item_id': existing_item.id if existing_item else None,
            'new_item_created': existing_item is None,
            'source_item_deleted': item.quantity <= 0,
            'original_source_quantity': item.quantity + quantity
        }
        
        undo_action = UndoAction(
            action_type='transfer',
            action_data=json.dumps(undo_data),
            description=f"Transfer {quantity} {item.name} from {from_bag.name} to {to_bag.name}",
            user_id=current_user.id
        )
        db.session.add(undo_action)
        
        db.session.commit()
        flash(f"Successfully transferred {quantity} units of {item.name} from {from_bag.name} to {to_bag.name}", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error during transfer: {str(e)}", "danger")
    
    return redirect(url_for('transfer'))

@app.route('/transfer/multi', methods=['POST'])
@login_required
def handle_multi_transfer():
    try:
        to_bag_id = request.form.get('to_bag_id')
        
        if not to_bag_id:
            flash("Please select a destination bag", "danger")
            return redirect(url_for('transfer'))
        
        to_bag = Bag.query.get_or_404(to_bag_id)
        
        # Parse item data from form
        transfer_items = []
        successful_transfers = []
        total_items_processed = 0
        
        # Extract items data from form
        for key in request.form.keys():
            if key.startswith('items[') and key.endswith('][item_id]'):
                # Extract item ID from key like "items[123][item_id]"
                item_id = request.form.get(key)
                quantity_key = key.replace('[item_id]', '[quantity]')
                quantity = int(request.form.get(quantity_key, 0))
                
                if item_id and quantity > 0:
                    transfer_items.append({
                        'item_id': item_id,
                        'quantity': quantity
                    })
        
        if not transfer_items:
            flash("No items selected for transfer", "warning")
            return redirect(url_for('transfer'))
        
        # Process each transfer
        for transfer_data in transfer_items:
            try:
                item_id = transfer_data['item_id']
                quantity = transfer_data['quantity']
                
                item = Item.query.get(item_id)
                if not item:
                    continue
                
                # Validation checks
                if quantity > item.quantity:
                    flash(f"Cannot transfer {quantity} units of {item.name} - only {item.quantity} available", "warning")
                    continue
                
                if item.bag_id == int(to_bag_id):
                    flash(f"Cannot transfer {item.name} to the same bag", "warning")
                    continue
                
                from_bag = item.bag
                
                # Check if same item exists in destination bag
                existing_item = Item.query.filter_by(
                    name=item.name,
                    type=item.type,
                    size=item.size,
                    expiry_date=item.expiry_date,
                    brand=item.brand,
                    bag_id=to_bag_id
                ).first()
                
                if existing_item:
                    # Add to existing item
                    existing_item.quantity += quantity
                    existing_item.updated_at = datetime.utcnow()
                else:
                    # Create new item in destination bag
                    new_item = Item(
                        name=item.name,
                        type=item.type,
                        brand=item.brand,
                        size=item.size,
                        quantity=quantity,
                        expiry_date=item.expiry_date,
                        bag_id=to_bag_id,
                        product_id=item.product_id
                    )
                    db.session.add(new_item)
                
                # Reduce quantity from source item
                item.quantity -= quantity
                item.updated_at = datetime.utcnow()
                
                # Remove source item if quantity reaches zero
                if item.quantity <= 0:
                    db.session.delete(item)
                
                # Log the transfer
                movement = MovementHistory(
                    item_name=item.name,
                    item_type=item.type,
                    item_size=item.size,
                    quantity=quantity,
                    movement_type='transfer',
                    from_bag=from_bag.name,
                    to_bag=to_bag.name,
                    notes=f"Multi-transfer: {quantity} units"
                )
                db.session.add(movement)
                
                successful_transfers.append({
                    'name': item.name,
                    'quantity': quantity,
                    'from_bag': from_bag.name
                })
                total_items_processed += 1
                
            except Exception as e:
                flash(f"Error transferring {item.name if 'item' in locals() else 'item'}: {str(e)}", "danger")
                continue
        
        if successful_transfers:
            # Create a single undo action for the multi-transfer
            undo_data = {
                'action_type': 'multi_transfer',
                'to_bag_id': to_bag_id,
                'to_bag_name': to_bag.name,
                'transfers': successful_transfers,
                'total_items': total_items_processed
            }
            
            undo_action = UndoAction(
                action_type='multi_transfer',
                action_data=json.dumps(undo_data),
                description=f"Multi-transfer of {total_items_processed} items to {to_bag.name}",
                user_id=current_user.id
            )
            db.session.add(undo_action)
            
            db.session.commit()
            
            if total_items_processed == 1:
                flash(f"Successfully transferred 1 item to {to_bag.name}", "success")
            else:
                flash(f"Successfully transferred {total_items_processed} items to {to_bag.name}", "success")
        else:
            flash("No items were transferred", "warning")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error during multi-transfer: {str(e)}", "danger")
    
    return redirect(url_for('transfer'))

@app.route('/usage', methods=['GET', 'POST'])
@login_required
def usage():
    if request.method == 'POST':
        return handle_usage()
    
    # Only show medical bags for usage (not cabinet)
    bags = Bag.query.filter_by(location='bag').all()
    bag_items = {}
    
    for bag in bags:
        items = Item.query.filter_by(bag_id=bag.id).filter(Item.quantity > 0).order_by(Item.name).all()
        if items:  # Only include bags that have items
            bag_items[bag.name] = items
    
    return render_template('usage.html', bags=bags, bag_items=bag_items)

def handle_usage():
    try:
        item_id = request.form.get('item_id')
        quantity_used = int(request.form.get('quantity', 0))
        patient_name = request.form.get('patient_name', '').strip()
        notes = request.form.get('notes', '')
        
        if not item_id or quantity_used <= 0:
            flash("Please provide valid usage details", "danger")
            return redirect(url_for('usage'))
        
        if not patient_name:
            flash("Patient name is required for usage tracking", "danger")
            return redirect(url_for('usage'))
        
        item = Item.query.get_or_404(item_id)
        
        if quantity_used > item.quantity:
            flash("Cannot use more items than available", "danger")
            return redirect(url_for('usage'))
        
        # Reduce quantity
        item.quantity -= quantity_used
        item.updated_at = datetime.utcnow()
        
        # Log the usage with patient information
        movement = MovementHistory(
            item_name=item.name,
            item_type=item.type,
            item_size=item.size,
            quantity=quantity_used,
            movement_type='usage',
            from_bag=item.bag.name,
            patient_name=patient_name,
            notes=notes or f"Used {quantity_used} units for patient {patient_name}",
            expiry_date=item.expiry_date
        )
        db.session.add(movement)
        
        # Create undo action for usage
        undo_data = {
            'action_type': 'usage',
            'item_id': item.id,
            'quantity': quantity_used,
            'item_name': item.name,
            'bag_name': item.bag.name,
            'patient_name': patient_name,
            'notes': notes,
            'original_quantity': item.quantity + quantity_used
        }
        
        undo_action = UndoAction(
            action_type='usage',
            action_data=json.dumps(undo_data),
            description=f"Used {quantity_used} {item.name} for patient {patient_name}",
            user_id=current_user.id
        )
        db.session.add(undo_action)
        
        db.session.commit()
        flash(f"Successfully recorded usage of {quantity_used} units of {item.name}", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error recording usage: {str(e)}", "danger")
    
    return redirect(url_for('usage'))

@app.route('/history')
@login_required
def history():
    page = request.args.get('page', 1, type=int)
    movement_filter = request.args.get('type_filter', '')
    item_filter = request.args.get('item_filter', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    query = MovementHistory.query
    
    # Apply filters
    if movement_filter:
        query = query.filter(MovementHistory.movement_type == movement_filter)
    
    if item_filter:
        query = query.filter(MovementHistory.item_name.ilike(f'%{item_filter}%'))
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(MovementHistory.timestamp >= from_date)
        except ValueError:
            flash("Invalid from date format", "warning")
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
            # Add one day to include the entire to_date
            to_date = datetime.combine(to_date, datetime.max.time())
            query = query.filter(MovementHistory.timestamp <= to_date)
        except ValueError:
            flash("Invalid to date format", "warning")
    
    movements = query.order_by(MovementHistory.timestamp.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    return render_template('history.html', movements=movements)

@app.route('/expiry')
@login_required
def expiry():
    # Use GMT+4 timezone for consistent date calculations
    gmt4_now = datetime.now(GMT_PLUS_4)
    today = gmt4_now.date()
    thirty_days = today + timedelta(days=30)
    ninety_days = today + timedelta(days=90)
    
    # Expired items
    expired_items = Item.query.filter(
        and_(
            Item.expiry_date.isnot(None),
            Item.expiry_date < today,
            Item.quantity > 0
        )
    ).order_by(Item.expiry_date).all()
    
    # Items expiring within 30 days
    expiring_items = Item.query.filter(
        and_(
            Item.expiry_date.isnot(None),
            Item.expiry_date >= today,
            Item.expiry_date <= thirty_days,
            Item.quantity > 0
        )
    ).order_by(Item.expiry_date).all()
    
    # Items expiring within 90 days (but not within 30 days)
    expiring_90_days = Item.query.filter(
        and_(
            Item.expiry_date.isnot(None),
            Item.expiry_date > thirty_days,
            Item.expiry_date <= ninety_days,
            Item.quantity > 0
        )
    ).order_by(Item.expiry_date).all()
    
    return render_template('expiry.html', 
                         expired_items=expired_items, 
                         expiring_items=expiring_items,
                         expiring_90_days=expiring_90_days,
                         today=today)

@app.route('/bags', methods=['GET', 'POST'])
@login_required
def bags():
    if request.method == 'POST':
        return handle_bag_management()
    
    bags = Bag.query.all()
    # Separate bags by location for the template
    cabinets = [bag for bag in bags if bag.location == 'cabinet']
    medical_bags = [bag for bag in bags if bag.location == 'bag']
    
    return render_template('bags.html', bags=bags, cabinets=cabinets, medical_bags=medical_bags)

def handle_bag_management():
    action = request.form.get('action')
    
    try:
        if action == 'add':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            location = request.form.get('location', 'bag')  # Default to 'bag' if not specified
            
            if not name:
                flash("Name is required", "danger")
                return redirect(url_for('bags'))
            
            if Bag.query.filter_by(name=name).first():
                flash("A storage location with this name already exists", "danger")
                return redirect(url_for('bags'))
            
            bag = Bag(name=name, description=description, location=location)
            db.session.add(bag)
            db.session.commit()
            
            storage_type = "cabinet" if location == "cabinet" else "medical bag"
            flash(f"Successfully created {storage_type}: {name}", "success")
            
        elif action == 'edit':
            bag_id = request.form.get('bag_id')
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            
            if not bag_id or not name:
                flash("ID and name are required", "danger")
                return redirect(url_for('bags'))
            
            bag = Bag.query.get_or_404(bag_id)
            
            # Check if name is taken by another storage location
            existing = Bag.query.filter_by(name=name).first()
            if existing and existing.id != bag.id:
                flash("A storage location with this name already exists", "danger")
                return redirect(url_for('bags'))
            
            bag.name = name
            bag.description = description
            db.session.commit()
            
            storage_type = "cabinet" if bag.location == "cabinet" else "medical bag"
            flash(f"Successfully updated {storage_type}: {name}", "success")
            
        elif action == 'delete':
            bag_id = request.form.get('bag_id')
            bag = Bag.query.get_or_404(bag_id)
            
            # Don't allow deleting the default Cabinet
            if bag.name == 'Cabinet':
                flash("Cannot delete the default Cabinet", "danger")
                return redirect(url_for('bags'))
            
            # Get cabinet for item transfer
            cabinet = Bag.query.filter_by(name='Cabinet').first()
            if not cabinet:
                flash("Error: Cabinet not found", "danger")
                return redirect(url_for('bags'))
            
            # Store complete bag data for permanent deletion tracking
            bag_data = {
                'id': bag.id,
                'name': bag.name,
                'description': bag.description,
                'location': bag.location,
                'created_at': bag.created_at.isoformat() if bag.created_at else None
            }
            
            # Prepare undo data with complete page state
            undo_data = {
                'bag_id': bag.id,
                'bag_name': bag.name,
                'bag_description': bag.description,
                'bag_location': bag.location,
                'transferred_items': [],
                'deleted_minimums': [],
                'page_state': {
                    'total_bags_before': Bag.query.count(),
                    'cabinet_items_before': Item.query.filter_by(bag_id=cabinet.id).count(),
                    'deleted_bag_data': bag_data
                }
            }
            
            # Transfer all items to cabinet and track for undo
            items_transferred = 0
            bag_items = Item.query.filter_by(bag_id=bag.id).all()
            
            for item in bag_items:
                if item.quantity > 0:
                    undo_data['transferred_items'].append({
                        'item_id': item.id,
                        'original_bag_id': bag.id
                    })
                    
                    # Update the item's bag_id using SQLAlchemy update
                    Item.query.filter_by(id=item.id).update({
                        'bag_id': cabinet.id,
                        'updated_at': datetime.utcnow()
                    })
                    
                    items_transferred += item.quantity
                    
                    # Record movement
                    movement = MovementHistory(
                        item_name=item.name,
                        item_type=item.type,
                        item_size=item.size,
                        quantity=item.quantity,
                        movement_type='transfer',
                        from_bag=bag.name,
                        to_bag=cabinet.name,
                        notes=f'Auto-transferred due to bag deletion'
                    )
                    db.session.add(movement)
            
            # Remove bag minimums and track for undo
            bag_minimums = BagMinimum.query.filter_by(bag_id=bag.id).all()
            for minimum in bag_minimums:
                undo_data['deleted_minimums'].append({
                    'bag_id': minimum.bag_id,
                    'product_id': minimum.product_id,
                    'minimum_quantity': minimum.minimum_quantity
                })
                db.session.delete(minimum)
            
            # Record permanent deletion
            permanent_deletion = PermanentDeletion(
                entity_type='bag',
                entity_name=bag.name,
                entity_data=json.dumps(bag_data),
                user_id=current_user.id
            )
            db.session.add(permanent_deletion)
            
            # Create undo action with complete page state
            undo_action = UndoAction(
                action_type='delete_bag',
                action_data=json.dumps(undo_data),
                description=f"Deleted bag '{bag.name}' with {items_transferred} items transferred to Cabinet",
                user_id=current_user.id
            )
            db.session.add(undo_action)
            
            # Delete the bag
            storage_type = "cabinet" if bag.location == "cabinet" else "medical bag"
            storage_name = bag.name
            db.session.delete(bag)
            db.session.commit()
            
            if items_transferred > 0:
                flash(f"Successfully deleted {storage_type}: {storage_name}. {items_transferred} items transferred to Cabinet.", "success")
            else:
                flash(f"Successfully deleted {storage_type}: {storage_name}", "success")
    
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    
    return redirect(url_for('bags'))

@app.route('/wastage', methods=['GET', 'POST'])
@login_required
def wastage():
    if request.method == 'POST':
        return handle_wastage()
    
    # Get expired items for disposal using GMT+4 timezone
    gmt4_now = datetime.now(GMT_PLUS_4)
    today = gmt4_now.date()
    expired_items = Item.query.filter(
        and_(
            Item.expiry_date.isnot(None),
            Item.expiry_date < today,
            Item.quantity > 0
        )
    ).order_by(Item.expiry_date).all()
    
    # Get wastage history
    wastage_history = MovementHistory.query.filter_by(movement_type='wastage').order_by(
        MovementHistory.timestamp.desc()
    ).limit(10).all()
    
    return render_template('wastage.html', expired_items=expired_items, wastage_history=wastage_history, today=today)

def handle_wastage():
    try:
        item_id = request.form.get('item_id')
        quantity_wasted = int(request.form.get('quantity', 0))
        reason = request.form.get('reason', '')
        
        if not item_id or quantity_wasted <= 0:
            flash("Please provide valid wastage details", "danger")
            return redirect(url_for('wastage'))
        
        item = Item.query.get_or_404(item_id)
        
        if quantity_wasted > item.quantity:
            flash("Cannot waste more items than available", "danger")
            return redirect(url_for('wastage'))
        
        # Reduce quantity
        item.quantity -= quantity_wasted
        item.updated_at = datetime.utcnow()
        
        # Log the wastage
        movement = MovementHistory(
            item_name=item.name,
            item_type=item.type,
            item_size=item.size,
            quantity=quantity_wasted,
            movement_type='wastage',
            from_bag=item.bag.name,
            notes=reason or f"Wastage of {quantity_wasted} units",
            expiry_date=item.expiry_date
        )
        db.session.add(movement)
        
        db.session.commit()
        flash(f"Successfully recorded wastage of {quantity_wasted} units of {item.name}", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error recording wastage: {str(e)}", "danger")
    
    return redirect(url_for('wastage'))

@app.route('/item_history/<int:product_id>')
@login_required
def item_history(product_id):
    """Show detailed history for a specific product"""
    product = Product.query.get_or_404(product_id)
    
    # Get all current items for this product
    current_items = Item.query.filter(
        Item.product_id == product_id,
        Item.quantity > 0
    ).join(Bag).order_by(Item.expiry_date.asc().nullslast(), Item.size).all()
    
    # Get all movement history for this product
    movement_history = MovementHistory.query.filter(
        MovementHistory.item_name == product.name
    ).order_by(MovementHistory.timestamp.desc()).all()
    
    return render_template('item_history.html',
                         product=product,
                         current_items=current_items,
                         movement_history=movement_history)

@app.route('/individual_item_history/<int:item_id>')
@login_required
def individual_item_history(item_id):
    """Show detailed history for a specific individual item"""
    item = Item.query.get_or_404(item_id)
    
    # Get or create the product this item belongs to
    product = item.product
    if not product:
        # If item doesn't have a linked product, create one or find existing
        product = Product.query.filter_by(name=item.name, type=item.type).first()
        if not product:
            product = Product(name=item.name, type=item.type, minimum_stock=0)
            db.session.add(product)
            db.session.commit()
        # Link the item to the product
        item.product_id = product.id
        db.session.commit()
    
    # Get movement history specifically for this individual item
    # We'll match by name, type, size, and expiry date to track this specific item
    movements = MovementHistory.query.filter(
        db.and_(
            MovementHistory.item_name == item.name,
            MovementHistory.item_type == item.type,
            MovementHistory.item_size == item.size,
            MovementHistory.expiry_date == item.expiry_date
        )
    ).order_by(MovementHistory.timestamp.desc()).all()
    
    # Get all bags for transfer functionality
    bags = Bag.query.order_by(Bag.name).all()
    
    return render_template('individual_item_history.html', 
                         item=item,
                         product=product,
                         movements=movements,
                         bags=bags)

@app.route('/api/check_existing_product')
@login_required
def api_check_existing_product():
    """API endpoint to check if a product already exists"""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'exists': False})
    
    product = Product.query.filter_by(name=name).first()
    return jsonify({
        'exists': product is not None,
        'product_id': product.id if product else None,
        'type': product.type if product else None,
        'minimum_stock': product.minimum_stock if product else None
    })

@app.route('/api/items/search')
@login_required
def api_search_items():
    """API endpoint for item name autocomplete"""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify([])
    
    # Search in current inventory (search by name or generic name)
    items = db.session.query(Item.name, Item.type, Item.brand, Item.size, Item.generic_name).filter(
        db.or_(
            Item.name.ilike(f'%{query}%'),
            Item.generic_name.ilike(f'%{query}%')
        )
    ).distinct().limit(10).all()
    
    # Search in movement history for historical items
    history_items = db.session.query(MovementHistory.item_name, MovementHistory.item_type, MovementHistory.item_size).filter(
        MovementHistory.item_name.ilike(f'%{query}%')
    ).distinct().limit(10).all()
    
    # Combine and deduplicate results
    results = []
    seen = set()
    
    for item in items:
        key = (item.name, item.type, item.brand, item.size)
        if key not in seen:
            results.append({
                'name': item.name,
                'type': item.type,
                'brand': item.brand or '',
                'size': item.size or ''
            })
            seen.add(key)
    
    for item in history_items:
        key = (item.item_name, item.item_type, '', item.item_size)
        if key not in seen:
            results.append({
                'name': item.item_name,
                'type': item.item_type,
                'brand': '',
                'size': item.item_size or ''
            })
            seen.add(key)
    
    return jsonify(results[:10])

@app.route('/api/update_minimum_stock', methods=['POST'])
@login_required
def update_minimum_stock():
    """API endpoint to update minimum stock for a product"""
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        minimum_stock = data.get('minimum_stock')
        
        if not product_id or minimum_stock is None:
            return jsonify({'success': False, 'error': 'Missing product_id or minimum_stock'})
        
        if minimum_stock < 0:
            return jsonify({'success': False, 'error': 'Minimum stock cannot be negative'})
        
        product = Product.query.get(product_id)
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'})
        
        product.minimum_stock = minimum_stock
        db.session.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/bag_minimums')
@login_required
def bag_minimums():
    """Display and manage minimum quantities for each bag"""
    bags = Bag.query.all()
    products = Product.query.order_by(Product.name).all()
    
    # Get all existing minimums
    minimums = BagMinimum.query.all()
    minimums_dict = {}
    for minimum in minimums:
        key = f"{minimum.bag_id}_{minimum.product_id}"
        minimums_dict[key] = minimum
    
    # Get bags that need restocking
    low_stock_bags = []
    for bag in bags:
        bag_low_items = []
        for minimum in bag.minimums:
            if minimum.is_below_minimum():
                bag_low_items.append({
                    'product': minimum.product,
                    'current': minimum.current_quantity(),
                    'minimum': minimum.minimum_quantity,
                    'shortage': minimum.shortage_amount()
                })
        if bag_low_items:
            low_stock_bags.append({
                'bag': bag,
                'low_items': bag_low_items
            })
    
    return render_template('bag_minimums.html', 
                         bags=bags, 
                         products=products, 
                         minimums_dict=minimums_dict,
                         low_stock_bags=low_stock_bags)

@app.route('/api/update_bag_minimum', methods=['POST'])
@login_required
def update_bag_minimum():
    """API endpoint to update minimum quantity for a product in a specific bag"""
    try:
        data = request.get_json()
        bag_id = data.get('bag_id')
        product_id = data.get('product_id')
        minimum_quantity = data.get('minimum_quantity')
        
        if not all([bag_id, product_id, minimum_quantity is not None]):
            return jsonify({'success': False, 'error': 'Missing required data'})
        
        minimum_quantity = int(minimum_quantity)
        
        # Check if minimum already exists
        existing = BagMinimum.query.filter_by(bag_id=bag_id, product_id=product_id).first()
        
        if minimum_quantity == 0:
            # Remove minimum if set to 0
            if existing:
                db.session.delete(existing)
                db.session.commit()
            return jsonify({'success': True, 'message': 'Minimum removed'})
        
        if existing:
            existing.minimum_quantity = minimum_quantity
            existing.updated_at = datetime.utcnow()
        else:
            new_minimum = BagMinimum(
                bag_id=bag_id,
                product_id=product_id,
                minimum_quantity=minimum_quantity
            )
            db.session.add(new_minimum)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Minimum updated successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/undo_last_action', methods=['POST'])
@login_required
def undo_last_action():
    """Undo the last action performed by the current user"""
    try:
        # Get the most recent unused undo action for this user
        last_action = UndoAction.query.filter_by(
            user_id=current_user.id,
            is_used=False
        ).order_by(UndoAction.timestamp.desc()).first()
        
        if not last_action:
            return jsonify({'success': False, 'error': 'No actions to undo'})
        
        # Parse the action data
        action_data = json.loads(last_action.action_data)
        
        if last_action.action_type == 'delete_bag':
            # Recreate the deleted bag
            new_bag = Bag(
                name=action_data['bag_name'],
                description=action_data['bag_description'],
                location=action_data['bag_location']
            )
            db.session.add(new_bag)
            db.session.flush()  # Get the new bag ID
            
            # Transfer items back to the recreated bag
            for item_data in action_data['transferred_items']:
                item = Item.query.get(item_data['item_id'])
                if item:
                    item.bag_id = new_bag.id
            
            # Recreate bag minimums
            for minimum_data in action_data['deleted_minimums']:
                new_minimum = BagMinimum(
                    bag_id=new_bag.id,
                    product_id=minimum_data['product_id'],
                    minimum_quantity=minimum_data['minimum_quantity']
                )
                db.session.add(new_minimum)
            
            # Mark the permanent deletion as restored
            permanent_deletion = PermanentDeletion.query.filter_by(
                entity_type='bag',
                entity_name=action_data['bag_name'],
                user_id=current_user.id,
                is_restored=False
            ).first()
            if permanent_deletion:
                permanent_deletion.is_restored = True
            
            # Remove the auto-transfer movement history entries
            MovementHistory.query.filter_by(
                from_bag=action_data['bag_name'],
                to_bag='Cabinet',
                notes='Auto-transferred due to bag deletion'
            ).delete()
            
            success_message = f"Restored bag '{action_data['bag_name']}' with all items and settings"
        
        elif last_action.action_type == 'transfer':
            # Reverse the transfer
            from_bag = Bag.query.get(action_data['from_bag_id'])
            to_bag = Bag.query.get(action_data['to_bag_id'])
            
            if action_data['new_item_created']:
                # Delete the item that was created in destination bag
                dest_item = Item.query.filter_by(
                    name=action_data['item_name'],
                    bag_id=action_data['to_bag_id']
                ).first()
                if dest_item:
                    db.session.delete(dest_item)
            else:
                # Reduce quantity from existing item in destination bag
                dest_item = Item.query.get(action_data['existing_item_id'])
                if dest_item:
                    dest_item.quantity -= action_data['quantity']
                    if dest_item.quantity <= 0:
                        db.session.delete(dest_item)
            
            # Handle source item restoration
            if action_data.get('source_item_deleted', False):
                # Recreate the source item that was deleted
                expiry_date = None
                if action_data.get('item_expiry_date'):
                    expiry_date = datetime.fromisoformat(action_data['item_expiry_date']).date()
                
                restored_item = Item(
                    name=action_data['item_name'],
                    type=action_data['item_type'],
                    brand=action_data.get('item_brand'),
                    size=action_data.get('item_size'),
                    quantity=action_data['quantity'],
                    expiry_date=expiry_date,
                    bag_id=action_data['from_bag_id'],
                    product_id=action_data.get('product_id')
                )
                db.session.add(restored_item)
            else:
                # Restore quantity to existing source item
                source_item = Item.query.get(action_data['item_id'])
                if source_item:
                    source_item.quantity += action_data['quantity']
                    source_item.updated_at = datetime.utcnow()
            
            # Remove the transfer movement history
            MovementHistory.query.filter(
                and_(
                    MovementHistory.item_name == action_data['item_name'],
                    MovementHistory.from_bag == from_bag.name,
                    MovementHistory.to_bag == to_bag.name,
                    MovementHistory.quantity == action_data['quantity'],
                    MovementHistory.movement_type == 'transfer'
                )
            ).delete()
            
            success_message = f"Reversed transfer of {action_data['quantity']} {action_data['item_name']} from {to_bag.name} back to {from_bag.name}"
        
        elif last_action.action_type == 'usage':
            # Reverse the usage
            item = Item.query.get(action_data['item_id'])
            if item:
                # Restore the used quantity
                item.quantity += action_data['quantity']
                item.updated_at = datetime.utcnow()
                
                # Remove the usage movement history
                MovementHistory.query.filter(
                    and_(
                        MovementHistory.item_name == action_data['item_name'],
                        MovementHistory.from_bag == action_data['bag_name'],
                        MovementHistory.quantity == action_data['quantity'],
                        MovementHistory.movement_type == 'usage',
                        MovementHistory.patient_name == action_data['patient_name']
                    )
                ).delete()
                
                success_message = f"Reversed usage of {action_data['quantity']} {action_data['item_name']} for patient {action_data['patient_name']}"
            else:
                return jsonify({'success': False, 'error': 'Item not found for usage reversal'})
        
        elif last_action.action_type == 'add_item':
            # Reverse the item addition
            # Find and remove the added item
            item = Item.query.filter_by(
                name=action_data['item_name'],
                type=action_data['item_type'],
                brand=action_data.get('brand'),
                size=action_data.get('size'),
                bag_id=action_data['bag_id'],
                quantity=action_data['quantity']
            ).first()
            
            if item:
                # Remove the item
                db.session.delete(item)
                
                # Remove the addition movement history
                MovementHistory.query.filter(
                    and_(
                        MovementHistory.item_name == action_data['item_name'],
                        MovementHistory.to_bag == action_data['bag_name'],
                        MovementHistory.quantity == action_data['quantity'],
                        MovementHistory.movement_type == 'addition',
                        MovementHistory.notes == 'Added manually'
                    )
                ).delete()
                
                # If a product was created for this item and no other items use it, remove it
                if action_data.get('product_created') and action_data.get('product_id'):
                    other_items = Item.query.filter_by(product_id=action_data['product_id']).count()
                    if other_items == 0:  # No other items use this product
                        product = Product.query.get(action_data['product_id'])
                        if product:
                            db.session.delete(product)
                
                success_message = f"Removed added item: {action_data['quantity']} {action_data['item_name']} from {action_data['bag_name']}"
            else:
                return jsonify({'success': False, 'error': 'Added item not found for reversal'})
        
        elif last_action.action_type == 'inventory_audit':
            # Reverse inventory audit changes
            audit_id = action_data['audit_id']
            changes = action_data['changes']
            
            # Reverse each change made during the audit
            for change in changes:
                item_name = change['item_name']
                item_type = change['item_type']
                item_size = change['item_size']
                quantity_change = change['quantity_change']
                
                # Find items to reverse the change
                items_to_update = Item.query.filter(
                    and_(
                        Item.name == item_name,
                        Item.type == item_type,
                        Item.size == item_size if item_size else Item.size.is_(None),
                        Item.quantity >= 0
                    )
                ).all()
                
                if quantity_change < 0:
                    # Original was reduction (usage), so we need to add back
                    quantity_to_add = abs(quantity_change)
                    if items_to_update:
                        items_to_update[0].quantity += quantity_to_add
                else:
                    # Original was addition (adjustment), so we need to subtract
                    remaining_to_reduce = quantity_change
                    for item in items_to_update:
                        if remaining_to_reduce <= 0:
                            break
                        
                        if item.quantity <= remaining_to_reduce:
                            remaining_to_reduce -= item.quantity
                            item.quantity = 0
                        else:
                            item.quantity -= remaining_to_reduce
                            remaining_to_reduce = 0
            
            # Remove the audit movement history records
            MovementHistory.query.filter(
                MovementHistory.movement_type.like('BULK_WEEKLY_CHECK_%')
            ).filter(
                MovementHistory.timestamp >= last_action.timestamp
            ).delete(synchronize_session=False)
            
            # Mark the audit as reversed
            audit = InventoryAudit.query.get(audit_id)
            if audit:
                audit.notes = f"{audit.notes} - REVERSED"
            
            success_message = f"Reversed inventory audit with {len(changes)} item changes"
        
        else:
            return jsonify({'success': False, 'error': 'Unknown action type'})
        
        # Mark the undo action as used
        last_action.is_used = True
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': success_message,
            'action_description': last_action.description
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/quick_restock_data')
@login_required
def quick_restock_data():
    """Get items that need restocking in specified bag"""
    try:
        bag_id = request.args.get('bag_id', type=int)
        if not bag_id:
            return jsonify({'items': []})
        
        # Find specified bag and Cabinet
        target_bag = Bag.query.get(bag_id)
        cabinet = Bag.query.filter_by(name='Cabinet').first()
        
        if not target_bag or not cabinet:
            return jsonify({'items': []})
        
        # Get items that are below minimum in specified bag
        restock_items = []
        for minimum in target_bag.minimums:
            current_qty = minimum.current_quantity()
            if current_qty < minimum.minimum_quantity:
                # Get available items in Cabinet for this product, sorted by expiry date
                cabinet_items = Item.query.filter_by(
                    bag_id=cabinet.id, 
                    product_id=minimum.product_id
                ).filter(Item.quantity > 0).order_by(Item.expiry_date.asc().nullslast()).all()
                
                cabinet_qty = sum(item.quantity for item in cabinet_items)
                needed = minimum.minimum_quantity - current_qty
                
                # Get product details for display
                product = minimum.product
                size = None
                earliest_expiry = None
                
                if cabinet_items:
                    size = cabinet_items[0].size
                    earliest_expiry = cabinet_items[0].expiry_date
                
                restock_items.append({
                    'product_id': product.id,
                    'product_name': product.name,
                    'size': size,
                    'cabinet_qty': cabinet_qty,
                    'current_qty': current_qty,
                    'minimum_qty': minimum.minimum_quantity,
                    'needed': needed,
                    'earliest_expiry': earliest_expiry,
                    'cabinet_items_details': [
                        {
                            'quantity': item.quantity,
                            'expiry_date': item.expiry_date,
                            'brand': item.brand
                        } for item in cabinet_items
                    ]
                })
        
        return jsonify({'items': restock_items})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/quick_restock', methods=['POST'])
@login_required
def quick_restock():
    """Process quick restock from Cabinet to specified bag"""
    try:
        product_ids = request.form.getlist('product_ids')
        quantities = request.form.getlist('quantities')
        bag_id = request.form.get('bag_id', type=int)
        
        if not bag_id:
            flash("Invalid bag selection", "danger")
            return redirect(url_for('dashboard'))
        
        # Find target bag and Cabinet
        target_bag = Bag.query.get(bag_id)
        cabinet = Bag.query.filter_by(name='Cabinet').first()
        
        if not target_bag or not cabinet:
            flash("Target bag or Cabinet not found", "danger")
            return redirect(url_for('dashboard'))
        
        transfers_made = []
        
        for i, product_id in enumerate(product_ids):
            if i < len(quantities):
                quantity = int(quantities[i]) if quantities[i].strip() else 0
                
                if quantity > 0:
                    product = Product.query.get(product_id)
                    if not product:
                        continue
                    
                    # Find items in Cabinet for this product
                    cabinet_items = Item.query.filter_by(
                        bag_id=cabinet.id,
                        product_id=product_id,
                    ).filter(Item.quantity > 0).all()
                    
                    # Transfer items from Cabinet to DOC Bag 1
                    remaining_to_transfer = quantity
                    
                    for cabinet_item in cabinet_items:
                        if remaining_to_transfer <= 0:
                            break
                        
                        transfer_qty = min(remaining_to_transfer, cabinet_item.quantity)
                        
                        # Check if same item exists in target bag
                        existing_item = Item.query.filter_by(
                            name=cabinet_item.name,
                            type=cabinet_item.type,
                            size=cabinet_item.size,
                            expiry_date=cabinet_item.expiry_date,
                            brand=cabinet_item.brand,
                            bag_id=target_bag.id,
                            product_id=product_id
                        ).first()
                        
                        if existing_item:
                            # Add to existing item
                            existing_item.quantity += transfer_qty
                            existing_item.updated_at = datetime.utcnow()
                        else:
                            # Create new item in target bag
                            new_item = Item(
                                name=cabinet_item.name,
                                type=cabinet_item.type,
                                brand=cabinet_item.brand,
                                size=cabinet_item.size,
                                quantity=transfer_qty,
                                expiry_date=cabinet_item.expiry_date,
                                bag_id=target_bag.id,
                                product_id=product_id
                            )
                            db.session.add(new_item)
                        
                        # Reduce quantity from Cabinet
                        cabinet_item.quantity -= transfer_qty
                        cabinet_item.updated_at = datetime.utcnow()
                        
                        # Log the transfer
                        movement = MovementHistory(
                            item_name=cabinet_item.name,
                            item_type=cabinet_item.type,
                            item_size=cabinet_item.size,
                            quantity=transfer_qty,
                            movement_type='transfer',
                            from_bag=cabinet.name,
                            to_bag=target_bag.name,
                            notes=f"Quick restock transfer"
                        )
                        db.session.add(movement)
                        
                        remaining_to_transfer -= transfer_qty
                        transfers_made.append(f"{transfer_qty} {cabinet_item.name}")
        
        db.session.commit()
        
        if transfers_made:
            flash(f"Successfully restocked: {', '.join(transfers_made)}", "success")
        else:
            flash("No items were transferred", "info")
            
    except Exception as e:
        db.session.rollback()
        flash(f"Error during restock: {str(e)}", "danger")
    
    return redirect(url_for('dashboard'))

@app.route('/api/bulk_update_bag_minimums', methods=['POST'])
@login_required
def bulk_update_bag_minimums():
    """Bulk update multiple bag minimums at once"""
    try:
        data = request.get_json()
        changes = data.get('changes', [])
        
        if not changes:
            return jsonify({'success': False, 'error': 'No changes provided'})
        
        updates_count = 0
        
        for change in changes:
            bag_id = change.get('bag_id')
            product_id = change.get('product_id')
            minimum_quantity = change.get('minimum_quantity', 0)
            
            if not bag_id or not product_id:
                continue
            
            # Find existing minimum or create new one
            existing_minimum = BagMinimum.query.filter_by(
                bag_id=bag_id, 
                product_id=product_id
            ).first()
            
            if minimum_quantity > 0:
                if existing_minimum:
                    existing_minimum.minimum_quantity = minimum_quantity
                    existing_minimum.updated_at = datetime.utcnow()
                else:
                    new_minimum = BagMinimum(
                        bag_id=bag_id,
                        product_id=product_id,
                        minimum_quantity=minimum_quantity
                    )
                    db.session.add(new_minimum)
                updates_count += 1
            else:
                # Remove minimum if quantity is 0
                if existing_minimum:
                    db.session.delete(existing_minimum)
                    updates_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully updated {updates_count} minimum quantities'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/get_last_action')
@login_required
def get_last_action():
    """Get information about the last action that can be undone"""
    try:
        last_action = UndoAction.query.filter_by(
            user_id=current_user.id,
            is_used=False
        ).order_by(UndoAction.timestamp.desc()).first()
        
        if last_action:
            return jsonify({
                'action': {
                    'description': last_action.description,
                    'timestamp': last_action.timestamp.isoformat()
                }
            })
        else:
            return jsonify({'action': None})
    except Exception as e:
        return jsonify({'action': None, 'error': str(e)})

@app.route('/inventory_audit')
@login_required
def inventory_audit():
    """Display inventory audit page for consumable items separated by storage location"""
    # Get selected bag/storage from query parameter
    selected_bag_id = request.args.get('bag_id', type=int)
    
    # Get all bags for selection dropdown (excluding 'All Locations' option)
    all_bags = Bag.query.order_by(Bag.location.desc(), Bag.name).all()
    
    # If no bag is selected, default to Cabinet
    if not selected_bag_id:
        cabinet_bag = Bag.query.filter_by(name='Cabinet').first()
        if cabinet_bag:
            selected_bag_id = cabinet_bag.id
    
    # Get all items that require weekly check (types 4 and 5)
    consumables_audit_types = ['Consumable Dressings/Swabs', 'Catheters & Containers']
    
    # Base query for consumable items - always filter by selected bag
    query = Item.query.join(Bag).filter(
        and_(
            Item.type.in_(consumables_audit_types),
            Item.quantity > 0,
            Item.bag_id == selected_bag_id
        )
    )
    
    selected_bag = Bag.query.get(selected_bag_id) if selected_bag_id else None
    consumable_items = query.order_by(Item.name, Item.size).all()
    
    # Group items by name and size for easier display
    grouped_items = {}
    for item in consumable_items:
        key = f"{item.name} ({item.size})" if item.size else item.name
        if key not in grouped_items:
            grouped_items[key] = {
                'name': item.name,
                'size': item.size,
                'current_qty': 0,
                'type': item.type,
                'bag_name': item.bag.name,
                'bag_location': item.bag.location,
                'items': []
            }
        grouped_items[key]['current_qty'] += item.quantity
        grouped_items[key]['items'].append(item)
    
    return render_template('inventory_audit.html', 
                         grouped_items=grouped_items,
                         all_bags=all_bags,
                         selected_bag=selected_bag)

@app.route('/inventory_audit', methods=['POST'])
@login_required
def handle_inventory_audit():
    """Process inventory audit form submission"""
    if request.method == 'POST':
        try:
            # Get today's date to check if it's Friday
            today = datetime.now()
            
            # Process each item's new count
            bulk_movements = []
            
            for key, value in request.form.items():
                if key.startswith('new_count_'):
                    item_key = key.replace('new_count_', '')
                    new_count = int(value) if value.strip() else 0
                    
                    # Get current quantity from hidden field
                    current_qty_key = f'current_qty_{item_key}'
                    current_qty = int(request.form.get(current_qty_key, 0))
                    
                    # Get item details from hidden fields
                    item_name = request.form.get(f'item_name_{item_key}', '')
                    item_type = request.form.get(f'item_type_{item_key}', '')
                    item_size = request.form.get(f'item_size_{item_key}', '')
                    
                    # Calculate delta
                    delta = new_count - current_qty
                    
                    if delta != 0:
                        # Determine movement type
                        movement_type = 'USAGE' if delta < 0 else 'ADJUSTMENT'
                        
                        # Create movement record
                        movement = MovementHistory(
                            item_name=item_name,
                            item_type=item_type,
                            item_size=item_size,
                            quantity=abs(delta),
                            movement_type=f'BULK_WEEKLY_CHECK_{movement_type}',
                            notes=f'Weekly check: {current_qty} → {new_count} (Δ{delta:+d})',
                            timestamp=datetime.utcnow()
                        )
                        bulk_movements.append(movement)
                        
                        # Update actual item quantities
                        # Find all items with this name/size combination
                        items_to_update = Item.query.filter(
                            and_(
                                Item.name == item_name,
                                Item.type == item_type,
                                Item.size == item_size if item_size else Item.size.is_(None),
                                Item.quantity > 0
                            )
                        ).all()
                        
                        if delta < 0:
                            # Usage - reduce quantities
                            remaining_to_reduce = abs(delta)
                            for item in items_to_update:
                                if remaining_to_reduce <= 0:
                                    break
                                
                                if item.quantity <= remaining_to_reduce:
                                    remaining_to_reduce -= item.quantity
                                    item.quantity = 0
                                else:
                                    item.quantity -= remaining_to_reduce
                                    remaining_to_reduce = 0
                        else:
                            # Adjustment - add to first available item or create new if needed
                            if items_to_update:
                                items_to_update[0].quantity += delta
                            # If no items exist, we'd need to create one, but that's unusual for weekly check
            
            # Save all movements and item updates
            for movement in bulk_movements:
                db.session.add(movement)
            
            # Create audit record
            audit = InventoryAudit(
                user_id=current_user.id,
                bag_id=request.form.get('selected_bag_id', type=int),
                items_checked=len(bulk_movements),
                notes=f'Inventory audit completed with {len(bulk_movements)} items updated'
            )
            db.session.add(audit)
            db.session.flush()  # Get the audit ID before creating undo action
            
            # Create undo action for the entire audit
            if bulk_movements:
                # Store the audit changes for undo
                audit_data = {
                    'audit_id': audit.id,
                    'changes': []
                }
                
                # Store each change made during the audit
                for movement in bulk_movements:
                    change_data = {
                        'item_name': movement.item_name,
                        'item_type': movement.item_type,
                        'item_size': movement.item_size,
                        'quantity_change': -movement.quantity if 'USAGE' in movement.movement_type else movement.quantity,
                        'movement_type': movement.movement_type,
                        'notes': movement.notes
                    }
                    audit_data['changes'].append(change_data)
                
                # Create undo action
                undo_action = UndoAction(
                    action_type='inventory_audit',
                    action_data=json.dumps(audit_data),
                    description=f'Inventory audit with {len(bulk_movements)} item changes',
                    user_id=current_user.id
                )
                db.session.add(undo_action)
            
            db.session.commit()
            
            flash(f'Inventory audit completed successfully! {len(bulk_movements)} items updated.', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing inventory audit: {str(e)}', 'error')
    
    return redirect(url_for('inventory_audit'))

@app.route('/api/update-product', methods=['POST'])
@login_required
def update_product():
    """API endpoint to update product information"""
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        field = data.get('field')
        value = data.get('value')
        
        if not all([product_id, field, value is not None]):
            return jsonify({'success': False, 'message': 'Missing required parameters'})
        
        product = Product.query.get_or_404(product_id)
        
        # Validate field
        if field not in ['name', 'type', 'minimum_stock']:
            return jsonify({'success': False, 'message': 'Invalid field'})
        
        # Special validation for minimum_stock
        if field == 'minimum_stock':
            try:
                value = int(value)
                if value < 0:
                    return jsonify({'success': False, 'message': 'Minimum stock must be non-negative'})
            except ValueError:
                return jsonify({'success': False, 'message': 'Minimum stock must be a number'})
        
        # Check if name already exists for another product
        if field == 'name':
            existing = Product.query.filter(Product.name == value, Product.id != product_id).first()
            if existing:
                return jsonify({'success': False, 'message': 'Product name already exists'})
        
        # Update the field
        setattr(product, field, value)
        
        # Also update all related items if name or type changed
        if field in ['name', 'type']:
            items = Item.query.filter_by(product_id=product_id).all()
            for item in items:
                setattr(item, field, value)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Product updated successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/update-item', methods=['POST'])
@login_required
def update_item():
    """API endpoint to update individual item information"""
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        field = data.get('field')
        value = data.get('value')
        
        if not all([item_id, field]):
            return jsonify({'success': False, 'message': 'Missing required parameters'})
        
        item = Item.query.get_or_404(item_id)
        
        # Validate field
        if field not in ['name', 'type', 'size', 'brand', 'generic_name', 'expiry_date']:
            return jsonify({'success': False, 'message': 'Invalid field'})
        
        # Handle empty string for optional fields
        if field in ['size', 'brand', 'generic_name'] and not value:
            value = None
        
        # Handle expiry_date field with MM/YY format parsing
        if field == 'expiry_date':
            if not value:
                value = None
            else:
                try:
                    # Parse MM/YY format (e.g., "04/26" -> April 2026, day 01)
                    if '/' in value and len(value) == 5:
                        month_str, year_str = value.split('/')
                        month = int(month_str)
                        year = int('20' + year_str)  # Convert YY to 20YY
                        
                        # Validate month
                        if month < 1 or month > 12:
                            return jsonify({'success': False, 'message': 'Invalid month. Use MM/YY format (01-12)'})
                        
                        # Create date object with day 01
                        from datetime import date
                        value = date(year, month, 1)
                    else:
                        return jsonify({'success': False, 'message': 'Invalid expiry date format. Use MM/YY format (e.g., 04/26)'})
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'message': 'Invalid expiry date format. Use MM/YY format (e.g., 04/26)'})
        
        # Update the field
        setattr(item, field, value)
        
        # Update the product if name or type changed
        if field in ['name', 'type'] and item.product:
            # Check if we should update the product too
            # Only update if this is the primary representation
            setattr(item.product, field, value)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Item updated successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

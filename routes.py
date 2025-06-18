import os
import csv
import io
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_, func
from flask_login import login_user, logout_user, login_required, current_user
from app import app, db
from models import Item, Bag, MovementHistory, ItemType, Product, User, BagMinimum, init_default_types, format_datetime_gmt4, format_date_gmt4

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
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
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
                         bags_with_counts=bags_with_counts)

@app.route('/add_items', methods=['GET', 'POST'])
@login_required
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
    return render_template('add_items.html', bags=bags, item_types=item_types)

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
                    
                    # Parse expiry date
                    expiry_date = None
                    if row.get('expiry_date'):
                        try:
                            expiry_date = datetime.strptime(row['expiry_date'], '%Y-%m-%d').date()
                        except ValueError:
                            try:
                                expiry_date = datetime.strptime(row['expiry_date'], '%m/%d/%Y').date()
                            except ValueError:
                                errors.append(f"Row {row_num}: Invalid expiry date format")
                                continue
                    
                    # Create item
                    item = Item(
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
                    # Parse expiry date
                    expiry_date = None
                    if i < len(expiry_dates) and expiry_dates[i].strip():
                        try:
                            expiry_date = datetime.strptime(expiry_dates[i], '%Y-%m-%d').date()
                        except ValueError:
                            flash(f"Invalid expiry date format for item {i+1}", "warning")
                            continue
                    
                    # Get additional fields safely
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
                    
                    # Create item
                    item = Item(
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
    expiry_filter = request.args.get('expiry', '')
    
    # Base query - get products with their items
    product_query = Product.query
    
    # Apply product-level filters
    if search:
        product_query = product_query.filter(Product.name.ilike(f'%{search}%'))
    
    if type_filter:
        product_query = product_query.filter(Product.type == type_filter)
    
    products = product_query.order_by(Product.name).all()
    
    # Filter products based on item-level criteria and group items
    filtered_products = []
    for product in products:
        # Get active items for this product
        item_query = Item.query.filter(Item.product_id == product.id, Item.quantity > 0).join(Bag)
        
        # Apply item-level filters
        if bag_filter:
            item_query = item_query.filter(Bag.name == bag_filter)
        
        if expiry_filter:
            today = date.today()
            if expiry_filter == 'expired':
                item_query = item_query.filter(and_(Item.expiry_date.isnot(None), Item.expiry_date < today))
            elif expiry_filter == 'expiring':
                thirty_days = today + timedelta(days=30)
                item_query = item_query.filter(and_(Item.expiry_date.isnot(None), 
                                                Item.expiry_date >= today, 
                                                Item.expiry_date <= thirty_days))
        
        items = item_query.order_by(Item.brand, Item.size, Item.expiry_date).all()
        
        if items:  # Only include products that have matching items
            # Group items by brand, size, and expiry date
            grouped_items = []
            current_group = None
            
            for item in items:
                # Create a key for grouping (brand, size, expiry_date)
                group_key = (item.brand or 'No Brand', item.size or 'No Size', item.expiry_date)
                
                if current_group is None or current_group['key'] != group_key:
                    # Start a new group
                    current_group = {
                        'key': group_key,
                        'brand': item.brand,
                        'size': item.size,
                        'expiry_date': item.expiry_date,
                        'items': [item],
                        'total_quantity': item.quantity,
                        'bags': [item.bag]
                    }
                    grouped_items.append(current_group)
                else:
                    # Add to existing group
                    current_group['items'].append(item)
                    current_group['total_quantity'] += item.quantity
                    if item.bag not in current_group['bags']:
                        current_group['bags'].append(item.bag)
            
            filtered_products.append({
                'product': product,
                'grouped_items': grouped_items,
                'total_quantity': sum(item.quantity for item in items),
                'is_low_stock': product.is_low_stock
            })
    
    # Get filter options
    bags = Bag.query.all()
    item_types = db.session.query(Product.type).distinct().all()
    item_types = [t[0] for t in item_types]
    
    return render_template('inventory.html',
                         products=filtered_products,
                         bags=bags,
                         item_types=item_types,
                         today=date.today(),
                         current_filters={
                             'search': search,
                             'type': type_filter,
                             'bag': bag_filter,
                             'expiry': expiry_filter
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
                bag_id=to_bag_id
            )
            db.session.add(new_item)
        
        # Reduce quantity from source item
        item.quantity -= quantity
        item.updated_at = datetime.utcnow()
        
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
        
        db.session.commit()
        flash(f"Successfully transferred {quantity} units of {item.name} from {from_bag.name} to {to_bag.name}", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error during transfer: {str(e)}", "danger")
    
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
    today = date.today()
    thirty_days = today + timedelta(days=30)
    
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
    
    return render_template('expiry.html', 
                         expired_items=expired_items, 
                         expiring_items=expiring_items,
                         today=today)

@app.route('/bags', methods=['GET', 'POST'])
@login_required
def bags():
    if request.method == 'POST':
        return handle_bag_management()
    
    bags = Bag.query.all()
    return render_template('bags.html', bags=bags)

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
            
            # Check if storage location has items
            if bag.get_total_items() > 0:
                storage_type = "cabinet" if bag.location == "cabinet" else "medical bag"
                flash(f"Cannot delete {storage_type} with items. Please transfer items first.", "danger")
                return redirect(url_for('bags'))
            
            storage_type = "cabinet" if bag.location == "cabinet" else "medical bag"
            storage_name = bag.name
            db.session.delete(bag)
            db.session.commit()
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
    
    # Get expired items for disposal
    today = date.today()
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
    
    # Get the product this item belongs to
    product = item.product
    
    # Get all items for this product across all locations
    items = Item.query.filter_by(product_id=product.id).order_by(Item.bag_id, Item.quantity.desc()).all()
    
    # Get movement history for this product
    movements = MovementHistory.query.filter(
        db.and_(
            MovementHistory.item_name == product.name,
            MovementHistory.item_type == product.type
        )
    ).order_by(MovementHistory.timestamp.desc()).limit(50).all()
    
    # Get all bags for transfer functionality
    bags = Bag.query.order_by(Bag.name).all()
    
    return render_template('individual_item_history.html', 
                         product=product,
                         items=items, 
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
    
    # Search in current inventory
    items = db.session.query(Item.name, Item.type, Item.brand, Item.size).filter(
        Item.name.ilike(f'%{query}%')
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

@app.route('/weekly_check')
@login_required
def weekly_check():
    """Display weekly check page for consumable items separated by storage location"""
    # Get selected bag/storage from query parameter
    selected_bag_id = request.args.get('bag_id', type=int)
    
    # Get all bags for selection dropdown
    all_bags = Bag.query.order_by(Bag.location.desc(), Bag.name).all()
    
    # Get all items that require weekly check (types 4 and 5)
    weekly_check_types = ['Consumable Dressings/Swabs', 'Catheters & Containers']
    
    # Base query for consumable items
    query = Item.query.join(Bag).filter(
        and_(
            Item.type.in_(weekly_check_types),
            Item.quantity > 0
        )
    )
    
    # Filter by selected bag if specified
    if selected_bag_id:
        query = query.filter(Item.bag_id == selected_bag_id)
        selected_bag = Bag.query.get(selected_bag_id)
    else:
        selected_bag = None
    
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
    
    return render_template('weekly_check.html', 
                         grouped_items=grouped_items,
                         all_bags=all_bags,
                         selected_bag=selected_bag)

@app.route('/weekly_check', methods=['POST'])
@login_required
def handle_weekly_check():
    """Process weekly check form submission"""
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
            
            db.session.commit()
            
            flash(f'Weekly check completed successfully! {len(bulk_movements)} items updated.', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing weekly check: {str(e)}', 'error')
    
    return redirect(url_for('weekly_check'))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

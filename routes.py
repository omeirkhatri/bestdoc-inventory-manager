import os
import csv
import io
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_, func
from app import app, db
from models import Item, Bag, MovementHistory, ItemType, init_default_types

@app.route('/')
def dashboard():
    # Initialize default types if needed
    init_default_types()
    
    # Get dashboard statistics
    total_items = db.session.query(func.sum(Item.quantity)).scalar() or 0
    total_unique_items = Item.query.count()
    total_bags = Bag.query.count()
    
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
    
    # Low stock items (quantity <= 5)
    low_stock_items = Item.query.filter(
        and_(Item.quantity <= 5, Item.quantity > 0)
    ).all()
    
    # Recent movements
    recent_movements = MovementHistory.query.order_by(
        MovementHistory.timestamp.desc()
    ).limit(10).all()
    
    # Bag statistics
    bags_with_counts = []
    for bag in Bag.query.all():
        item_count = sum(item.quantity for item in bag.items if item.quantity > 0)
        bags_with_counts.append({
            'name': bag.name,
            'count': item_count,
            'unique_items': len([item for item in bag.items if item.quantity > 0])
        })
    
    return render_template('dashboard.html',
                         total_items=total_items,
                         total_unique_items=total_unique_items,
                         total_bags=total_bags,
                         expiring_items=expiring_items,
                         expired_items=expired_items,
                         low_stock_items=low_stock_items,
                         recent_movements=recent_movements,
                         bags_with_counts=bags_with_counts)

@app.route('/add_items', methods=['GET', 'POST'])
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
                        size=row.get('size', '').strip() or None,
                        quantity=int(row['quantity']),
                        expiry_date=expiry_date,
                        batch_number=row.get('batch_number', '').strip() or None,
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
        sizes = request.form.getlist('size')
        quantities = request.form.getlist('quantity')
        expiry_dates = request.form.getlist('expiry_date')
        batch_numbers = request.form.getlist('batch_number')
        bag_id = request.form.get('bag_id')
        
        if not bag_id:
            flash("Please select a bag", "danger")
            return redirect(url_for('add_items'))
        
        bag = Bag.query.get_or_404(bag_id)
        items_added = 0
        
        for i in range(len(names)):
            if names[i].strip() and types[i].strip() and quantities[i].strip():
                # Parse expiry date
                expiry_date = None
                if expiry_dates[i].strip():
                    try:
                        expiry_date = datetime.strptime(expiry_dates[i], '%Y-%m-%d').date()
                    except ValueError:
                        flash(f"Invalid expiry date format for item {i+1}", "warning")
                        continue
                
                # Create item
                item = Item(
                    name=names[i].strip(),
                    type=types[i].strip(),
                    size=sizes[i].strip() if sizes[i].strip() else None,
                    quantity=int(quantities[i]),
                    expiry_date=expiry_date,
                    batch_number=batch_numbers[i].strip() if batch_numbers[i].strip() else None,
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
def inventory():
    # Get filter parameters
    search = request.args.get('search', '')
    type_filter = request.args.get('type', '')
    bag_filter = request.args.get('bag', '')
    expiry_filter = request.args.get('expiry', '')
    
    # Base query
    query = Item.query.join(Bag)
    
    # Apply filters
    if search:
        query = query.filter(
            or_(
                Item.name.ilike(f'%{search}%'),
                Item.size.ilike(f'%{search}%'),
                Item.batch_number.ilike(f'%{search}%')
            )
        )
    
    if type_filter:
        query = query.filter(Item.type == type_filter)
    
    if bag_filter:
        query = query.filter(Bag.name == bag_filter)
    
    if expiry_filter:
        today = date.today()
        if expiry_filter == 'expired':
            query = query.filter(and_(Item.expiry_date.isnot(None), Item.expiry_date < today))
        elif expiry_filter == 'expiring':
            thirty_days = today + timedelta(days=30)
            query = query.filter(and_(Item.expiry_date.isnot(None), 
                                    Item.expiry_date >= today, 
                                    Item.expiry_date <= thirty_days))
    
    # Get items with positive quantity
    items = query.filter(Item.quantity > 0).order_by(Item.name, Item.expiry_date).all()
    
    # Get filter options
    bags = Bag.query.all()
    item_types = db.session.query(Item.type).distinct().all()
    item_types = [t[0] for t in item_types]
    
    return render_template('inventory.html',
                         items=items,
                         bags=bags,
                         item_types=item_types,
                         current_filters={
                             'search': search,
                             'type': type_filter,
                             'bag': bag_filter,
                             'expiry': expiry_filter
                         })

@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if request.method == 'POST':
        return handle_transfer()
    
    bags = Bag.query.all()
    cabinet = Bag.query.filter_by(name='Cabinet').first()
    cabinet_items = []
    
    if cabinet:
        # Group items by name, type, size for FIFO display
        cabinet_items = Item.query.filter_by(bag_id=cabinet.id).filter(Item.quantity > 0).order_by(Item.name, Item.expiry_date).all()
    
    return render_template('transfer.html', bags=bags, cabinet_items=cabinet_items)

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
            batch_number=item.batch_number,
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
                size=item.size,
                quantity=quantity,
                expiry_date=item.expiry_date,
                batch_number=item.batch_number,
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
def usage():
    if request.method == 'POST':
        return handle_usage()
    
    bags = Bag.query.all()
    bag_items = {}
    
    for bag in bags:
        if bag.name != 'Cabinet':  # Only show non-cabinet bags for usage
            bag_items[bag.name] = Item.query.filter_by(bag_id=bag.id).filter(Item.quantity > 0).order_by(Item.name).all()
    
    return render_template('usage.html', bags=bags, bag_items=bag_items)

def handle_usage():
    try:
        item_id = request.form.get('item_id')
        quantity_used = int(request.form.get('quantity', 0))
        notes = request.form.get('notes', '')
        
        if not item_id or quantity_used <= 0:
            flash("Please provide valid usage details", "danger")
            return redirect(url_for('usage'))
        
        item = Item.query.get_or_404(item_id)
        
        if quantity_used > item.quantity:
            flash("Cannot use more items than available", "danger")
            return redirect(url_for('usage'))
        
        # Reduce quantity
        item.quantity -= quantity_used
        item.updated_at = datetime.utcnow()
        
        # Log the usage
        movement = MovementHistory(
            item_name=item.name,
            item_type=item.type,
            item_size=item.size,
            quantity=quantity_used,
            movement_type='usage',
            from_bag=item.bag.name,
            notes=notes or f"Used {quantity_used} units"
        )
        db.session.add(movement)
        
        db.session.commit()
        flash(f"Successfully recorded usage of {quantity_used} units of {item.name}", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error recording usage: {str(e)}", "danger")
    
    return redirect(url_for('usage'))

@app.route('/history')
def history():
    page = request.args.get('page', 1, type=int)
    movements = MovementHistory.query.order_by(MovementHistory.timestamp.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    return render_template('history.html', movements=movements)

@app.route('/expiry')
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
            
            if not name:
                flash("Bag name is required", "danger")
                return redirect(url_for('bags'))
            
            if Bag.query.filter_by(name=name).first():
                flash("Bag with this name already exists", "danger")
                return redirect(url_for('bags'))
            
            bag = Bag(name=name, description=description)
            db.session.add(bag)
            db.session.commit()
            flash(f"Successfully created bag: {name}", "success")
            
        elif action == 'edit':
            bag_id = request.form.get('bag_id')
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            
            if not bag_id or not name:
                flash("Bag ID and name are required", "danger")
                return redirect(url_for('bags'))
            
            bag = Bag.query.get_or_404(bag_id)
            
            # Check if name is taken by another bag
            existing = Bag.query.filter_by(name=name).first()
            if existing and existing.id != bag.id:
                flash("Bag with this name already exists", "danger")
                return redirect(url_for('bags'))
            
            bag.name = name
            bag.description = description
            db.session.commit()
            flash(f"Successfully updated bag: {name}", "success")
            
        elif action == 'delete':
            bag_id = request.form.get('bag_id')
            bag = Bag.query.get_or_404(bag_id)
            
            # Don't allow deleting Cabinet
            if bag.name == 'Cabinet':
                flash("Cannot delete the Cabinet bag", "danger")
                return redirect(url_for('bags'))
            
            # Check if bag has items
            if bag.items:
                flash("Cannot delete bag with items. Please transfer items first.", "danger")
                return redirect(url_for('bags'))
            
            db.session.delete(bag)
            db.session.commit()
            flash("Successfully deleted bag", "success")
    
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    
    return redirect(url_for('bags'))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

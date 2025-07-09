# Healthcare Inventory Management System

## Overview

This is a Flask-based healthcare inventory management system designed for medical facilities to track supplies, equipment, and medications. The system provides comprehensive inventory tracking with features including item management, expiry monitoring, usage tracking, transfer management, and audit capabilities.

## System Architecture

### Backend Architecture
- **Framework**: Flask (Python web framework)
- **Database**: SQLAlchemy ORM with SQLite/PostgreSQL support
- **Authentication**: Flask-Login for session management
- **Database Models**: Declarative Base with comprehensive medical inventory schema

### Frontend Architecture
- **Template Engine**: Jinja2 with Flask
- **CSS Framework**: Bootstrap 5 with dark theme
- **JavaScript**: Vanilla JS with Chart.js for data visualization
- **Icons**: Font Awesome for UI consistency
- **Tables**: DataTables for advanced table functionality

### Database Design
- **User Management**: Authentication with username/password
- **Inventory Structure**: Items organized by bags/cabinets with product categorization
- **Movement Tracking**: Complete audit trail for all inventory movements
- **Expiry Management**: Date-based expiry tracking and alerts

## Key Components

### Core Models
- **User**: Authentication and user management
- **Item**: Individual inventory items with quantities and expiry dates
- **Product**: Product master data for item categorization
- **Bag**: Storage location management (cabinets/medical bags)
- **MovementHistory**: Complete audit trail of all inventory changes
- **ItemType**: Product categorization system

### Main Features
1. **Dashboard**: Overview with statistics and Friday audit reminders
2. **Inventory Management**: Add, edit, and track all medical supplies
3. **Transfer System**: Move items between storage locations
4. **Usage Tracking**: Record consumption and usage patterns
5. **Expiry Monitor**: Track and alert on expiring items
6. **Wastage Tracking**: Handle expired item disposal
7. **Audit System**: Regular inventory count verification
8. **History Tracking**: Complete movement and change history

### Authentication System
- Session-based authentication using Flask-Login
- User registration and password management
- Protected routes requiring authentication
- Session management with logout functionality

## Data Flow

### Inventory Operations
1. Items are added to specific storage locations (bags/cabinets)
2. All movements are logged in MovementHistory table
3. Quantities are automatically updated based on usage/transfers
4. Expiry dates trigger alerts and disposal workflows

### Audit Process
1. Weekly consumables audit reminders (Friday alerts)
2. Location-specific inventory checking
3. Automatic usage calculation based on count differences
4. Historical audit trail maintenance

### Transfer Workflow
1. Items can be moved between storage locations
2. Quantity adjustments are tracked
3. Movement history maintains complete audit trail
4. Real-time inventory level updates

## External Dependencies

### Python Packages
- Flask: Web framework
- Flask-SQLAlchemy: Database ORM
- Flask-Login: Authentication management
- Werkzeug: WSGI utilities and security
- PyTZ: Timezone handling (GMT+4 support)

### Frontend Libraries
- Bootstrap 5: UI framework with dark theme
- Font Awesome 6: Icon library
- Chart.js: Data visualization
- DataTables: Advanced table functionality

### Database Support
- SQLite: Default development database
- PostgreSQL: Production database support via DATABASE_URL environment variable

## Deployment Strategy

### Environment Configuration
- **SESSION_SECRET**: Session encryption key
- **DATABASE_URL**: Database connection string
- **MAX_CONTENT_LENGTH**: File upload size limit (16MB)

### Database Configuration
- Connection pooling with 300-second recycle time
- Pre-ping enabled for connection health checks
- Support for both SQLite (development) and PostgreSQL (production)

### Proxy Configuration
- ProxyFix middleware for proper header handling
- Support for reverse proxy deployments

### File Handling
- CSV import/export functionality
- Secure filename handling
- File size restrictions

## Changelog
- July 09, 2025. Removed Admin Panel page and created accordion-style user menu - Consolidated all admin functionality into user profile page, replaced static user menu with collapsible accordion showing "username [admin]" when collapsed
- July 09, 2025. Created comprehensive user profile management page - Added first_name and last_name fields to User model, created unified profile page with personal info management, password change, and admin user management (add/edit/delete users)
- July 09, 2025. Fixed undo functionality for multi-transfer actions - Added support for multi_transfer action type that was missing from undo system
- July 09, 2025. Fixed History page DataTable conflict - Disabled client-side DataTable that was overriding server-side pagination, ensuring Dashboard and History show identical data
- July 09, 2025. Fixed History page date filter parsing for month inputs - History now shows all movements correctly
- July 09, 2025. Fixed transfer form data handling for single item transfers - Transfer functionality now works properly
- July 01, 2025. Initial setup

## User Preferences

Preferred communication style: Simple, everyday language.
// Healthcare Inventory Management System - Main JavaScript

// Global configuration
const INVENTORY_CONFIG = {
    dateFormat: 'MM/dd/yyyy',
    lowStockThreshold: 5,
    expiryWarningDays: 30,
    maxFileSize: 16 * 1024 * 1024 // 16MB
};

// Utility functions
const Utils = {
    // Format date for display
    formatDate: function(dateString) {
        if (!dateString) return 'No expiry';
        const date = new Date(dateString);
        return date.toLocaleDateString('en-US');
    },

    // Calculate days until expiry
    daysUntilExpiry: function(expiryDate) {
        if (!expiryDate) return null;
        const today = new Date();
        const expiry = new Date(expiryDate);
        const timeDiff = expiry.getTime() - today.getTime();
        return Math.ceil(timeDiff / (1000 * 3600 * 24));
    },

    // Get expiry status
    getExpiryStatus: function(expiryDate) {
        const days = this.daysUntilExpiry(expiryDate);
        if (days === null) return 'no-expiry';
        if (days < 0) return 'expired';
        if (days <= INVENTORY_CONFIG.expiryWarningDays) return 'expiring';
        return 'good';
    },

    // Format quantity with low stock indication
    formatQuantity: function(quantity) {
        const isLowStock = quantity <= INVENTORY_CONFIG.lowStockThreshold;
        return {
            value: quantity,
            isLowStock: isLowStock,
            class: isLowStock ? 'text-warning' : 'text-primary'
        };
    },

    // Validate file type and size
    validateFile: function(file, allowedTypes = ['.csv']) {
        const errors = [];
        
        if (!file) {
            errors.push('No file selected');
            return errors;
        }
        
        // Check file type
        const fileExtension = '.' + file.name.split('.').pop().toLowerCase();
        if (!allowedTypes.includes(fileExtension)) {
            errors.push(`Invalid file type. Allowed types: ${allowedTypes.join(', ')}`);
        }
        
        // Check file size
        if (file.size > INVENTORY_CONFIG.maxFileSize) {
            errors.push(`File too large. Maximum size: ${(INVENTORY_CONFIG.maxFileSize / 1024 / 1024).toFixed(1)}MB`);
        }
        
        return errors;
    },

    // Debounce function for search inputs
    debounce: function(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // Show toast notification
    showToast: function(message, type = 'info') {
        // Create toast container if it doesn't exist
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
            toastContainer.style.zIndex = '9999';
            document.body.appendChild(toastContainer);
        }

        // Create toast element
        const toastId = 'toast-' + Date.now();
        const toastHtml = `
            <div id="${toastId}" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header">
                    <i class="fas fa-${this.getToastIcon(type)} me-2"></i>
                    <strong class="me-auto">${this.getToastTitle(type)}</strong>
                    <small>just now</small>
                    <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;

        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
        
        // Show toast
        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement);
        toast.show();

        // Remove toast element after hiding
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
    },

    getToastIcon: function(type) {
        const icons = {
            'success': 'check-circle',
            'error': 'exclamation-triangle',
            'warning': 'exclamation-circle',
            'info': 'info-circle'
        };
        return icons[type] || 'info-circle';
    },

    getToastTitle: function(type) {
        const titles = {
            'success': 'Success',
            'error': 'Error',
            'warning': 'Warning',
            'info': 'Information'
        };
        return titles[type] || 'Information';
    }
};

// Form validation helpers
const FormValidation = {
    // Validate required fields
    validateRequired: function(form, fieldNames) {
        const errors = [];
        fieldNames.forEach(fieldName => {
            const field = form.querySelector(`[name="${fieldName}"]`);
            if (!field || !field.value.trim()) {
                errors.push(`${fieldName.replace('_', ' ')} is required`);
            }
        });
        return errors;
    },

    // Validate numeric fields
    validateNumeric: function(form, fieldNames, options = {}) {
        const errors = [];
        fieldNames.forEach(fieldName => {
            const field = form.querySelector(`[name="${fieldName}"]`);
            if (field && field.value) {
                const value = parseFloat(field.value);
                if (isNaN(value)) {
                    errors.push(`${fieldName.replace('_', ' ')} must be a number`);
                } else {
                    if (options.min !== undefined && value < options.min) {
                        errors.push(`${fieldName.replace('_', ' ')} must be at least ${options.min}`);
                    }
                    if (options.max !== undefined && value > options.max) {
                        errors.push(`${fieldName.replace('_', ' ')} must be at most ${options.max}`);
                    }
                }
            }
        });
        return errors;
    },

    // Validate date fields
    validateDates: function(form, fieldNames) {
        const errors = [];
        fieldNames.forEach(fieldName => {
            const field = form.querySelector(`[name="${fieldName}"]`);
            if (field && field.value) {
                const date = new Date(field.value);
                if (isNaN(date.getTime())) {
                    errors.push(`${fieldName.replace('_', ' ')} is not a valid date`);
                }
            }
        });
        return errors;
    },

    // Show validation errors
    showErrors: function(errors) {
        if (errors.length > 0) {
            const errorMessage = errors.join('\n');
            Utils.showToast(errorMessage, 'error');
            return false;
        }
        return true;
    }
};

// Search and filter functionality
const SearchFilter = {
    // Initialize search functionality
    init: function() {
        // Add search functionality to tables
        this.initTableSearch();
        
        // Add filter functionality
        this.initFilters();
        
        // Add quick filter buttons
        this.initQuickFilters();
    },

    initTableSearch: function() {
        const searchInputs = document.querySelectorAll('[data-search-table]');
        searchInputs.forEach(input => {
            const tableId = input.getAttribute('data-search-table');
            const table = document.getElementById(tableId);
            
            if (table) {
                const debouncedSearch = Utils.debounce((searchTerm) => {
                    this.searchTable(table, searchTerm);
                }, 300);
                
                input.addEventListener('input', (e) => {
                    debouncedSearch(e.target.value);
                });
            }
        });
    },

    searchTable: function(table, searchTerm) {
        const rows = table.querySelectorAll('tbody tr');
        const term = searchTerm.toLowerCase();
        
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            const isVisible = text.includes(term);
            row.style.display = isVisible ? '' : 'none';
        });
        
        // Update visible count if element exists
        const countElement = document.querySelector(`[data-count-for="${table.id}"]`);
        if (countElement) {
            const visibleRows = Array.from(rows).filter(row => row.style.display !== 'none');
            countElement.textContent = visibleRows.length;
        }
    },

    initFilters: function() {
        const filterForms = document.querySelectorAll('[data-filter-form]');
        filterForms.forEach(form => {
            // Auto-submit on filter change (optional)
            const autoSubmit = form.hasAttribute('data-auto-submit');
            if (autoSubmit) {
                const filterInputs = form.querySelectorAll('select, input[type="date"]');
                filterInputs.forEach(input => {
                    input.addEventListener('change', () => {
                        form.submit();
                    });
                });
            }
        });
    },

    initQuickFilters: function() {
        const quickFilterButtons = document.querySelectorAll('[data-quick-filter]');
        quickFilterButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                const filterValue = button.getAttribute('data-quick-filter');
                const targetInput = document.querySelector(button.getAttribute('data-target'));
                
                if (targetInput) {
                    targetInput.value = filterValue;
                    
                    // Trigger form submission if auto-submit is enabled
                    const form = targetInput.closest('form');
                    if (form && form.hasAttribute('data-auto-submit')) {
                        form.submit();
                    }
                }
            });
        });
    }
};

// Modal management
const ModalManager = {
    // Show confirmation modal
    showConfirmation: function(title, message, onConfirm, options = {}) {
        const modalId = 'confirmation-modal-' + Date.now();
        const modalHtml = `
            <div class="modal fade" id="${modalId}" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header ${options.headerClass || ''}">
                            <h5 class="modal-title">${title}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            ${message}
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn ${options.confirmClass || 'btn-primary'}" id="${modalId}-confirm">
                                ${options.confirmText || 'Confirm'}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
        const modalElement = document.getElementById(modalId);
        const modal = new bootstrap.Modal(modalElement);
        
        // Handle confirm button
        document.getElementById(`${modalId}-confirm`).addEventListener('click', () => {
            modal.hide();
            if (typeof onConfirm === 'function') {
                onConfirm();
            }
        });
        
        // Clean up after modal is hidden
        modalElement.addEventListener('hidden.bs.modal', () => {
            modalElement.remove();
        });
        
        modal.show();
    },

    // Show loading modal
    showLoading: function(message = 'Loading...') {
        const modalId = 'loading-modal';
        let modalElement = document.getElementById(modalId);
        
        if (!modalElement) {
            const modalHtml = `
                <div class="modal fade" id="${modalId}" tabindex="-1" data-bs-backdrop="static" data-bs-keyboard="false">
                    <div class="modal-dialog modal-sm">
                        <div class="modal-content">
                            <div class="modal-body text-center py-4">
                                <div class="spinner-border text-primary mb-3" role="status">
                                    <span class="visually-hidden">Loading...</span>
                                </div>
                                <div id="loading-message">${message}</div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            modalElement = document.getElementById(modalId);
        } else {
            document.getElementById('loading-message').textContent = message;
        }
        
        const modal = new bootstrap.Modal(modalElement);
        modal.show();
        
        return modal;
    },

    // Hide loading modal
    hideLoading: function() {
        const modalElement = document.getElementById('loading-modal');
        if (modalElement) {
            const modal = bootstrap.Modal.getInstance(modalElement);
            if (modal) {
                modal.hide();
            }
        }
    }
};

// Data export functionality
const DataExport = {
    // Export table to CSV
    exportTableToCSV: function(tableId, filename) {
        const table = document.getElementById(tableId);
        if (!table) {
            Utils.showToast('Table not found', 'error');
            return;
        }
        
        const csv = this.tableToCSV(table);
        this.downloadCSV(csv, filename);
    },

    tableToCSV: function(table) {
        const rows = table.querySelectorAll('tr');
        const csvRows = [];
        
        rows.forEach(row => {
            const cells = row.querySelectorAll('th, td');
            const csvRow = [];
            
            cells.forEach(cell => {
                // Clean up cell content
                let cellText = cell.textContent.trim();
                // Remove extra whitespace and line breaks
                cellText = cellText.replace(/\s+/g, ' ');
                // Escape quotes
                cellText = cellText.replace(/"/g, '""');
                csvRow.push(`"${cellText}"`);
            });
            
            if (csvRow.length > 0) {
                csvRows.push(csvRow.join(','));
            }
        });
        
        return csvRows.join('\n');
    },

    downloadCSV: function(csv, filename) {
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        
        if (link.download !== undefined) {
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            link.setAttribute('download', filename);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
        }
    }
};

// Real-time updates and notifications
const NotificationManager = {
    // Check for expiring items and show notifications
    checkExpiringItems: function() {
        // This would typically fetch data from the server
        // For now, we'll check existing page data
        const expiringElements = document.querySelectorAll('[data-expiry-status="expiring"]');
        const expiredElements = document.querySelectorAll('[data-expiry-status="expired"]');
        
        if (expiredElements.length > 0) {
            Utils.showToast(`${expiredElements.length} items have expired!`, 'error');
        } else if (expiringElements.length > 0) {
            Utils.showToast(`${expiringElements.length} items are expiring soon`, 'warning');
        }
    },

    // Periodic check for updates
    startPeriodicChecks: function(intervalMinutes = 30) {
        setInterval(() => {
            this.checkExpiringItems();
        }, intervalMinutes * 60 * 1000);
    }
};

// Keyboard shortcuts
const KeyboardShortcuts = {
    init: function() {
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + K for quick search
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                const searchInput = document.querySelector('input[type="search"], input[placeholder*="search" i]');
                if (searchInput) {
                    searchInput.focus();
                }
            }
            
            // Ctrl/Cmd + N for add new (when on specific pages)
            if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
                const addButton = document.querySelector('a[href*="add"], button[data-action="add"]');
                if (addButton && !e.target.closest('input, textarea')) {
                    e.preventDefault();
                    addButton.click();
                }
            }
        });
    }
};

// Product Management for Add Items
const ProductManager = {
    init: function() {
        // Add event listeners for item name inputs
        document.querySelectorAll('.item-name-input').forEach(input => {
            this.attachProductChecker(input);
            this.attachItemSearch(input);
        });
        
        // Handle dynamic row addition
        const addRowBtn = document.getElementById('addRowBtn');
        if (addRowBtn) {
            addRowBtn.addEventListener('click', () => {
                this.addNewItemRow();
            });
        }
        
        // Handle row cloning
        document.addEventListener('click', (e) => {
            if (e.target.closest('.clone-item-btn')) {
                const row = e.target.closest('.item-row');
                const nameInput = row.querySelector('input[name="name"]');
                const typeSelect = row.querySelector('select[name="type"]');
                
                if (nameInput.value.trim() && typeSelect.value) {
                    this.cloneItemRow(row);
                } else {
                    alert('Please fill in the item name and type before duplicating');
                }
            }
            if (e.target.closest('.remove-row')) {
                this.removeItemRow(e.target.closest('.item-row'));
            }
        });
    },

    attachItemSearch: function(input) {
        if (!input) return;
        
        const suggestionsContainer = input.nextElementSibling;
        if (!suggestionsContainer || !suggestionsContainer.classList.contains('item-suggestions')) {
            return;
        }
        
        let debounceTimer;
        
        input.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            const query = e.target.value.trim();
            
            if (query.length < 2) {
                this.hideSuggestions(suggestionsContainer);
                return;
            }
            
            debounceTimer = setTimeout(() => {
                this.searchItems(input, query);
            }, 300);
        });
        
        // Hide suggestions when clicking outside
        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !suggestionsContainer.contains(e.target)) {
                this.hideSuggestions(suggestionsContainer);
            }
        });
    },

    searchItems: function(input, query) {
        const suggestionsContainer = input.nextElementSibling;
        
        fetch(`/api/search_items?q=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(data => {
                this.showSuggestions(input, suggestionsContainer, data);
            })
            .catch(error => {
                console.warn('Error searching items:', error);
                this.hideSuggestions(suggestionsContainer);
            });
    },

    showSuggestions: function(input, container, items) {
        if (!items || items.length === 0) {
            this.hideSuggestions(container);
            return;
        }
        
        // Clear container first
        container.innerHTML = '';
        
        // Create elements safely without innerHTML
        items.forEach(item => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'dropdown-item suggestion-item';
            button.setAttribute('data-name', item.name);
            button.setAttribute('data-type', item.type);
            button.setAttribute('data-brand', item.brand || '');
            button.setAttribute('data-size', item.size || '');
            
            const nameDiv = document.createElement('div');
            nameDiv.className = 'fw-bold';
            nameDiv.textContent = item.name;
            
            const detailsSmall = document.createElement('small');
            detailsSmall.className = 'text-muted';
            const detailsText = item.type + 
                (item.brand ? ' - ' + item.brand : '') + 
                (item.size ? ' (' + item.size + ')' : '');
            detailsSmall.textContent = detailsText;
            
            button.appendChild(nameDiv);
            button.appendChild(detailsSmall);
            container.appendChild(button);
        });
        container.style.display = 'block';
        
        // Add click handlers to suggestions
        container.querySelectorAll('.suggestion-item').forEach(item => {
            item.addEventListener('click', (e) => {
                this.selectSuggestion(input, e.target.closest('.suggestion-item'));
            });
        });
    },

    selectSuggestion: function(input, suggestionItem) {
        const row = input.closest('.item-row');
        const name = suggestionItem.getAttribute('data-name');
        const type = suggestionItem.getAttribute('data-type');
        const brand = suggestionItem.getAttribute('data-brand');
        const size = suggestionItem.getAttribute('data-size');
        
        // Fill in the form fields
        input.value = name;
        
        const typeSelect = row.querySelector('select[name="type"]');
        if (typeSelect && type) {
            typeSelect.value = type;
        }
        
        const brandInput = row.querySelector('input[name="brand"]');
        if (brandInput && brand) {
            brandInput.value = brand;
        }
        
        const sizeInput = row.querySelector('input[name="size"]');
        if (sizeInput && size) {
            sizeInput.value = size;
        }
        
        // Hide suggestions
        const suggestionsContainer = input.nextElementSibling;
        this.hideSuggestions(suggestionsContainer);
        
        // Trigger product check to update minimum stock field
        this.checkExistingProduct(input);
    },

    hideSuggestions: function(container) {
        if (container) {
            container.style.display = 'none';
            container.innerHTML = '';
        }
    },
    
    attachProductChecker: function(input) {
        if (!input) return;
        
        let debounceTimer;
        
        input.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                this.checkExistingProduct(e.target);
            }, 500);
        });
    },
    
    checkExistingProduct: function(input) {
        const productName = input.value.trim();
        const row = input.closest('.item-row');
        const minimumStockInput = row.querySelector('.minimum-stock-input');
        
        if (!productName || productName.length < 2) {
            this.toggleMinimumStockField(minimumStockInput, true);
            return;
        }
        
        fetch(`/api/check_existing_product?name=${encodeURIComponent(productName)}`)
            .then(response => response.json())
            .then(data => {
                if (data.exists) {
                    // Product exists - hide minimum stock field and populate type
                    this.toggleMinimumStockField(minimumStockInput, false);
                    
                    const typeSelect = row.querySelector('select[name="type"]');
                    if (typeSelect && data.type) {
                        typeSelect.value = data.type;
                    }
                } else {
                    // New product - show minimum stock field
                    this.toggleMinimumStockField(minimumStockInput, true);
                }
            })
            .catch(error => {
                console.warn('Error checking product existence:', error);
                // Default to showing minimum stock field
                this.toggleMinimumStockField(minimumStockInput, true);
            });
    },
    
    toggleMinimumStockField: function(input, show) {
        if (!input) return;
        
        const container = input.closest('.col-md-5');
        if (!container) return;
        
        if (show) {
            container.style.display = 'block';
            input.removeAttribute('disabled');
        } else {
            container.style.display = 'none';
            input.setAttribute('disabled', 'disabled');
            input.value = '';
        }
    },
    
    addNewItemRow: function() {
        const itemRows = document.getElementById('itemRows');
        const firstRow = itemRows.querySelector('.item-row');
        const newRow = firstRow.cloneNode(true);
        
        // Clear all inputs
        newRow.querySelectorAll('input, select').forEach(field => {
            if (field.type === 'checkbox' || field.type === 'radio') {
                field.checked = false;
            } else {
                field.value = '';
            }
        });
        
        // Show remove button
        const removeBtn = newRow.querySelector('.remove-row');
        if (removeBtn) {
            removeBtn.style.display = 'block';
        }
        
        // Attach product checker and item search to new name input
        const nameInput = newRow.querySelector('.item-name-input');
        if (nameInput) {
            this.attachProductChecker(nameInput);
            this.attachItemSearch(nameInput);
        }
        
        // Show minimum stock field by default for new rows
        const minimumStockInput = newRow.querySelector('.minimum-stock-input');
        this.toggleMinimumStockField(minimumStockInput, true);
        
        itemRows.appendChild(newRow);
        this.updateRemoveButtons();
    },
    
    cloneItemRow: function(sourceRow) {
        const newRow = sourceRow.cloneNode(true);
        
        // Explicitly copy select field values (cloneNode doesn't preserve selected values)
        const sourceTypeSelect = sourceRow.querySelector('select[name="type"]');
        const newTypeSelect = newRow.querySelector('select[name="type"]');
        if (sourceTypeSelect && newTypeSelect) {
            newTypeSelect.value = sourceTypeSelect.value;
        }
        
        // Keep ALL values including type and expiry date - only clear quantity
        const quantityInput = newRow.querySelector('input[name="quantity"]');
        if (quantityInput) quantityInput.value = '';
        
        // Clear minimum stock field for duplicated rows since it's only for new products
        const minimumStockInput = newRow.querySelector('input[name="minimum_stock"]');
        if (minimumStockInput) minimumStockInput.value = '';
        
        // Show remove button
        const removeBtn = newRow.querySelector('.remove-row');
        if (removeBtn) {
            removeBtn.style.display = 'block';
        }
        
        // Hide suggestions for the new row
        const suggestionsDiv = newRow.querySelector('.item-suggestions');
        if (suggestionsDiv) {
            suggestionsDiv.style.display = 'none';
        }
        
        // Attach product checker and item search to cloned name input
        const nameInput = newRow.querySelector('.item-name-input');
        if (nameInput) {
            this.attachProductChecker(nameInput);
            this.attachItemSearch(nameInput);
        }
        
        sourceRow.parentNode.insertBefore(newRow, sourceRow.nextSibling);
        this.updateRemoveButtons();
        
        // Focus on quantity input for quick entry
        if (quantityInput) {
            quantityInput.focus();
        }
    },
    
    removeItemRow: function(row) {
        const itemRows = document.getElementById('itemRows');
        if (itemRows.children.length > 1) {
            row.remove();
            this.updateRemoveButtons();
        }
    },
    
    updateRemoveButtons: function() {
        const itemRows = document.getElementById('itemRows');
        const rows = itemRows.querySelectorAll('.item-row');
        
        rows.forEach((row, index) => {
            const removeBtn = row.querySelector('.remove-row');
            if (removeBtn) {
                removeBtn.style.display = rows.length > 1 ? 'block' : 'none';
            }
        });
    }
};

// Initialize everything when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Initialize search and filters
    SearchFilter.init();
    
    // Initialize keyboard shortcuts
    KeyboardShortcuts.init();
    
    // Initialize product management for add items page
    if (document.getElementById('manualForm')) {
        ProductManager.init();
    }
    
    // Start periodic notifications (commented out for now)
    // NotificationManager.startPeriodicChecks();
    
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialize popovers
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Add loading states to forms
    const forms = document.querySelectorAll('form[method="POST"]');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            const submitButton = form.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.disabled = true;
                const originalText = submitButton.innerHTML;
                submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Processing...';
                
                // Re-enable after 5 seconds as fallback
                setTimeout(() => {
                    submitButton.disabled = false;
                    submitButton.innerHTML = originalText;
                }, 5000);
            }
        });
    });
    
    // Auto-focus first input in modals
    document.addEventListener('shown.bs.modal', function(e) {
        const modal = e.target;
        const firstInput = modal.querySelector('input:not([type="hidden"]), select, textarea');
        if (firstInput) {
            firstInput.focus();
        }
    });
    
    // Add confirmation to delete buttons
    const deleteButtons = document.querySelectorAll('button[onclick*="delete"], a[onclick*="delete"]');
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            if (!button.hasAttribute('data-confirmed')) {
                e.preventDefault();
                e.stopPropagation();
                
                ModalManager.showConfirmation(
                    'Confirm Deletion',
                    'Are you sure you want to delete this item? This action cannot be undone.',
                    () => {
                        button.setAttribute('data-confirmed', 'true');
                        button.click();
                    },
                    {
                        headerClass: 'bg-danger text-white',
                        confirmClass: 'btn-danger',
                        confirmText: 'Delete'
                    }
                );
            }
        });
    });
    
    console.log('Healthcare Inventory Management System loaded successfully');
});

// Missing global functions for templates
function editMinimumStock(productId, currentStock) {
    const newStock = prompt(`Enter new minimum stock for this product (current: ${currentStock}):`);
    if (newStock !== null && !isNaN(newStock) && newStock >= 0) {
        fetch('/api/update_minimum_stock', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                product_id: productId,
                minimum_stock: parseInt(newStock)
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                Utils.showToast('Minimum stock updated successfully', 'success');
                location.reload();
            } else {
                Utils.showToast('Error updating minimum stock: ' + data.error, 'error');
            }
        })
        .catch(error => {
            Utils.showToast('Error updating minimum stock', 'error');
            console.error('Error:', error);
        });
    }
}

function showTransferModal(itemId, itemName, quantity, bagName) {
    // Find or create transfer modal
    let modal = document.getElementById('transferModal');
    if (!modal) {
        console.error('Transfer modal not found');
        return;
    }
    
    // Populate modal with item data
    const modalTitle = modal.querySelector('.modal-title');
    const itemNameField = modal.querySelector('#transfer_item_name');
    const quantityField = modal.querySelector('#transfer_quantity');
    const fromBagField = modal.querySelector('#transfer_from_bag');
    const itemIdField = modal.querySelector('#transfer_item_id');
    
    if (modalTitle) modalTitle.textContent = `Transfer ${itemName}`;
    if (itemNameField) itemNameField.value = itemName;
    if (quantityField) quantityField.max = quantity;
    if (fromBagField) fromBagField.value = bagName;
    if (itemIdField) itemIdField.value = itemId;
    
    // Show modal
    const bootstrapModal = new bootstrap.Modal(modal);
    bootstrapModal.show();
}

function showUsageModal(itemId, itemName, quantity) {
    // Find or create usage modal
    let modal = document.getElementById('usageModal');
    if (!modal) {
        console.error('Usage modal not found');
        return;
    }
    
    // Populate modal with item data
    const modalTitle = modal.querySelector('.modal-title');
    const itemNameField = modal.querySelector('#usage_item_name');
    const quantityField = modal.querySelector('#usage_quantity');
    const itemIdField = modal.querySelector('#usage_item_id');
    
    if (modalTitle) modalTitle.textContent = `Record Usage: ${itemName}`;
    if (itemNameField) itemNameField.value = itemName;
    if (quantityField) quantityField.max = quantity;
    if (itemIdField) itemIdField.value = itemId;
    
    // Show modal
    const bootstrapModal = new bootstrap.Modal(modal);
    bootstrapModal.show();
}

// Export utilities for use in other scripts
window.InventoryUtils = Utils;
window.InventoryForms = FormValidation;
window.InventoryModals = ModalManager;
window.InventoryExport = DataExport;
window.editMinimumStock = editMinimumStock;
window.showTransferModal = showTransferModal;
window.showUsageModal = showUsageModal;

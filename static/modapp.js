/**
 * ModApp JavaScript - AJAX moderation actions without page refresh
 */

// Handle individual moderation actions (approve, reject, delete, clear_flags)
async function moderationAction(action, quoteId, element) {
    try {
        // Show loading state
        const originalText = element.textContent;
        element.textContent = 'Loading...';
        element.style.pointerEvents = 'none';
        
        const response = await fetch(`/${action}/${quoteId}`, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'  // Tell server this is AJAX
            }
        });
        
        const result = await response.json();
        
        if (result.success) {
            // Show success message briefly
            showMessage(result.message, 'success');
            
            // Remove the quote from the current view or update its display
            const quoteRow = element.closest('tr');
            if (quoteRow) {
                // Fade out the quote
                quoteRow.style.transition = 'opacity 0.3s ease';
                quoteRow.style.opacity = '0';
                
                setTimeout(() => {
                    quoteRow.remove();
                    updateCounters();
                }, 300);
            }
        } else {
            // Show error message
            showMessage(result.message || 'Action failed', 'error');
            // Restore original state
            element.textContent = originalText;
            element.style.pointerEvents = 'auto';
        }
        
    } catch (error) {
        console.error('Moderation action failed:', error);
        showMessage('Network error. Please try again.', 'error');
        // Restore original state
        element.textContent = originalText;
        element.style.pointerEvents = 'auto';
    }
    
    return false; // Prevent default link behavior
}

// Show temporary message to user
function showMessage(message, type = 'info') {
    // Remove any existing messages
    const existingMsg = document.getElementById('temp-message');
    if (existingMsg) {
        existingMsg.remove();
    }
    
    // Create new message element
    const msgDiv = document.createElement('div');
    msgDiv.id = 'temp-message';
    msgDiv.textContent = message;
    msgDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 1000;
        padding: 10px 20px;
        border-radius: 5px;
        font-weight: bold;
        color: white;
        max-width: 300px;
        word-wrap: break-word;
        transition: opacity 0.3s ease;
        ${type === 'success' ? 'background-color: #28a745;' : ''}
        ${type === 'error' ? 'background-color: #dc3545;' : ''}
        ${type === 'info' ? 'background-color: #17a2b8;' : ''}
    `;
    
    document.body.appendChild(msgDiv);
    
    // Auto-remove after 3 seconds
    setTimeout(() => {
        msgDiv.style.opacity = '0';
        setTimeout(() => msgDiv.remove(), 300);
    }, 3000);
}

// Update quote counters (simplified - could be enhanced with actual counts)
function updateCounters() {
    // This could be enhanced to fetch actual counts from server
    // For now, just indicate that counts may have changed
    const statusElements = document.querySelectorAll('.quote-status');
    statusElements.forEach(el => {
        el.style.opacity = '0.8';
        setTimeout(() => el.style.opacity = '1', 100);
    });
}

// Handle bulk actions form
async function handleBulkAction(form, event) {
    event.preventDefault();
    
    const formData = new FormData(form);
    const action = formData.get('action');
    const quoteIds = formData.getAll('quote_ids');
    
    if (quoteIds.length === 0) {
        showMessage('Please select at least one quote', 'error');
        return false;
    }
    
    if (!confirm(`Are you sure you want to ${action} ${quoteIds.length} quote(s)?`)) {
        return false;
    }
    
    try {
        const response = await fetch('/modapp/bulk', {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage(result.message, 'success');
            
            // Remove processed quotes from view
            quoteIds.forEach(quoteId => {
                const checkbox = document.querySelector(`input[value="${quoteId}"]`);
                if (checkbox) {
                    const quoteRow = checkbox.closest('tr');
                    if (quoteRow) {
                        quoteRow.style.transition = 'opacity 0.3s ease';
                        quoteRow.style.opacity = '0';
                        setTimeout(() => quoteRow.remove(), 300);
                    }
                }
            });
            
            // Reset form
            form.reset();
            updateCounters();
            
        } else {
            showMessage(result.message || 'Bulk action failed', 'error');
        }
        
    } catch (error) {
        console.error('Bulk action failed:', error);
        showMessage('Network error. Please try again.', 'error');
    }
    
    return false;
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    // Convert all moderation links to AJAX
    document.querySelectorAll('a[href^="/approve/"], a[href^="/reject/"], a[href^="/delete/"], a[href^="/clear_flags/"]').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            const href = this.getAttribute('href');
            const parts = href.split('/');
            const action = parts[1]; // approve, reject, delete, clear_flags
            const quoteId = parts[2];
            
            moderationAction(action, quoteId, this);
        });
    });
    
    // Convert bulk form to AJAX
    const bulkForm = document.querySelector('form[action="/modapp/bulk"]');
    if (bulkForm) {
        bulkForm.addEventListener('submit', function(e) {
            handleBulkAction(this, e);
        });
    }
});
// AJAX voting functionality
function vote(quoteId, action, buttonElement) {
    // Prevent multiple clicks on the same button
    if (buttonElement.disabled) {
        return false;
    }
    
    // Disable button temporarily to prevent double-clicks
    buttonElement.disabled = true;
    
    // Make AJAX request
    fetch(`/vote/${quoteId}/${action}`, {
        method: 'GET',
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => {
        // Handle both successful and error responses with JSON
        return response.json().then(data => {
            return { data, status: response.status, ok: response.ok };
        });
    })
    .then(result => {
        const { data, status, ok } = result;
        
        if (ok && data.success) {
            // Update vote count display
            const voteElement = document.getElementById(`votes-${quoteId}`);
            if (voteElement) {
                voteElement.textContent = data.votes;
            }
            
            // Update button states based on user's voting history
            updateButtonStates(quoteId, data.user_vote);
        } else {
            // Show the server's error message, with special handling for rate limiting
            let errorMessage = data.message || 'Sorry, your vote could not be recorded. Please try again.';
            
            if (status === 429) {
                // Rate limiting or flood control
                errorMessage = data.message || 'Please slow down! You\'re voting too quickly. Wait a moment and try again.';
            }
            
            alert(errorMessage);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Connection error while voting. Please check your internet connection and try again.');
    })
    .finally(() => {
        // Re-enable the button immediately
        buttonElement.disabled = false;
    });
    
    return false; // Prevent default link behavior
}

function updateButtonStates(quoteId, userVote) {
    const upButton = document.getElementById(`up-${quoteId}`);
    const downButton = document.getElementById(`down-${quoteId}`);
    
    if (upButton && downButton) {
        // Reset button styles
        upButton.style.backgroundColor = '';
        downButton.style.backgroundColor = '';
        
        // Highlight the voted button
        if (userVote === 'upvote') {
            upButton.style.backgroundColor = '#90EE90'; // Light green
        } else if (userVote === 'downvote') {
            downButton.style.backgroundColor = '#FFB6C1'; // Light pink
        }
    }
}

// Flag quote functionality
function flag(quoteId, buttonElement) {
    if (buttonElement.disabled) {
        return false;
    }
    
    if (!confirm('Are you sure you want to flag this quote as inappropriate?')) {
        return false;
    }
    
    buttonElement.disabled = true;
    
    fetch(`/flag/${quoteId}`, {
        method: 'GET',
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(data.message || 'Thank you! This quote has been flagged for review by moderators.');
            buttonElement.style.backgroundColor = '#FFB6C1'; // Light pink
            buttonElement.textContent = '✓';
        } else {
            alert(data.message || 'Sorry, we could not flag this quote. Please try again.');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Connection error while flagging. Please check your internet connection and try again.');
    })
    .finally(() => {
        buttonElement.disabled = false;
    });
    
    return false;
}

// Copy quote functionality
function copyQuote(quoteId, buttonElement) {
    if (buttonElement.disabled) {
        return false;
    }
    
    // Get the quote text
    const quoteElement = document.querySelector(`#quote-${quoteId} .qt, [data-quote-id="${quoteId}"] .qt`);
    let quoteText = '';
    
    if (quoteElement) {
        quoteText = quoteElement.textContent || quoteElement.innerText;
    } else {
        // Fallback: look for quote text in any element after the quote header
        const allQuotes = document.querySelectorAll('.qt');
        const quoteHeaders = document.querySelectorAll('.quote');
        
        for (let i = 0; i < quoteHeaders.length; i++) {
            const header = quoteHeaders[i];
            if (header.innerHTML.includes(`#${quoteId}`)) {
                if (allQuotes[i]) {
                    quoteText = allQuotes[i].textContent || allQuotes[i].innerText;
                }
                break;
            }
        }
    }
    
    if (!quoteText) {
        alert('Sorry, we could not find the quote text to copy. Please try selecting and copying the text manually.');
        return false;
    }
    
    // Format the text with quote number
    const formattedText = `#${quoteId}: ${quoteText.trim()}`;
    
    // Copy to clipboard
    if (navigator.clipboard && window.isSecureContext) {
        // Modern approach
        navigator.clipboard.writeText(formattedText).then(() => {
            showCopySuccess(buttonElement);
        }).catch(() => {
            fallbackCopy(formattedText, buttonElement);
        });
    } else {
        // Fallback for older browsers
        fallbackCopy(formattedText, buttonElement);
    }
    
    return false;
}

function fallbackCopy(text, buttonElement) {
    // Create temporary textarea
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        document.execCommand('copy');
        showCopySuccess(buttonElement);
    } catch (err) {
        console.error('Could not copy text: ', err);
        alert('Copy to clipboard failed. Please manually select and copy the quote text using Ctrl+C (or Cmd+C on Mac).');
    }
    
    document.body.removeChild(textArea);
}

function showCopySuccess(buttonElement) {
    const originalText = buttonElement.textContent;
    buttonElement.textContent = '✓';
    buttonElement.style.backgroundColor = '#90EE90'; // Light green
    
    setTimeout(() => {
        buttonElement.textContent = originalText;
        buttonElement.style.backgroundColor = '';
    }, 1500);
}

// Load user vote states when page loads
document.addEventListener('DOMContentLoaded', function() {
    // Get all vote elements and check their states
    const voteElements = document.querySelectorAll('[id^="votes-"]');
    
    // Get user's voting history from cookies
    const votes = getCookie('votes');
    if (votes) {
        try {
            const voteData = JSON.parse(votes);
            
            // Update button states for each quote
            voteElements.forEach(element => {
                const quoteId = element.id.replace('votes-', '');
                const userVote = voteData[quoteId];
                if (userVote) {
                    updateButtonStates(quoteId, userVote);
                }
            });
        } catch (e) {
            console.log('Could not parse vote cookie');
        }
    }
});

// Helper function to get cookie value
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}
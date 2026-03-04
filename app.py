from flask import Flask, render_template, request, redirect, url_for, flash, abort, make_response, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
import datetime
import json
import random
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import logging
import time
import ipaddress
from collections import defaultdict
from config_loader import config  # Import configuration system

# ── In-memory login rate limiter ──────────────────────────────────────────────
_login_attempts: dict[str, list[float]] = defaultdict(list)
LOGIN_MAX_ATTEMPTS = 5        # max tries per window
LOGIN_WINDOW_SECONDS = 300    # 5-minute window

def db_retry_operation(operation, max_retries=2, delay=0.01):
    """
    Retry database operations that might fail due to database locks.
    Includes session cleanup for better reliability.
    
    Args:
        operation: Operation to retry
        max_retries: Max attempts
        delay: Delay between retries
    
    Returns:
        The result of the operation if successful
    
    Raises:
        The last exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except Exception as e:
            last_exception = e
            error_msg = str(e).lower()
            
            # Retry on transient database errors (deadlocks, serialization failures, etc.)
            if ('deadlock' in error_msg or
                'serialization failure' in error_msg or
                'transaction has been rolled back' in error_msg):
                
                try:
                    # Only rollback, don't close session to avoid unbound objects
                    db.session.rollback()
                except:
                    pass  # Ignore cleanup errors
                
                if attempt < max_retries:
                    logging.warning(f"Database error detected, rollback and retry (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(delay)
                    continue
            
            # For non-database errors or final attempt, re-raise immediately
            raise
    
    # This should never be reached due to the logic above, but just in case
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError("Database operation failed for unknown reasons")

def validate_ip_address(ip_str):
    """
    Validate that an IP address string is a valid IPv4 or IPv6 address.
    Returns a sanitized IP address string or '127.0.0.1' if invalid.
    """
    try:
        # This will raise ValueError if the IP is invalid
        ip_obj = ipaddress.ip_address(ip_str)
        return str(ip_obj)
    except (ValueError, TypeError):
        # If IP is invalid, return localhost as fallback
        app.logger.warning(f"Invalid IP address detected: {ip_str}")
        return '127.0.0.1'

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = config.database_uri

import os
import secrets

# Securely load the secret key with absolute path resolution
base_dir = os.path.abspath(os.path.dirname(__file__))
# Note: config.json logic or config_loader might be initializing the app earlier or conflicting!
# Let's ensure SECRET_KEY is set on the app object directly and immediately.

secret_key_path = os.path.join(base_dir, "instance", "flask_secret_key")

try:
    with open(secret_key_path, "r") as f:
        file_secret = f.read().strip()
        if file_secret:
            app.config['SECRET_KEY'] = file_secret
        else:
            print("Warning: Secret key file is empty. Generating temporary key.")
            app.config['SECRET_KEY'] = secrets.token_hex(32)
except FileNotFoundError:
    print(f"Warning: Secret key file not found at {secret_key_path}. Generating temporary one.")
    app.config['SECRET_KEY'] = secrets.token_hex(32)

app.secret_key = app.config['SECRET_KEY'] # Explicitly set attribute for older Flask extensions
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Apply ProxyFix middleware to handle behind-proxy requests properly
# This ensures that request.remote_addr is correct even when behind Nginx
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configure secure session settings from config
app.config['SESSION_COOKIE_SECURE'] = config.get('security.session_cookie_secure', False)
app.config['SESSION_COOKIE_HTTPONLY'] = config.get('security.session_cookie_httponly', True)
app.config['SESSION_COOKIE_SAMESITE'] = config.get('security.session_cookie_samesite', 'Lax')

# Configure CSRF protection from config
app.config['WTF_CSRF_ENABLED'] = config.csrf_enabled
app.config['WTF_CSRF_TIME_LIMIT'] = config.get('security.csrf_time_limit')
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_timeout': config.get('database.pool_timeout', 20),
    'pool_recycle': config.get('database.pool_recycle', 300),
    'pool_pre_ping': config.get('database.pool_pre_ping', True)
}

# Limit admin session lifetime (default 2 hours)
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(
    seconds=config.get('security.session_lifetime_seconds', 7200)
)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Exempt API endpoints from CSRF protection
csrf.exempt('get_all_quotes')
csrf.exempt('get_quote')
csrf.exempt('get_random_quote')
csrf.exempt('get_top_quotes')
csrf.exempt('search_quotes')
csrf.exempt('get_stats')

# Remove rate limiting - immediate response for all requests

db = SQLAlchemy(app)

# Initialize Argon2 password hasher
ph = PasswordHasher()

# Configure logging from config
logging.basicConfig(
    level=getattr(logging, config.logging_level),
    format=config.get('logging.format', '%(asctime)s [%(levelname)s] %(message)s')
)

# Add security headers from config
@app.after_request
def add_security_headers(response):
    headers = config.get('security.security_headers', {})
    if headers.get('x_content_type_options'):
        response.headers['X-Content-Type-Options'] = headers['x_content_type_options']
    if headers.get('x_frame_options'):
        response.headers['X-Frame-Options'] = headers['x_frame_options']
    if headers.get('x_xss_protection'):
        response.headers['X-XSS-Protection'] = headers['x_xss_protection']
    if headers.get('strict_transport_security'):
        response.headers['Strict-Transport-Security'] = headers['strict_transport_security']
    if headers.get('content_security_policy'):
        response.headers['Content-Security-Policy'] = headers['content_security_policy']
    return response

# Admin credentials from config
# Define the Quote model
class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    votes = db.Column(db.Integer, default=0)
    date = db.Column(db.DateTime, nullable=True)  # Legacy field for old quotes
    status = db.Column(db.Integer, default=0, index=True)  # 0 = pending, 1 = approved, 2 = rejected
    ip_address = db.Column(db.String(45))  # Store IPv4 and IPv6 addresses
    user_agent = db.Column(db.String(255))  # Store user-agent strings
    submitted_at = db.Column(db.DateTime, nullable=True)  # New timestamp field for new quotes
    flag_count = db.Column(db.Integer, default=0, index=True)  # Track how many times quote has been flagged

    # Add composite indexes for common queries
    __table_args__ = (
        db.Index('idx_status_id', 'status', 'id'),
        db.Index('idx_flag_count_id', 'flag_count', 'id'),
    )

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), nullable=False)
    ip_address = db.Column(db.String(45))
    vote_type = db.Column(db.String(10)) # 'upvote', 'downvote', or 'flag'
    timestamp = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    
    __table_args__ = (
        db.Index('idx_vote_quote_ip', 'quote_id', 'ip_address'),
    )

def serialize_quote(quote):
    """Standardizes JSON serialization for quotes across all API endpoints."""
    # Use submitted_at for new quotes, fall back to date for legacy quotes
    timestamp = quote.submitted_at if quote.submitted_at else quote.date
    
    return {
        'id': quote.id,
        'text': quote.text,
        'votes': quote.votes,
        'submitted_at': timestamp.isoformat() if timestamp else None,
        'timestamp': int(timestamp.timestamp()) if timestamp else None,
        'datetime_display': timestamp.strftime('%d/%m/%y %H:%M:%S') if timestamp else None
    }

@app.context_processor
def inject_counts():
    """Injects quote counts into all templates automatically."""
    try:
        def get_counts():
            # status: 0=pending, 1=approved, 2=rejected
            approved = db.session.query(Quote).filter_by(status=1).count()
            pending = db.session.query(Quote).filter_by(status=0).count()
            rejected = db.session.query(Quote).filter_by(status=2).count()
            flagged = db.session.query(Quote).filter(Quote.flag_count > 0).count()
            return {
                'approved_count': approved,
                'pending_count': pending,
                'rejected_count': rejected,
                'flagged_count': flagged
            }
        
        # Use retry wrapper for database counts
        return db_retry_operation(get_counts)
    except Exception as e:
        logging.error(f"Error in context processor: {str(e)}")
        # Provide fallbacks if DB is locked/failed
        return {
            'approved_count': 0,
            'pending_count': 0,
            'rejected_count': 0,
            'flagged_count': 0
        }

# Home route to display quotes
@app.route('/')
def index():
    # quotes query removed as it's not used in index.html (welcome page)
    # If quotes should be displayed on home, update index.html to include loop from browse.html
    
    # Get the count of approved and pending quotes
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()
    
    return render_template('index.html', approved_count=approved_count, pending_count=pending_count)

# Separate route for submitting quotes
@app.route('/submit', methods=['GET', 'POST'])
def submit():
    if request.method == 'POST':
        quote_text = request.form.get('quote')
        is_preview = 'submit2' in request.form  # Preview button is named submit2
        
        if not quote_text:
            flash("Quote text is required.", 'error')
            return redirect(url_for('submit'))
        
        # Input validation and length limits from config
        quote_text = quote_text.strip()
        min_length = config.get('quotes.min_length', 10)
        max_length = config.get('quotes.max_length', 5000)
        
        if len(quote_text) < min_length:
            flash(f"Your quote is too short. Please enter at least {min_length} characters.", 'error')
            return redirect(url_for('submit'))
        
        if len(quote_text) > max_length:
            flash(f"Your quote is too long. Please keep it under {max_length} characters.", 'error')
            return redirect(url_for('submit'))
        
        # Basic content validation (no scripts or dangerous content)
        if not config.get('quotes.allow_html', False):
            if '<script' in quote_text.lower() or 'javascript:' in quote_text.lower():
                flash("Invalid content detected. Please remove any script tags or JavaScript.", 'error')
                return redirect(url_for('submit'))
        
        # If this is a preview request, show the preview
        if is_preview:
            approved_count = Quote.query.filter_by(status=1).count()
            pending_count = Quote.query.filter_by(status=0).count()
            return render_template('submit.html', 
                                 approved_count=approved_count, 
                                 pending_count=pending_count,
                                 preview_text=quote_text,
                                 original_text=quote_text)

        ip_address = validate_ip_address(request.remote_addr)  # Get user's IP address
        
        # Rate Limiting: Check for submissions in the last 60 seconds
        limit_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=60)
        if Quote.query.filter(Quote.ip_address == ip_address, Quote.submitted_at > limit_time).first():
            flash("You are submitting too fast. Please wait a minute before trying again.", 'error')
            return redirect(url_for('submit'))

        user_agent = (request.headers.get('User-Agent') or '')[:255]  # Truncate to column width

        # Determine initial status based on config
        auto_approve = config.get('quotes.auto_approve', False)
        initial_status = 1 if auto_approve else 0  # 1 = approved, 0 = pending

        def commit_quote():
            quote = Quote(
                text=quote_text, 
                ip_address=ip_address, 
                user_agent=user_agent,
                status=initial_status,
                submitted_at=datetime.datetime.now(datetime.timezone.utc)  # Set submission timestamp for new quotes
            )
            db.session.add(quote)
            db.session.commit()
            return quote

        try:
            new_quote = db_retry_operation(commit_quote)
            
            # Log the quote creation for debugging
            logging.debug(f"Quote created: ID={new_quote.id}, Status={new_quote.status}, Text='{quote_text[:50]}...'")
            
            if auto_approve:
                flash("Quote submitted and approved.", 'success')
            else:
                flash("Quote submitted and awaiting moderation.", 'success')
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error submitting quote: {e}")  # Always log errors
            flash("Sorry, something went wrong while submitting your quote. Please try again in a moment.", 'error')

        return redirect(url_for('index'))

    # Get the count of approved and pending quotes
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()

    return render_template('submit.html', approved_count=approved_count, pending_count=pending_count)

@app.route('/vote/<int:id>/<action>', methods=['POST'])
def vote(id, action):
    # Validate action parameter upfront
    if action not in ('upvote', 'downvote'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Invalid vote action.'}), 400
        flash('Invalid vote action.', 'error')
        return redirect(url_for('browse'))

    # Only allow voting on approved quotes (status = 1)
    quote = Quote.query.filter_by(id=id, status=1).first()
    if not quote:
        error_msg = "Quote not found or not available for voting."
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': error_msg
            }), 404
        else:
            flash(error_msg, 'error')
            return redirect(url_for('browse'))

    # Retrieve vote history from database using IP
    client_ip = validate_ip_address(request.remote_addr)
    existing_vote = Vote.query.filter_by(quote_id=id, ip_address=client_ip).first()

    message = ""
    
    def update_vote():
        nonlocal message
        
        # If no prior vote, apply the new vote
        if not existing_vote:
            if action == 'upvote':
                quote.votes += 1
                new_vote = Vote(quote_id=id, ip_address=client_ip, vote_type='upvote')
                db.session.add(new_vote)
            elif action == 'downvote':
                quote.votes -= 1
                new_vote = Vote(quote_id=id, ip_address=client_ip, vote_type='downvote')
                db.session.add(new_vote)
            message = "Vote recorded."

        else:
            previous_action = existing_vote.vote_type

            if previous_action == action:
                # If the user clicks the same action again, undo the vote
                if action == 'upvote':
                    quote.votes -= 1
                elif action == 'downvote':
                    quote.votes += 1
                db.session.delete(existing_vote)  # Remove the vote record (undo)
                message = "Your vote has been undone."
            else:
                # If the user switches votes (upvote -> downvote or vice versa)
                if previous_action == 'upvote' and action == 'downvote':
                    quote.votes -= 2  # Undo upvote (+1) and apply downvote (-1)
                    existing_vote.vote_type = 'downvote'
                elif previous_action == 'downvote' and action == 'upvote':
                    quote.votes += 2  # Undo downvote (-1) and apply upvote (+1)
                    existing_vote.vote_type = 'upvote'
                message = "Your vote has been changed."
        
        db.session.commit()

    # Save the updated vote data with retry for database locks
    try:
        # Simple retry mechanism for database locks
        db_retry_operation(update_vote)
        
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Return JSON response for AJAX
            current_vote_type = None
            # Re-query to get current state after operation
            updated_vote = Vote.query.filter_by(quote_id=id, ip_address=client_ip).first()
            if updated_vote:
                current_vote_type = updated_vote.vote_type
                
            resp = make_response(jsonify({
                'success': True,
                'votes': quote.votes,
                'user_vote': current_vote_type,
                'message': message
            }))
            return resp
        else:
            # Traditional redirect for non-AJAX requests
            flash(message, 'success')
            page = request.args.get('page', 1)
            return redirect(url_for('browse', page=page))
    except Exception as e:
        db.session.rollback()
        logging.error(f"Vote error for quote {id}, action {action}: {str(e)}")
        user_error_msg = "Sorry, there was an error processing your vote. Please try again."
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': user_error_msg
            }), 500
        else:
            flash(user_error_msg, 'error')
            page = request.args.get('page', 1)
            return redirect(url_for('browse', page=page))

@app.route('/random')
def random_quote():
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()

    if approved_count == 0:
        flash("No approved quotes found.", 'error')
        return redirect(url_for('index'))

    # Use offset to get a random quote from approved quotes
    random_offset = random.randint(0, approved_count - 1)
    random_quote = Quote.query.filter_by(status=1).offset(random_offset).first()

    return render_template('random.html', quote=random_quote, approved_count=approved_count, pending_count=pending_count)


@app.route('/<int:id>')
def quote_homepathid(id):
    # Only show approved quotes (status = 1)
    quote = Quote.query.filter_by(id=id, status=1).first()
    if not quote:
        abort(404)
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()
    return render_template('quote.html', quote=quote, approved_count=approved_count, pending_count=pending_count)

@app.route('/quote')
def quote():
    quote_id = request.args.get('id', type=int)  # Convert to int directly
    if not quote_id:
        flash("Please enter a valid quote number to view that specific quote.", 'error')
        return redirect(url_for('browse'))
    
    # Only show approved quotes (status = 1)
    quote = Quote.query.filter_by(id=quote_id, status=1).first()
    if not quote:
        flash(f"No approved quote found with ID {quote_id}", 'error')
        return redirect(url_for('search'))
    
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()
    return render_template('quote.html', quote=quote, approved_count=approved_count, pending_count=pending_count)

@app.route('/faq')
def faq():
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()
    return render_template('faq.html', approved_count=approved_count, pending_count=pending_count)

# Flag/Report a quote route
@app.route('/flag/<int:id>', methods=['POST'])
def flag_quote(id):
    # Only allow flagging of approved quotes (status = 1)
    quote = Quote.query.filter_by(id=id, status=1).first()
    if not quote:
        message = 'Quote not found or not available for flagging.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': message
            }), 404
        else:
            flash(message, 'error')
            return redirect(url_for('browse'))

    # Deduplicate flags by IP — one flag per IP per quote
    client_ip = validate_ip_address(request.remote_addr)
    existing_flag = Vote.query.filter_by(quote_id=id, ip_address=client_ip, vote_type='flag').first()
    if existing_flag:
        message = 'You have already flagged this quote.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': message}), 409
        else:
            flash(message, 'info')
            return redirect(url_for('browse'))

    # Record the flag and increment count
    flag_record = Vote(quote_id=id, ip_address=client_ip, vote_type='flag')
    db.session.add(flag_record)
    quote.flag_count += 1
    
    def commit_flag_changes():
        """Helper function to commit flag changes with proper error handling"""
        db.session.commit()
        return True
    
    try:
        # Use retry mechanism for database commit
        db_retry_operation(commit_flag_changes)
        message = 'Quote flagged for review.'
        
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'message': message,
                'flag_count': quote.flag_count
            })
        else:
            flash(message, 'success')
    except Exception as e:
        db.session.rollback()
        # Log detailed error but only show generic message to user
        logging.error(f"Flag error for quote {id}: {str(e)}")
        user_error_msg = 'Sorry, there was an error flagging this quote. Please try again.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': user_error_msg
            }), 500
        else:
            flash(user_error_msg, 'error')
    
    # For non-AJAX requests, redirect back to the same page (validate referer to prevent open redirect)
    referer = request.headers.get('Referer', '')
    if referer and referer.startswith(request.host_url) and any(
        path in referer for path in ['/browse', '/quote', '/random', '/search']
    ):
        return redirect(referer)
    else:
        return redirect(url_for('browse'))

# Admin login route
def _is_login_rate_limited(ip: str) -> bool:
    """Return True if this IP has exceeded the login attempt threshold."""
    now = time.time()
    window = [t for t in _login_attempts[ip] if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[ip] = window
    return len(window) >= LOGIN_MAX_ATTEMPTS


def _record_login_attempt(ip: str) -> None:
    _login_attempts[ip].append(time.time())


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        client_ip = validate_ip_address(request.remote_addr)

        # Rate-limit login attempts per IP
        if _is_login_rate_limited(client_ip):
            flash('Too many login attempts. Please wait a few minutes and try again.', 'danger')
            approved_count = Quote.query.filter_by(status=1).count()
            pending_count = Quote.query.filter_by(status=0).count()
            return render_template('login.html', approved_count=approved_count, pending_count=pending_count), 429

        try:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            if not username or not password:
                flash('Please enter both username and password.', 'danger')
                approved_count = Quote.query.filter_by(status=1).count()
                pending_count = Quote.query.filter_by(status=0).count()
                return render_template('login.html', approved_count=approved_count, pending_count=pending_count)
            
            # Check if the username is correct and verify the password using Argon2
            # Supports multiple admins defined in config.json
            admin_user = next((admin for admin in config.admins if admin['username'] == username), None)

            # Use a generic failure message to prevent user enumeration
            login_fail_msg = 'Invalid username or password. Please try again.'

            if admin_user:
                try:
                    ph.verify(admin_user['password_hash'], password)  # Verify password using Argon2
                    
                    # Regenerate session ID to prevent session fixation attacks
                    # Clear the old session and create a new one
                    session.clear()
                    session.permanent = True
                    session['admin'] = True
                    session['admin_username'] = username
                    
                    # Clear rate-limit history on successful login
                    _login_attempts.pop(client_ip, None)

                    flash(f'Welcome back, {username}! You are now logged in as administrator.', 'success')
                    return redirect(url_for('modapp'))
                except VerifyMismatchError:
                    _record_login_attempt(client_ip)
                    flash(login_fail_msg, 'danger')
                except Exception as e:
                    logging.error(f"Password verification error: {e}")
                    flash('An error occurred during login. Please try again.', 'danger')
            else:
                _record_login_attempt(client_ip)
                flash(login_fail_msg, 'danger')
                
        except Exception as e:
            logging.error(f"Login error: {e}")
            flash('An error occurred during login. Please try again.', 'danger')
    
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()
    return render_template('login.html', approved_count=approved_count, pending_count=pending_count)

# Admin panel route (accessible only to logged-in admins)
@app.route('/modapp')
def modapp():
    if not session.get('admin'):
        flash('Access denied. Please log in with administrator credentials to access the moderation panel.', 'danger')
        return redirect(url_for('login'))

    # Apply filtering (pending, approved, rejected, flagged)
    filter_status = request.args.get('filter', 'pending')
    page = request.args.get('page', 1, type=int)

    # Get quotes based on filter with optimized queries
    if filter_status == 'approved':
        quotes = Quote.query.filter_by(status=1).order_by(Quote.id.desc()).paginate(page=page, per_page=10, error_out=False)
    elif filter_status == 'rejected':
        quotes = Quote.query.filter_by(status=2).order_by(Quote.id.desc()).paginate(page=page, per_page=10, error_out=False)
    elif filter_status == 'flagged':
        # Show quotes with flag_count > 0, ordered by flag count (highest first)
        quotes = Quote.query.filter(Quote.flag_count > 0).order_by(Quote.flag_count.desc(), Quote.id.desc()).paginate(page=page, per_page=10, error_out=False)
    else:  # Default to pending
        quotes = Quote.query.filter_by(status=0).order_by(Quote.id.desc()).paginate(page=page, per_page=10, error_out=False)

    # Get counts for each status in a single query to avoid multiple hits
    from sqlalchemy import func, case
    count_results = db.session.query(
        func.count(case((Quote.status == 1, 1))).label('approved_count'),
        func.count(case((Quote.status == 0, 1))).label('pending_count'),
        func.count(case((Quote.status == 2, 1))).label('rejected_count'),
        func.count(case((Quote.flag_count > 0, 1))).label('flagged_count')
    ).first()
    
    approved_count = count_results.approved_count
    pending_count = count_results.pending_count
    rejected_count = count_results.rejected_count
    flagged_count = count_results.flagged_count

    return render_template('modapp.html', quotes=quotes, filter_status=filter_status,
                           approved_count=approved_count, pending_count=pending_count,
                           rejected_count=rejected_count, flagged_count=flagged_count)


# Bulk actions route for modapp
@app.route('/modapp/bulk', methods=['POST'])
def modapp_bulk():
    if not session.get('admin'):
        flash('Access denied. Administrator login required for bulk actions.', 'danger')
        return redirect(url_for('login'))
    
    action = request.form.get('action')
    quote_ids = request.form.getlist('quote_ids')
    
    if not quote_ids:
        flash('Please select at least one quote before performing a bulk action.', 'error')
        return redirect(url_for('modapp'))
    
    if not action or action not in ['approve', 'reject', 'delete', 'clear_flags']:
        flash('The requested action is not supported. Please try again or contact support.', 'error')
        return redirect(url_for('modapp'))
    
    success_count = 0
    error_count = 0
    
    # Validate all quote IDs first
    valid_quote_ids = []
    for quote_id_str in quote_ids:
        try:
            quote_id = int(quote_id_str)
            quote = db.session.get(Quote, quote_id)
            if quote:
                valid_quote_ids.append(quote_id)
            else:
                error_count += 1
                logging.warning(f"Quote ID {quote_id} not found during bulk {action}")
        except (ValueError, TypeError):
            error_count += 1
            logging.warning(f"Invalid quote ID '{quote_id_str}' during bulk {action}")
    
    if not valid_quote_ids:
        flash('No valid quotes selected. Please try again.', 'error')
        return redirect(url_for('modapp'))
    
    # Perform bulk operation with transaction safety
    def bulk_operation():
        nonlocal success_count
        
        try:
            for quote_id in valid_quote_ids:
                try:
                    # Use fresh query to avoid stale session issues
                    quote = db.session.query(Quote).filter(Quote.id == quote_id).first()
                    if quote:
                        if action == 'approve':
                            if quote.status != 1:  # Only approve if not already approved
                                quote.status = 1
                                success_count += 1
                        elif action == 'reject':
                            if quote.status != 2:  # Only reject if not already rejected
                                quote.status = 2
                                success_count += 1
                        elif action == 'delete':
                            db.session.delete(quote)
                            success_count += 1
                        elif action == 'clear_flags':
                            if quote.flag_count > 0:  # Only clear if there are flags
                                quote.flag_count = 0
                                success_count += 1
                except Exception as e:
                    logging.error(f"Error processing quote {quote_id} during bulk {action}: {str(e)}")
                    raise  # Re-raise to trigger rollback
            
            # Commit all changes at once
            db.session.commit()
            return True
            
        except Exception as e:
            db.session.rollback()
            raise e
    
    try:
        db_retry_operation(bulk_operation)
        
        # Generate success message
        if success_count > 0:
            if action == 'clear_flags':
                message = f'Successfully cleared flags on {success_count} quote(s).'
            else:
                action_past_tense = {
                    'approve': 'approved',
                    'reject': 'rejected', 
                    'delete': 'deleted'
                }.get(action, f'{action}d')
                message = f'Successfully {action_past_tense} {success_count} quote(s).'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': message})
            else:
                flash(message, 'success')
        else:
            message = 'No changes were made. The selected quotes may already be in the requested state.'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message})
            else:
                flash(message, 'info')
        
        if error_count > 0:
            warning_message = f'{error_count} quote(s) had invalid IDs and were skipped.'
            if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                flash(warning_message, 'warning')
            
    except Exception as e:
        db.session.rollback()
        logging.error(f'Bulk {action} operation failed: {str(e)}')
        error_message = f'Error performing bulk {action}. Please check the logs for details.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error_message})
        else:
            flash(error_message, 'error')
    
    # For non-AJAX requests, redirect back to modapp
    return redirect(url_for('modapp'))


# Helper function to approve a quote
def approve_quote(quote_id):
    """Helper function to approve a quote with proper session management"""
    try:
        # Use a fresh query in case of stale session
        quote = db.session.query(Quote).filter(Quote.id == quote_id).first()
        if quote and quote.status != 1:  # Only approve if not already approved
            quote.status = 1  # Approved
            
            def commit_operation():
                try:
                    db.session.commit()
                    return True
                except Exception as e:
                    db.session.rollback()
                    raise e
                
            return db_retry_operation(commit_operation)
        return False
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in approve_quote({quote_id}): {str(e)}")
        raise

# Helper function to reject a quote
def reject_quote(quote_id):
    """Helper function to reject a quote with proper session management"""
    try:
        # Use a fresh query in case of stale session
        quote = db.session.query(Quote).filter(Quote.id == quote_id).first()
        if quote and quote.status != 2:  # Only reject if not already rejected
            quote.status = 2  # Rejected
            
            def commit_operation():
                try:
                    db.session.commit()
                    return True
                except Exception as e:
                    db.session.rollback()
                    raise e
                
            return db_retry_operation(commit_operation)
        return False
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in reject_quote({quote_id}): {str(e)}")
        raise

# Helper function to delete a quote
def delete_quote(quote_id):
    """Helper function to delete a quote with proper error handling"""
    try:
        quote = db.session.get(Quote, quote_id)
        if quote:
            def commit_operation():
                db.session.delete(quote)
                db.session.commit()
                return True
                
            return db_retry_operation(commit_operation)
        return False
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in delete_quote({quote_id}): {str(e)}")
        raise

# Helper function to clear flags from a quote
def clear_flags_quote(quote_id):
    """Helper function to clear flags from a quote with proper error handling"""
    try:
        quote = db.session.get(Quote, quote_id)
        if quote and quote.flag_count > 0:
            original_flag_count = quote.flag_count
            quote.flag_count = 0
            
            def commit_operation():
                db.session.commit()
                return True
                
            db_retry_operation(commit_operation)
            return original_flag_count  # Return number of flags cleared
        return 0  # No flags to clear
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in clear_flags_quote({quote_id}): {str(e)}")
        raise

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '').strip()  # Get the search query
    quotes = []

    # Query counts of approved and pending quotes
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()

    if query:
        quotes = Quote.query.filter(Quote.text.contains(query), Quote.status == 1).limit(50).all()
        if len(quotes) == 50:
            flash("Search restricted to top 50 matches. Please verify your query for more specific results.", 'info')

    return render_template('search.html', quotes=quotes, query=query, approved_count=approved_count, pending_count=pending_count)

@app.route('/read', methods=['GET'])
def read_quote():
    quote_id = request.args.get('id', type=int)  # Get the quote number
    
    if not quote_id:
        flash("Please enter a valid quote number to search for that specific quote.", 'error')
        return redirect(url_for('search'))

    # Find the quote by ID (only approved quotes)
    quote = Quote.query.filter_by(id=quote_id, status=1).first()

    if quote:
        approved_count = Quote.query.filter_by(status=1).count()
        pending_count = Quote.query.filter_by(status=0).count()
        return render_template('quote.html', quote=quote, approved_count=approved_count, pending_count=pending_count)
    else:
        flash(f"No quote found with ID {quote_id}", 'error')
        return redirect(url_for('search'))

# Route for browsing approved quotes
@app.route('/browse', methods=['GET'])
def browse():
    # Query the counts of approved and pending quotes
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()

    # Pagination setup with config
    page = request.args.get('page', 1, type=int)
    per_page = config.quotes_per_page
    # Use coalesce so quotes with only submitted_at (no legacy date) sort correctly
    from sqlalchemy import func as sqlfunc
    sort_col = sqlfunc.coalesce(Quote.submitted_at, Quote.date)
    quotes = Quote.query.filter_by(status=1).order_by(sort_col.desc()).paginate(page=page, per_page=per_page)

    # Pass the counts and the quotes to the template
    return render_template('browse.html', quotes=quotes, approved_count=approved_count, pending_count=pending_count)


@app.route('/top')
def top_quotes():
    """Display the top quotes sorted by votes"""
    # Query the counts of approved and pending quotes
    approved_count = Quote.query.filter_by(status=1).count()
    pending_count = Quote.query.filter_by(status=0).count()

    # Get top 100 quotes or paginate
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    per_page = min(per_page, 100)  # Cap at 100 per page
    
    # Get approved quotes sorted by votes (descending), then by date (coalescing both date fields)
    from sqlalchemy import func as sqlfunc2
    sort_col2 = sqlfunc2.coalesce(Quote.submitted_at, Quote.date)
    quotes = Quote.query.filter_by(status=1).order_by(Quote.votes.desc(), sort_col2.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Use the browse template but with top quotes
    return render_template('browse.html', quotes=quotes, approved_count=approved_count, 
                         pending_count=pending_count, is_top=True)


# Approve a quote (admin only)
@app.route('/approve/<int:id>', methods=['POST'])
def approve(id):
    if not session.get('admin'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Access denied. Administrator login required.'})
        flash('Access denied. Administrator login required.', 'danger')
        return redirect(url_for('login'))

    try:
        success = approve_quote(id)
        if success:
            message = f'Quote #{id} has been approved.'
            logging.info(f"Admin approved quote {id}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': message})
            else:
                flash(message, 'success')
        else:
            message = f'Quote #{id} could not be approved (may not exist or already approved).'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message})
            else:
                flash(message, 'warning')
            
    except Exception as e:
        logging.error(f"Error approving quote {id}: {str(e)}")
        message = 'Error approving quote. Please try again or check the logs.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': message})
        else:
            flash(message, 'error')

    # For non-AJAX requests, redirect back to modapp
    filter_status = request.args.get('filter', 'pending')
    return redirect(url_for('modapp', filter=filter_status))

# Reject a quote (admin only)
@app.route('/reject/<int:id>', methods=['POST'])
def reject(id):
    if not session.get('admin'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Access denied. Administrator login required.'})
        flash('Access denied. Administrator login required.', 'danger')
        return redirect(url_for('login'))

    try:
        success = reject_quote(id)
        if success:
            message = f'Quote #{id} has been rejected.'
            logging.info(f"Admin rejected quote {id}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': message})
            else:
                flash(message, 'success')
        else:
            message = f'Quote #{id} could not be rejected (may not exist or already rejected).'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message})
            else:
                flash(message, 'warning')
            
    except Exception as e:
        logging.error(f"Error rejecting quote {id}: {str(e)}")
        message = 'Error rejecting quote. Please try again or check the logs.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': message})
        else:
            flash(message, 'error')

    # For non-AJAX requests, redirect back to modapp
    filter_status = request.args.get('filter', 'pending')
    return redirect(url_for('modapp', filter=filter_status))


# Delete a quote (admin only)
@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    if not session.get('admin'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Access denied. Administrator login required.'})
        flash('Access denied. Administrator login required.', 'danger')
        return redirect(url_for('login'))

    try:
        # Get quote text for preview before deletion
        quote = db.session.get(Quote, id)
        if quote:
            quote_text_preview = quote.text[:50] + "..." if len(quote.text) > 50 else quote.text
        else:
            quote_text_preview = "unknown quote"
        
        success = delete_quote(id)
        if success:
            message = f'Quote #{id} ("{quote_text_preview}") has been permanently deleted.'
            logging.info(f"Admin deleted quote {id}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': message})
            else:
                flash(message, 'success')
        else:
            message = f'Quote #{id} could not be deleted (may not exist).'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message})
            else:
                flash(message, 'warning')
        
    except Exception as e:
        logging.error(f"Error deleting quote {id}: {str(e)}")
        message = 'Error deleting quote. Please try again or check the logs.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': message})
        else:
            flash(message, 'error')
    
    # For non-AJAX requests, redirect back to modapp
    filter_status = request.args.get('filter', 'pending')
    return redirect(url_for('modapp', filter=filter_status))

# Clear flags from a quote (admin only)
@app.route('/clear_flags/<int:id>', methods=['POST'])
def clear_flags(id):
    if not session.get('admin'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Access denied. Administrator login required.'})
        flash('Access denied. Administrator login required.', 'danger')
        return redirect(url_for('login'))

    try:
        # Get quote status for feedback message
        quote = db.session.get(Quote, id)
        if not quote:
            message = f'Quote #{id} not found.'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message})
            else:
                flash(message, 'error')
        else:
            flags_cleared = clear_flags_quote(id)
            if flags_cleared > 0:
                status_names = {0: "pending", 1: "approved", 2: "rejected"}
                message = f'Cleared {flags_cleared} flag(s) from quote #{id}. Quote remains {status_names.get(quote.status, "unknown")}.'
                logging.info(f"Admin cleared {flags_cleared} flags from quote {id}")
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': message})
                else:
                    flash(message, 'success')
            else:
                message = f'Quote #{id} has no flags to clear.'
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': message})
                else:
                    flash(message, 'info')
            
    except Exception as e:
        logging.error(f"Error clearing flags for quote {id}: {str(e)}")
        message = 'Error clearing flags. Please try again or check the logs.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': message})
        else:
            flash(message, 'error')
    
    # For non-AJAX requests, redirect back to modapp
    filter_status = request.args.get('filter', 'flagged')
    return redirect(url_for('modapp', filter=filter_status))


# Edit a quote's date/time (admin only)
@app.route('/modapp/edit_date/<int:id>', methods=['POST'])
def edit_quote_date(id):
    if not session.get('admin'):
        flash('Access denied. Administrator login required.', 'danger')
        return redirect(url_for('login'))

    new_date_str = request.form.get('new_date', '').strip()
    filter_status = request.form.get('filter', 'pending')
    if filter_status not in ('pending', 'approved', 'rejected', 'flagged'):
        filter_status = 'pending'

    if not new_date_str:
        flash(f'Please enter a valid date/time for quote #{id}.', 'error')
        return redirect(url_for('modapp', filter=filter_status))

    try:
        # Parse the datetime-local input value (format: YYYY-MM-DDTHH:MM)
        new_dt = datetime.datetime.strptime(new_date_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        flash(f'Invalid date format for quote #{id}. Use YYYY-MM-DDTHH:MM.', 'error')
        return redirect(url_for('modapp', filter=filter_status))

    quote = db.session.get(Quote, id)
    if not quote:
        flash(f'Quote #{id} not found.', 'error')
        return redirect(url_for('modapp', filter=filter_status))

    try:
        def commit_date():
            quote.submitted_at = new_dt
            quote.date = new_dt  # Keep legacy field in sync too
            db.session.commit()
            return True

        db_retry_operation(commit_date)
        logging.info(f"Admin updated date of quote {id} to {new_dt}")
        message = f'Date for quote #{id} updated to {new_dt.strftime("%d/%m/%Y %H:%M")}.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message})
        flash(message, 'success')
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating date for quote {id}: {str(e)}")
        message = f'Error updating date for quote #{id}. Please try again.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': message})
        flash(message, 'error')

    return redirect(url_for('modapp', filter=filter_status))


# Edit a quote's text (admin only)
@app.route('/modapp/edit_text/<int:id>', methods=['POST'])
def edit_quote_text(id):
    if not session.get('admin'):
        flash('Access denied. Administrator login required.', 'danger')
        return redirect(url_for('login'))

    new_text = request.form.get('new_text', '').strip()
    filter_status = request.form.get('filter', 'pending')
    if filter_status not in ('pending', 'approved', 'rejected', 'flagged'):
        filter_status = 'pending'

    if not new_text:
        flash(f'Quote text cannot be empty for quote #{id}.', 'error')
        return redirect(url_for('modapp', filter=filter_status))

    max_length = config.get('quotes.max_length', 5000)
    min_length = config.get('quotes.min_length', 1)

    if len(new_text) < min_length:
        flash(f'Quote #{id} text is too short (minimum {min_length} characters).', 'error')
        return redirect(url_for('modapp', filter=filter_status))

    if len(new_text) > max_length:
        flash(f'Quote #{id} text is too long (maximum {max_length} characters).', 'error')
        return redirect(url_for('modapp', filter=filter_status))

    quote = db.session.get(Quote, id)
    if not quote:
        flash(f'Quote #{id} not found.', 'error')
        return redirect(url_for('modapp', filter=filter_status))

    try:
        def commit_text():
            quote.text = new_text
            db.session.commit()
            return True

        db_retry_operation(commit_text)
        logging.info(f"Admin edited text of quote {id}")
        message = f'Quote #{id} text updated successfully.'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message})
        flash(message, 'success')
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating text for quote {id}: {str(e)}")
        message = f'Error updating quote #{id}. Please try again.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': message})
        flash(message, 'error')

    return redirect(url_for('modapp', filter=filter_status))


# Admin logout route
@app.route('/logout')
def logout():
    # Clear the entire session for security
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

# Automatically create the database tables using app context
with app.app_context():
    db.create_all()
    
    # Add flag_count column if it doesn't exist (for existing databases)
    try:
        db.session.execute(db.text("SELECT flag_count FROM quote LIMIT 1"))
    except Exception as e:
        db.session.rollback()
        err = str(e).lower()
        if "does not exist" in err or "no such column" in err:
            db.session.execute(db.text("ALTER TABLE quote ADD COLUMN flag_count INTEGER DEFAULT 0"))
            db.session.commit()
            logging.info("Added flag_count column to existing database")
    
    # Add submitted_at column if it doesn't exist (for existing databases)
    try:
        db.session.execute(db.text("SELECT submitted_at FROM quote LIMIT 1"))
    except Exception as e:
        db.session.rollback()
        err = str(e).lower()
        if "does not exist" in err or "no such column" in err:
            db.session.execute(db.text("ALTER TABLE quote ADD COLUMN submitted_at TIMESTAMP"))
            db.session.commit()
            logging.info("Added submitted_at column to existing database")

# Initialize CORS for cross-origin API access
CORS(app)

# API to get all approved quotes with pagination
@app.route('/api/quotes', methods=['GET'])
def get_all_quotes():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)  # Max 100 per page
    sort = request.args.get('sort', 'date')
    order = request.args.get('order', 'desc')
    
    # Base query for approved quotes
    query = Quote.query.filter_by(status=1)
    
    # Apply sorting
    if sort == 'votes':
        sort_col = Quote.votes
    elif sort == 'id':
        sort_col = Quote.id
    else:  # default to date
        from sqlalchemy import func as sqlfunc
        sort_col = sqlfunc.coalesce(Quote.submitted_at, Quote.date)
        
    if order == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())
        
    quotes = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'quotes': [serialize_quote(q) for q in quotes.items],
        'pagination': {
            'page': quotes.page,
            'pages': quotes.pages,
            'per_page': quotes.per_page,
            'total': quotes.total,
            'has_next': quotes.has_next,
            'has_prev': quotes.has_prev
        }
    }), 200

# API to get a specific quote by ID
@app.route('/api/quotes/<int:id>', methods=['GET'])
def get_quote(id):
    quote = Quote.query.filter_by(id=id, status=1).first_or_404()  # Only approved quotes
    return jsonify(serialize_quote(quote)), 200

# API to get a random approved quote
@app.route('/api/random', methods=['GET'])
def get_random_quote():
    count = Quote.query.filter_by(status=1).count()
    if count == 0:
        return jsonify({"error": "No approved quotes available"}), 404
    
    # Use a safer approach to get random quote
    random_offset = random.randint(0, count - 1)
    random_quote = Quote.query.filter_by(status=1).offset(random_offset).first()
    
    # Handle potential race condition where quote could be None
    if not random_quote:
        return jsonify({"error": "No approved quotes available"}), 404
    
    return jsonify(serialize_quote(random_quote)), 200

# API to get the top quotes by vote count
@app.route('/api/top', methods=['GET'])
def get_top_quotes():
    limit = min(request.args.get('limit', 10, type=int), 100)
    min_votes = request.args.get('min_votes', 0, type=int)
    
    from sqlalchemy import func as sqlfunc
    sort_col = sqlfunc.coalesce(Quote.submitted_at, Quote.date)
    
    quotes = Quote.query.filter(
        Quote.status == 1,
        Quote.votes >= min_votes
    ).order_by(Quote.votes.desc(), sort_col.desc()).limit(limit).all()
    
    return jsonify({
        'quotes': [serialize_quote(q) for q in quotes],
        'limit': limit,
        'min_votes': min_votes,
        'count': len(quotes)
    }), 200

# API to search for quotes with pagination
@app.route('/api/search', methods=['GET'])
def search_quotes():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"error": "No search term provided"}), 400
    
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)  # Max 100 per page
    
    # Search in approved quotes with pagination using safe parameterized query
    quotes = Quote.query.filter(
        Quote.text.contains(query), 
        Quote.status == 1
    ).order_by(Quote.votes.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    if not quotes.items:
        return jsonify({
            "error": "No quotes found for search term",
            "search_term": query,
            "total_results": 0
        }), 404

    quote_list = [serialize_quote(quote) for quote in quotes.items]
    
    return jsonify({
        'quotes': quote_list,
        'search_term': query,
        'pagination': {
            'page': quotes.page,
            'pages': quotes.pages,
            'per_page': quotes.per_page,
            'total': quotes.total,
            'has_next': quotes.has_next,
            'has_prev': quotes.has_prev
        }
    }), 200

# API to get quote statistics
@app.route('/api/stats', methods=['GET'])
def get_stats():
    total_quotes = Quote.query.count()
    approved_quotes = Quote.query.filter_by(status=1).count()
    pending_quotes = Quote.query.filter_by(status=0).count()
    rejected_quotes = Quote.query.filter_by(status=2).count()
    flagged_quotes = Quote.query.filter(Quote.flag_count > 0).count()
    
    # Vote statistics
    top_voted = Quote.query.filter_by(status=1).order_by(Quote.votes.desc()).first()
    total_votes = db.session.query(db.func.sum(Quote.votes)).filter_by(status=1).scalar() or 0
    avg_votes = db.session.query(db.func.avg(Quote.votes)).filter_by(status=1).scalar() or 0
    
    return jsonify({
        'total_quotes': total_quotes,
        'approved_quotes': approved_quotes,
        'pending_quotes': pending_quotes,
        'rejected_quotes': rejected_quotes,
        'flagged_quotes': flagged_quotes,
        'vote_stats': {
            'total_votes': int(total_votes),
            'average_votes': round(float(avg_votes), 2),
            'highest_voted': {
                'id': top_voted.id if top_voted else None,
                'votes': top_voted.votes if top_voted else 0,
                'text_preview': top_voted.text[:100] + '...' if top_voted and len(top_voted.text) > 100 else (top_voted.text if top_voted else None)
            }
        }
    }), 200

# API documentation endpoint
@app.route('/api/docs', methods=['GET'])
def api_docs():
    docs = {
        "ircquotes.org API Documentation": {
            "version": "1.0",
            "description": "Read-only API for accessing IRC quotes",
            "base_url": request.url_root + "api/",
            "endpoints": {
                "/api/quotes": {
                    "method": "GET",
                    "description": "Get paginated list of approved quotes",
                    "parameters": {
                        "page": "Page number (default: 1)",
                        "per_page": "Results per page (default: 20, max: 100)",
                        "sort": "Sort by 'date', 'votes', or 'id' (default: 'date')",
                        "order": "Sort order 'asc' or 'desc' (default: 'desc')"
                    },
                    "example": "/api/quotes?page=1&per_page=10&sort=votes&order=desc"
                },
                "/api/quotes/<id>": {
                    "method": "GET",
                    "description": "Get a specific quote by ID",
                    "parameters": {
                        "id": "Quote ID (required)"
                    },
                    "example": "/api/quotes/12345"
                },
                "/api/random": {
                    "method": "GET",
                    "description": "Get a random approved quote",
                    "parameters": "None",
                    "example": "/api/random"
                },
                "/api/top": {
                    "method": "GET",
                    "description": "Get top-voted quotes",
                    "parameters": {
                        "limit": "Number of quotes to return (default: 10, max: 100)",
                        "min_votes": "Minimum vote threshold (default: 0)"
                    },
                    "example": "/api/top?limit=20&min_votes=5"
                },
                "/api/search": {
                    "method": "GET",
                    "description": "Search quotes by text content",
                    "parameters": {
                        "q": "Search query (required)",
                        "page": "Page number (default: 1)",
                        "per_page": "Results per page (default: 20, max: 100)"
                    },
                    "example": "/api/search?q=linux&page=1&per_page=10"
                },
                "/api/stats": {
                    "method": "GET",
                    "description": "Get quote database statistics",
                    "parameters": "None",
                    "example": "/api/stats"
                }
            },
            "response_format": {
                "quotes": "Array of quote objects",
                "quote_object": {
                    "id": "Quote ID (integer)",
                    "text": "Quote text content (string)",
                    "votes": "Current vote count (integer)",
                    "submitted_at": "ISO 8601 timestamp (string)",
                    "timestamp": "Unix epoch timestamp (integer)",
                    "datetime_display": "Human-readable timestamp (string: DD/MM/YY HH:MM:SS)"
                },
                "pagination": {
                    "page": "Current page number",
                    "pages": "Total pages",
                    "per_page": "Results per page",
                    "total": "Total results",
                    "has_next": "Boolean - has next page",
                    "has_prev": "Boolean - has previous page"
                }
            },
            "notes": [
                "All endpoints return only approved quotes",
                "Rate limiting may apply to prevent abuse",
                "All responses are in JSON format",
                "CORS is enabled for cross-origin requests"
            ]
        }
    }
    return jsonify(docs), 200

# API to submit a new quote (DISABLED for abuse prevention)
@app.route('/api/submit', methods=['POST'])
def submit_quote():
    return jsonify({
        "error": "Quote submission via API is currently disabled to prevent abuse.",
        "message": "Please use the web interface at /submit to submit quotes.",
        "web_submit_url": request.url_root + "submit"
    }), 403

# Note: db.create_all() is already called above with migration logic. No need to repeat.

# For development server (app.py)
if __name__ == '__main__':
    # This is only used for local development testing
    # In production, use: python production.py
    print("Starting Flask development server...")
    print(f"Debug mode: {config.get('app.debug', False)}")
    print(f"Host: {config.app_host}")
    print(f"Port: {config.app_port}")
    print("Warning: This is a development server. Use 'python production.py' for production!")
    
    app.run(
        host=config.app_host,
        port=config.app_port, 
        debug=config.get('app.debug', False)
    )

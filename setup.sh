#!/bin/bash

# ircquotes production server setup script
# Run this after cloning the repository

echo "Setting up ircquotes on production server..."

# Instance directory should already exist from git
# But create it if it doesn't
mkdir -p instance

# Generate secret key
echo "Generating Flask secret key..."
python3 -c "import secrets; print(secrets.token_hex(32))" > instance/flask_secret_key

# Create empty database file if it doesn't exist
if [ ! -f "instance/quotes.db" ]; then
    echo "Creating database file..."
    touch instance/quotes.db
fi

# Set permissions
echo "Setting file permissions..."
chmod 600 instance/flask_secret_key
chmod 664 instance/quotes.db

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv .venv

# Activate and install dependencies
echo "Installing dependencies..."
source .venv/bin/activate
pip install -r requirements.txt

# Initialize database
echo "Initializing database..."
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized successfully!')"

echo ""
echo "Setup complete! You can now:"
echo "1. Configure admin credentials:"
echo "   python generate_password.py"
echo "   # Then edit config.json and update admin.username and admin.password_hash"
echo ""
echo "2. Configure other settings by editing config.json:"
echo "   # app.port - Change server port"
echo "   # quotes.min_length - Minimum quote length"
echo "   # quotes.max_length - Maximum quote length"
echo "   # security.csrf_enabled - Enable/disable CSRF protection"
echo ""
echo "3. Start the application:"
echo "   source .venv/bin/activate"
echo "   gunicorn --config gunicorn.conf.py app:app"
echo ""
echo "4. Or run in development mode:"
echo "   python app.py"
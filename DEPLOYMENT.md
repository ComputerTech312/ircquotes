# ircquotes Production Deployment

## Configuration Management

### Configuration File: `config.json`
All application settings are now centralized in `config.json`. You can easily modify:

- **App settings** (host, port, debug mode)
- **Database configuration** (URI, connection pool settings)
- **Security settings** (CSRF, session cookies, security headers)
- **Rate limiting** (per-endpoint limits)
- **Quote settings** (length limits, pagination)
- **Admin credentials**
- **Feature toggles**

### Configuration Management
All configuration is done by editing `config.json` directly. This file contains all application settings organized in sections:

- **app**: Basic application settings (name, host, port, debug)
- **database**: Database connection settings
- **security**: Security headers, CSRF, proxy settings
- **rate_limiting**: Rate limiting configuration for different endpoints
- **admin**: Admin username and password hash
- **quotes**: Quote submission settings (length limits, pagination)
- **features**: Feature toggles (voting, flagging, dark mode, etc.)
- **logging**: Logging configuration

### Example Configuration Changes
```bash
# Edit config.json in any text editor
nano config.json

# Example changes:
# - Change port: "port": 8080 in the "app" section
# - Change quotes per page: "per_page": 50 in the "quotes" section  
# - Disable CSRF: "csrf_enabled": false in the "security" section
# - Change rate limits: "login": "10 per minute" in rate_limiting.endpoints

# After making changes, restart the application
```

## Running with Gunicorn (Production)

### Quick Start - Uses config.json settings
```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Option 1: Run with config file (recommended - uses config.json)
gunicorn --config gunicorn.conf.py app:app

# Option 2: Run with Python launcher (also uses config.json)
python start_gunicorn.py
```

### Manual Gunicorn Commands (ignores config.json)

**Basic production run:**
```bash
gunicorn -w 4 -b 127.0.0.1:6969 app:app
```

**With more workers (for higher traffic):**
```bash
gunicorn -w 8 -b 127.0.0.1:6969 --timeout 30 app:app
```

**Behind a reverse proxy (nginx/apache):**
```bash
gunicorn -w 4 -b 127.0.0.1:6969 app:app
```

### Environment Variables for Production
```bash
export FLASK_ENV=production
```

## Security Notes

- All major security vulnerabilities have been fixed
- CSRF protection enabled
- XSS protection with output escaping
- SQL injection prevention
- Rate limiting on all endpoints
- Secure session configuration
- Security headers added

## Admin Access
- Username: Configurable in `config.json` (default: admin)
- Password: Use the Argon2 hashed password in `config.json`

## Configuration Examples

### High-Traffic Setup
```json
{
  "quotes": {
    "per_page": 50
  },
  "rate_limiting": {
    "endpoints": {
      "vote": "120 per minute",
      "search": "60 per minute"
    }
  }
}
```

### Development Setup
```json
{
  "app": {
    "debug": true,
    "port": 5000
  },
  "security": {
    "session_cookie_secure": false
  },
  "logging": {
    "level": "DEBUG"
  }
}
```

### Production Security Setup
```json
{
  "security": {
    "session_cookie_secure": true,
    "csrf_enabled": true
  },
  "logging": {
    "level": "WARNING"
  }
}
```
# Configuration Guide

This guide explains how to configure the ircquotes application by editing `config.json` manually.

## Configuration File Structure

The `config.json` file is organized into sections:

### App Section
```json
"app": {
  "name": "ircquotes",      // Application name
  "host": "127.0.0.1",      // Host to bind to (use 0.0.0.0 for all interfaces)
  "port": 6969,             // Port number to run on
  "debug": false            // Enable debug mode (set to true for development)
}
```

### Gunicorn Section (Production Settings)
```json
"gunicorn": {
  "workers": 4,             // Number of worker processes
  "timeout": 30,            // Request timeout in seconds
  "keepalive": 5,           // Keep-alive timeout
  "max_requests": 1000,     // Max requests per worker before restart
  "preload": true           // Preload application code
}
```

### Database Section
```json
"database": {
  "uri": "sqlite:///quotes.db?timeout=20",  // Database connection string
  "pool_timeout": 20,                       // Connection pool timeout
  "pool_recycle": -1,                       // Connection recycle time (-1 = disabled)
  "pool_pre_ping": true                     // Test connections before use
}
```

### Security Section
```json
"security": {
  "csrf_enabled": true,                     // Enable CSRF protection
  "csrf_time_limit": null,                  // CSRF token time limit (null = no limit)
  "session_cookie_secure": false,          // Require HTTPS for session cookies
  "session_cookie_httponly": true,         // Prevent JavaScript access to session cookies
  "session_cookie_samesite": "Lax",        // SameSite policy for session cookies
  "security_headers": {
    "x_content_type_options": "nosniff",
    "x_frame_options": "DENY",
    "x_xss_protection": "1; mode=block",
    "strict_transport_security": "max-age=31536000; includeSubDomains",
    "content_security_policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
  }
}
```

### Admin Section
```json
"admin": {
  "username": "admin",                      // Admin username
  "password_hash": "..."                    // Argon2 password hash (use generate_password.py)
}
```

### Quotes Section
```json
"quotes": {
  "min_length": 1,                          // Minimum quote length in characters
  "max_length": 5000,                       // Maximum quote length in characters
  "per_page": 25,                           // Quotes displayed per page
  "auto_approve": false,                    // Automatically approve new quotes
  "allow_html": false                       // Allow HTML in quotes (not recommended)
}
```

### Features Section
```json
"features": {
  "voting_enabled": true,                   // Enable voting on quotes
  "flagging_enabled": true,                 // Enable flagging inappropriate quotes
  "copy_quotes_enabled": true,              // Enable copy-to-clipboard feature
  "dark_mode_enabled": true,                // Enable dark mode toggle
  "api_enabled": true,                      // Enable JSON API endpoints
  "bulk_moderation_enabled": true           // Enable bulk moderation actions
}
```

### Logging Section
```json
"logging": {
  "level": "DEBUG",                         // Logging level (DEBUG, INFO, WARNING, ERROR)
  "format": "%(asctime)s [%(levelname)s] %(message)s"  // Log message format
}
```

## Common Configuration Tasks

### Change Admin Password
1. Run: `python generate_password.py`
2. Edit `config.json` and update `admin.password_hash` with the generated hash
3. Restart the application

### Change Port
Edit the `app.port` value in `config.json`:
```json
"app": {
  "port": 8080
}
```

### Adjust Quote Limits
Edit the `quotes` section:
```json
"quotes": {
  "min_length": 10,
  "max_length": 2000,
  "per_page": 50
}
```

### Disable Features
Set feature flags to `false`:
```json
"features": {
  "voting_enabled": false,
  "flagging_enabled": false
}
```

### Adjust Rate Limits
Modify the `rate_limiting.endpoints` section:
```json
"rate_limiting": {
  "endpoints": {
    "submit": "10 per minute",
    "vote": "120 per minute"
  }
}
```

## Important Notes

- Always restart the application after making configuration changes
- Use valid JSON syntax (no trailing commas, proper quotes)
- Test configuration changes in a development environment first
- Keep backups of your working configuration
- Use `python generate_password.py` to create secure password hashes
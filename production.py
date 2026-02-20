#!/usr/bin/env python3
"""
Production launcher for ircquotes using Gunicorn
Reads all configuration from config.json
"""

import subprocess
import sys
import os
from config_loader import config

def main():
    """Launch Gunicorn with settings from config.json"""
    
    print("Starting ircquotes in production mode with Gunicorn...")
    
    # Get configuration values from config.json
    host = config.app_host
    port = config.app_port
    workers = config.get('gunicorn.workers', 1)  # Default to 1 to avoid SQLite locking
    timeout = config.get('gunicorn.timeout', 30)
    keepalive = config.get('gunicorn.keepalive', 5)
    max_requests = config.get('gunicorn.max_requests', 1000)
    preload = config.get('gunicorn.preload', True)
    
    # Use virtual environment's gunicorn if available
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_gunicorn = os.path.join(script_dir, '.venv', 'bin', 'gunicorn')
    
    if os.path.exists(venv_gunicorn):
        gunicorn_cmd = venv_gunicorn
        print(f"Using virtual environment Gunicorn: {venv_gunicorn}")
    else:
        gunicorn_cmd = 'gunicorn'
        print("Using system Gunicorn")
    
    # Build Gunicorn command with all config.json settings
    cmd = [
        gunicorn_cmd,
        '--bind', f'{host}:{port}',
        '--workers', str(workers),
        '--timeout', str(timeout),
        '--keep-alive', str(keepalive),  # Fixed: --keep-alive not --keepalive
        '--max-requests', str(max_requests),
        '--max-requests-jitter', '100',
        '--access-logfile', '-',  # Log to stdout
        '--error-logfile', '-',   # Log to stderr
        '--log-level', 'info'
    ]
    
    # Add preload option if enabled
    if preload:
        cmd.append('--preload')
    
    # Add the app module at the end
    cmd.append('app:app')
    
    print(f"Configuration:")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Workers: {workers}")
    print(f"  Timeout: {timeout}s")
    print(f"  Max Requests: {max_requests}")
    print(f"  Preload: {preload}")
    print()
    print(f"Gunicorn command: {' '.join(cmd)}")
    print()
    
    # Execute Gunicorn
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error starting Gunicorn: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping Gunicorn...")
        sys.exit(0)
    except FileNotFoundError:
        print("Error: Gunicorn not found. Please install it with: pip install gunicorn")
        sys.exit(1)

if __name__ == "__main__":
    main()
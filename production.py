#!/usr/bin/env python3
"""
Production launcher for ircquotes using Gunicorn
Supports start, stop, restart, and status.
Reads configuration from config.json
"""

import subprocess
import sys
import os
import signal
import time
from config_loader import config

PID_FILE = "ircquotes.pid"
LOG_FILE = "ircquotes.log"

def get_pid():
    """Read PID from PID file."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
        except (ValueError, IOError):
            return None
    return None

def is_running(pid):
    """Check if process is running."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def start():
    """Start Gunicorn in daemon mode."""
    pid = get_pid()
    if is_running(pid):
        print(f"ircquotes is already running (PID: {pid})")
        return

    print("Starting ircquotes in production mode...")
    
    # Get configuration values
    host = config.app_host
    port = config.app_port
    workers = config.get('gunicorn.workers', 1)
    timeout = config.get('gunicorn.timeout', 30)
    keepalive = config.get('gunicorn.keepalive', 5)
    max_requests = config.get('gunicorn.max_requests', 1000)
    preload = config.get('gunicorn.preload', True)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_gunicorn = os.path.join(script_dir, '.venv', 'bin', 'gunicorn')
    
    if os.path.exists(venv_gunicorn):
        gunicorn_cmd = venv_gunicorn
    else:
        gunicorn_cmd = 'gunicorn'
    
    # Build Gunicorn command with daemon options
    cmd = [
        gunicorn_cmd,
        '--bind', f'{host}:{port}',
        '--workers', str(workers),
        '--timeout', str(timeout),
        '--keep-alive', str(keepalive),
        '--max-requests', str(max_requests),
        '--max-requests-jitter', '100',
        '--access-logfile', LOG_FILE,
        '--error-logfile', LOG_FILE,
        '--log-level', 'info',
        '--daemon',
        '--pid', PID_FILE
    ]
    
    if preload:
        cmd.append('--preload')
    
    cmd.append('app:app')
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        # Give it a second to start and write the PID file
        time.sleep(1)
        new_pid = get_pid()
        if is_running(new_pid):
            print(f"ircquotes started successfully (PID: {new_pid}).")
        else:
            print("ircquotes failed to start. Check ircquotes.log for details.")
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error starting ircquotes: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: Gunicorn not found. Please install it with: pip install gunicorn")
        sys.exit(1)

def stop():
    """Stop the Gunicorn process."""
    pid = get_pid()
    if not is_running(pid):
        print("ircquotes is not running.")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        return

    print(f"Stopping ircquotes (PID: {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to exit
        for _ in range(10):
            if not is_running(pid):
                print("ircquotes stopped.")
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
                return
            time.sleep(1)
        
        print("Process did not stop, sending SIGKILL...")
        os.kill(pid, signal.SIGKILL)
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        print("ircquotes terminated.")
    except OSError as e:
        print(f"Error stopping ircquotes: {e}")

def restart():
    """Restart the Gunicorn process."""
    stop()
    time.sleep(1)
    start()

def status():
    """Report the current status."""
    pid = get_pid()
    if is_running(pid):
        print(f"ircquotes is running (PID: {pid})")
    else:
        print("ircquotes is not running.")

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 production.py [start|stop|restart|status]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    if command == 'start':
        start()
    elif command == 'stop':
        stop()
    elif command == 'restart':
        restart()
    elif command == 'status':
        status()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python3 production.py [start|stop|restart|status]")
        sys.exit(1)

if __name__ == "__main__":
    main()
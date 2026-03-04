#!/usr/bin/env python3
"""
ircquotes setup script.
Installs PostgreSQL if needed, creates the database/user, configures config.json,
creates a virtual environment, installs dependencies, and initialises the schema.

Run with:  python3 setup.py
"""

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

# ── coloured output helpers ──────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def info(msg: str)    -> None: print(_c("36", f"  → {msg}"))
def success(msg: str) -> None: print(_c("32", f"  ✓ {msg}"))
def warn(msg: str)    -> None: print(_c("33", f"  ! {msg}"))
def step(msg: str)    -> None: print(_c("1;34", f"\n[+] {msg}"))
def die(msg: str)     -> None:
    print(_c("1;31", f"\n[✗] {msg}"))
    sys.exit(1)

# ── helpers ───────────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
INSTANCE    = BASE_DIR / "instance"
VENV        = BASE_DIR / ".venv"

DB_NAME     = "ircquotes"
DB_USER     = "ircquotes"


def run(cmd: list[str], *, check: bool = True, capture: bool = False,
        input_text: str | None = None) -> subprocess.CompletedProcess:
    kwargs: dict = {"text": True}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if input_text is not None:
        kwargs["input"] = input_text
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        die(f"Command failed: {' '.join(cmd)}")
    return result


def _escape_sql_string(s: str) -> str:
    """Escape single quotes for use in a PostgreSQL SQL literal."""
    return s.replace("'", "''")


def sudo_psql(sql: str, *, dbname: str = "postgres",
              check: bool = True) -> subprocess.CompletedProcess:
    """Execute SQL as the postgres superuser."""
    return run(
        ["sudo", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
         "-d", dbname, "-c", sql],
        check=check, capture=True
    )


def psql_user_exists(username: str) -> bool:
    r = sudo_psql(f"SELECT 1 FROM pg_roles WHERE rolname='{username}';", check=False)
    return r.returncode == 0 and "1 row" in r.stdout


def psql_db_exists(dbname: str) -> bool:
    r = sudo_psql(f"SELECT 1 FROM pg_database WHERE datname='{dbname}';", check=False)
    return r.returncode == 0 and "1 row" in r.stdout


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "python"
    return VENV / "bin" / "python"


def venv_pip() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "pip"
    return VENV / "bin" / "pip"


# ── steps ─────────────────────────────────────────────────────────────────────

def check_python() -> None:
    step("Checking Python version")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        die(f"Python 3.10+ required (found {major}.{minor})")
    success(f"Python {major}.{minor} OK")


def install_postgresql() -> None:
    step("Checking PostgreSQL installation")
    if shutil.which("pg_isready"):
        success("PostgreSQL already installed")
        return

    if shutil.which("apt-get"):
        info("Installing postgresql via apt-get (this may take a minute)…")
        run(["sudo", "apt-get", "install", "-y", "postgresql", "postgresql-client"])
        success("PostgreSQL installed")
    elif shutil.which("dnf"):
        info("Installing postgresql via dnf…")
        run(["sudo", "dnf", "install", "-y", "postgresql-server", "postgresql"])
        run(["sudo", "postgresql-setup", "--initdb"])
        success("PostgreSQL installed")
    elif shutil.which("brew"):
        info("Installing postgresql via Homebrew…")
        run(["brew", "install", "postgresql@16"])
        run(["brew", "services", "start", "postgresql@16"])
        success("PostgreSQL installed")
    else:
        die(
            "Cannot auto-install PostgreSQL on this system.\n"
            "    Please install it manually and re-run setup.py."
        )


def start_postgresql() -> None:
    step("Starting PostgreSQL service")
    # systemd
    if shutil.which("systemctl"):
        r = run(["sudo", "systemctl", "is-active", "postgresql"],
                check=False, capture=True)
        if "active" in r.stdout:
            success("PostgreSQL is already running")
            return
        run(["sudo", "systemctl", "start", "postgresql"])
        run(["sudo", "systemctl", "enable", "postgresql"], check=False)
        success("PostgreSQL started and enabled")
        return
    # macOS launchd / brew services
    if shutil.which("brew"):
        run(["brew", "services", "start", "postgresql@16"], check=False)
        success("PostgreSQL started via brew services")
        return
    warn("Could not auto-start PostgreSQL — please start it manually if needed")


def create_db_user_and_database(db_password: str) -> None:
    step("Configuring PostgreSQL user and database")

    safe_pw = _escape_sql_string(db_password)

    if psql_user_exists(DB_USER):
        info(f"User '{DB_USER}' already exists \u2014 updating password")
        sudo_psql(f"ALTER USER {DB_USER} WITH PASSWORD '{safe_pw}';")
    else:
        info(f"Creating user '{DB_USER}'")
        sudo_psql(f"CREATE USER {DB_USER} WITH PASSWORD '{safe_pw}';")

    if psql_db_exists(DB_NAME):
        info(f"Database '{DB_NAME}' already exists — skipping creation")
    else:
        info(f"Creating database '{DB_NAME}'")
        sudo_psql(f"CREATE DATABASE {DB_NAME} OWNER {DB_USER};")

    # Ensure the user owns the database (idempotent)
    sudo_psql(f"ALTER DATABASE {DB_NAME} OWNER TO {DB_USER};")
    success(f"Database '{DB_NAME}' ready, owned by '{DB_USER}'")


def update_config(db_password: str) -> None:
    step("Updating config.json with PostgreSQL URI")
    with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    # URL-encode the password so special chars don't break the URI
    from urllib.parse import quote as urlquote
    safe_pw = urlquote(db_password, safe='')
    new_uri = f"postgresql://{DB_USER}:{safe_pw}@localhost/{DB_NAME}"
    cfg["database"]["uri"]          = new_uri
    cfg["database"]["pool_recycle"] = 300
    cfg["database"]["pool_pre_ping"] = True

    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")

    success(f"config.json updated → {new_uri}")


def create_instance_dir() -> None:
    step("Preparing instance directory")
    INSTANCE.mkdir(exist_ok=True)

    secret_key_file = INSTANCE / "flask_secret_key"
    if secret_key_file.exists():
        info("Flask secret key already exists — leaving it unchanged")
    else:
        info("Generating Flask secret key")
        secret_key_file.write_text(secrets.token_hex(32))

    secret_key_file.chmod(0o600)
    success("instance/ directory ready")


def create_virtualenv() -> None:
    step("Setting up Python virtual environment")
    if VENV.exists():
        info(".venv already exists — skipping creation")
    else:
        info("Creating .venv")
        run([sys.executable, "-m", "venv", str(VENV)])
    success(".venv ready")


def install_dependencies() -> None:
    step("Installing Python dependencies")
    req = BASE_DIR / "requirements.txt"
    if not req.exists():
        die("requirements.txt not found")
    run([str(venv_pip()), "install", "--quiet", "--upgrade", "pip"])
    run([str(venv_pip()), "install", "--quiet", "-r", str(req)])
    success("Dependencies installed")


def init_database_schema() -> None:
    step("Initialising database schema")
    script = (
        "import sys, os; "
        f"os.chdir('{BASE_DIR}'); "
        "from app import app, db; "
        "ctx = app.app_context(); ctx.push(); "
        "db.create_all(); "
        "print('schema OK')"
    )
    r = run([str(venv_python()), "-c", script], capture=True)
    if "schema OK" not in r.stdout and "schema OK" not in r.stderr:
        # Some output goes to stderr; tolerate warnings
        combined = r.stdout + r.stderr
        if r.returncode != 0:
            print(combined)
            die("Failed to initialise database schema")
    success("Schema created / verified")


def print_summary(db_password: str) -> None:
    print(_c("1;32", "\n══════════════════════════════════════════"))
    print(_c("1;32",   "  ircquotes setup complete!"))
    print(_c("1;32",   "══════════════════════════════════════════"))
    print(f"""
  Database : postgresql://{DB_USER}:***@localhost/{DB_NAME}
  Config   : config.json
  Venv     : .venv/

  Next steps:

  1. Set admin credentials (generates an Argon2 hash):
       .venv/bin/python generate_password.py

  2. Start in development mode:
       .venv/bin/python app.py

  3. Start in production mode:
       .venv/bin/python production.py

  The database password is stored only in config.json.
""")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(_c("1;34", "\nircquotes setup\n" + "─" * 40))

    check_python()
    install_postgresql()
    start_postgresql()

    db_password = secrets.token_urlsafe(24)

    create_db_user_and_database(db_password)
    update_config(db_password)
    create_instance_dir()
    create_virtualenv()
    install_dependencies()
    init_database_schema()
    print_summary(db_password)


if __name__ == "__main__":
    main()

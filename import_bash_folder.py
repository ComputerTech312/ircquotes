import os
import datetime
import sys

BASH_DIR = 'bash.org'

if not os.path.exists(BASH_DIR):
    print(f"Directory {BASH_DIR} not found!")
    sys.exit(1)

# Use the Flask app context and SQLAlchemy models
from app import app, db, Quote

with app.app_context():
    # Get list of files
    try:
        files = sorted(os.listdir(BASH_DIR))
    except FileNotFoundError:
        print(f"Could not list directory {BASH_DIR}")
        sys.exit(1)

    print(f"Found {len(files)} files to process.")

    count = 0
    skipped = 0

    current_time = datetime.datetime.utcnow()

    for filename in files:
        if filename.endswith('.txt'):
            filepath = os.path.join(BASH_DIR, filename)

            # Determine encoding? Bash.org is old. Let's try latin-1 which covers most Western ISO/Windows encodings commonly used then.
            # UTF-8 might fail for old dumps.
            try:
                with open(filepath, 'r', encoding='iso-8859-1') as f:
                    text = f.read().strip()
            except UnicodeDecodeError:
                # Fallback
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read().strip()

            if not text:
                skipped += 1
                print(f"Skipping empty file: {filename}")
                continue

            try:
                # Check for duplicates (exact match) to avoid re-importing identical text
                existing = Quote.query.filter_by(text=text).first()
                if existing:
                    skipped += 1
                    if skipped % 100 == 0:
                        print(f"Skipping duplicates... ({skipped})", end='\r')
                    continue

                # Insert
                quote = Quote(
                    text=text,
                    votes=0,
                    status=1,
                    submitted_at=current_time,
                    ip_address='bash.org_import',
                    user_agent='importer',
                    flag_count=0,
                )
                db.session.add(quote)

                count += 1
                if count % 100 == 0:
                    print(f"Imported {count} quotes...", end='\r')
                    db.session.commit()

            except Exception as e:
                db.session.rollback()
                print(f"Database error on {filename}: {e}")
                skipped += 1

    print()  # Newline after carriage returns
    db.session.commit()
    print(f"Finished! Imported {count} quotes. Skipped {skipped} (empty or duplicates).")

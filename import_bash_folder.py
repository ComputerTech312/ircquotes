import os
import sqlite3
import datetime
import sys

DB_PATH = 'instance/quotes.db'
BASH_DIR = 'bash.org'

if not os.path.exists(BASH_DIR):
    print(f"Directory {BASH_DIR} not found!")
    sys.exit(1)

print(f"Connecting to database at {DB_PATH}...")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

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
            cursor.execute("SELECT id FROM quote WHERE text = ?", (text,))
            if cursor.fetchone():
                skipped += 1
                if skipped % 100 == 0:
                     print(f"Skipping duplicates... ({skipped})", end='\r')
                continue

            # Insert
            cursor.execute("""
                INSERT INTO quote (text, votes, status, submitted_at, ip_address, user_agent, flag_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (text, 0, 1, current_time, 'bash.org_import', 'importer', 0))
            
            count += 1
            if count % 100 == 0:
                print(f"Imported {count} quotes...", end='\r')
                conn.commit()
                
        except sqlite3.Error as e:
            print(f"Database error on {filename}: {e}")
            skipped += 1

print() # Newline after carriage returns
conn.commit()
conn.close()
print(f"Finished! Imported {count} quotes. Skipped {skipped} (empty or duplicates).")

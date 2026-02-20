#!/usr/bin/env python3
"""Create a fresh quotes database with test data"""

import os
import sqlite3
import sys
from datetime import datetime

print("WARNING: This script will DELETE the existing database and create a new one with test data.")
response = input("Are you sure you want to continue? (yes/no): ")
if response.lower() != 'yes':
    print("Operation cancelled.")
    sys.exit(0)

# Remove existing database files
db_files = ['instance/quotes.db', 'instance/quotes.db-shm', 'instance/quotes.db-wal']
for db_file in db_files:
    if os.path.exists(db_file):
        os.remove(db_file)
        print(f"Removed {db_file}")

# Create fresh database
conn = sqlite3.connect('instance/quotes.db')
cursor = conn.cursor()

# Create the quote table with proper schema
cursor.execute("""
CREATE TABLE quote (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    votes INTEGER DEFAULT 0,
    date DATETIME,
    status INTEGER DEFAULT 0,
    ip_address TEXT,
    user_agent TEXT,
    submitted_at DATETIME,
    flag_count INTEGER DEFAULT 0
)
""")

# Create vote table
cursor.execute("""
CREATE TABLE vote (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL,
    ip_address TEXT,
    vote_type TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(quote_id) REFERENCES quote(id)
)
""")

# Create indexes for performance
cursor.execute("CREATE INDEX idx_status_id ON quote(status, id)")
cursor.execute("CREATE INDEX idx_flag_count_id ON quote(flag_count, id)")
cursor.execute("CREATE INDEX idx_vote_quote_ip ON vote(quote_id, ip_address)")

# Insert test data
test_quotes = [
    ("This is a pending quote for testing moderation", 0, 0),  # pending
    ("This is an approved quote that should appear in browse", 5, 1),  # approved  
    ("Another approved quote with positive votes", 12, 1),  # approved
    ("A rejected quote that was not good enough", -2, 2),  # rejected
    ("Another pending quote to test approve/reject", 0, 0),  # pending
    ("Third pending quote for comprehensive testing", 0, 0),  # pending
]

current_time = datetime.now()

for i, (text, votes, status) in enumerate(test_quotes, 1):
    cursor.execute("""
        INSERT INTO quote (text, votes, status, submitted_at, ip_address, user_agent, flag_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (text, votes, status, current_time, '127.0.0.1', 'Test Script', 0))

# Set WAL mode for better concurrency
cursor.execute("PRAGMA journal_mode=WAL")
cursor.execute("PRAGMA busy_timeout=1000")

# Commit and close
conn.commit()

# Verify the data
cursor.execute("SELECT id, text, status FROM quote ORDER BY id")
results = cursor.fetchall()

print("\nCreated fresh database with test quotes:")
print("ID | Status | Text")
print("-" * 50)
for quote_id, text, status in results:
    status_name = {0: "PENDING", 1: "APPROVED", 2: "REJECTED"}[status]
    print(f"{quote_id:2d} | {status_name:8s} | {text[:40]}...")

conn.close()
print(f"\nFresh database created successfully!")
print(f"Total quotes: {len(test_quotes)}")
print("3 pending, 2 approved, 1 rejected")
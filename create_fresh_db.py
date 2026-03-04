#!/usr/bin/env python3
"""Create a fresh quotes database with test data (PostgreSQL)"""

import sys
from datetime import datetime

print("WARNING: This script will DROP and recreate all tables, deleting all existing data.")
response = input("Are you sure you want to continue? (yes/no): ")
if response.lower() != 'yes':
    print("Operation cancelled.")
    sys.exit(0)

# Use Flask app context so SQLAlchemy models drive schema creation
from app import app, db, Quote, Vote

with app.app_context():
    print("Dropping all existing tables...")
    db.drop_all()
    print("Creating tables from SQLAlchemy models...")
    db.create_all()

    # Insert test data
    test_quotes = [
        ("This is a pending quote for testing moderation", 0, 0),       # pending
        ("This is an approved quote that should appear in browse", 5, 1), # approved
        ("Another approved quote with positive votes", 12, 1),           # approved
        ("A rejected quote that was not good enough", -2, 2),            # rejected
        ("Another pending quote to test approve/reject", 0, 0),          # pending
        ("Third pending quote for comprehensive testing", 0, 0),         # pending
    ]

    current_time = datetime.utcnow()

    for text, votes, status in test_quotes:
        q = Quote(
            text=text,
            votes=votes,
            status=status,
            submitted_at=current_time,
            ip_address='127.0.0.1',
            user_agent='Test Script',
            flag_count=0,
        )
        db.session.add(q)

    db.session.commit()

    results = Quote.query.order_by(Quote.id).all()

    print("\nCreated fresh database with test quotes:")
    print("ID | Status   | Text")
    print("-" * 50)
    for q in results:
        status_name = {0: "PENDING", 1: "APPROVED", 2: "REJECTED"}.get(q.status, "UNKNOWN")
        print(f"{q.id:2d} | {status_name:8s} | {q.text[:40]}...")

print(f"\nFresh database created successfully!")
print(f"Total quotes: {len(test_quotes)}")
print("3 pending, 2 approved, 1 rejected")
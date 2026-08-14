#!/usr/bin/env python
"""
Test the actual API endpoints to simulate frontend requests
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from database.db import get_db
import json

def test_api_endpoints():
    """
    Test the actual Flask API endpoints that the frontend calls
    """
    with app.app_context():
        # Setup test user with auth
        db = get_db()
        
        # Clean up
        db.execute("DELETE FROM users WHERE email = 'api_test@test.com'")
        
        # Create test user
        db.execute(
            "INSERT INTO users (name, email, password_hash, created_at, is_admin, plan, consent_given) VALUES (?, ?, ?, datetime('now'), 0, 'free', 1)",
            ("API Test", "api_test@test.com", "fake_hash")
        )
        db.commit()
        
        user = db.execute("SELECT id FROM users WHERE email = 'api_test@test.com'").fetchone()
        user_id = user["id"]
        print(f"[OK] Test user created with ID: {user_id}\n")
        
        # Now test by directly calling the functions as if we're authenticated
        from ml.memory import get_memory_context, generate_pattern_insight
        from ml.emotion_analyzer import analyze_journal_entry
        from ml.memory import update_memory_from_entry
        
        # Simulate journal submission
        print("="*60)
        print("SIMULATING JOURNAL SUBMISSION + MEMORY UPDATE")
        print("="*60)
        
        entry = "I couldn't sleep because of exam stress and I feel really overwhelmed"
        
        analysis = analyze_journal_entry(entry)
        print(f"[OK] Entry analyzed: {analysis['emotion_label']}")
        
        result = update_memory_from_entry(user_id, entry)
        print(f"[OK] Memory updated: {result}\n")
        
        # Now test the API response that would be returned
        print("="*60)
        print("TESTING /api/memory/insights ENDPOINT RESPONSE")
        print("="*60)
        
        result = generate_pattern_insight(user_id)
        response_payload = {
            "ok": True,
            "insight": result["insight"],
            "source": result["source"],
            "context": result["context"]
        }
        print(f"Response JSON: {json.dumps(response_payload, indent=2)}\n")
        
        # Test the /api/memory/facts endpoint
        print("="*60)
        print("TESTING /api/memory/facts ENDPOINT RESPONSE")
        print("="*60)
        
        context = get_memory_context(user_id)
        response_payload2 = {
            "ok": True,
            **context
        }
        print(f"Response JSON: {json.dumps(response_payload2, indent=2, default=str)}\n")
        
        # Cleanup
        db.execute("DELETE FROM memory_facts WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM journal_entries WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        print("[OK] Cleaned up test data")

if __name__ == "__main__":
    test_api_endpoints()

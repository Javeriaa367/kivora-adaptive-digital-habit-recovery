#!/usr/bin/env python
"""
Diagnostic script to trace the memory pipeline end-to-end.
Tests: journal save -> memory extraction -> memory retrieval
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from database.db import (
    get_active_memory_facts, get_db
)
from ml.memory import update_memory_from_entry, get_memory_context, generate_pattern_insight
from ml.emotion_analyzer import analyze_journal_entry

def test_full_pipeline():
    """
    1. Create test user
    2. Save multiple journal entries
    3. Check memory extraction
    4. Check memory retrieval
    5. Verify endpoints
    """
    with app.app_context():
        # Create test user
        db = get_db()
        
        # Clean up any existing test user
        db.execute("DELETE FROM users WHERE email = 'diagnostic@test.com'")
        
        # Insert test user
        db.execute(
            "INSERT INTO users (name, email, password_hash, created_at, is_admin, plan, consent_given) VALUES (?, ?, ?, datetime('now'), 0, 'free', 1)",
            ("Diagnostic Test", "diagnostic@test.com", "fake_hash")
        )
        db.commit()
        
        # Get the user ID
        user = db.execute("SELECT id FROM users WHERE email = 'diagnostic@test.com'").fetchone()
        user_id = user["id"]
        print(f"[OK] Created test user ID: {user_id}")
        
        # Test 1: Save first journal entry
        entry1 = "I couldn't sleep last night because I'm stressed about my exams"
        analysis1 = analyze_journal_entry(entry1)
        print(f"[OK] Journal Entry 1 analyzed: emotion={analysis1['emotion_label']}, sentiment={analysis1['sentiment_score']:.2f}")
        
        # Update memory from entry
        result1 = update_memory_from_entry(user_id, entry1)
        print(f"[OK] Memory updated from entry 1: {result1}")
        
        # Test 2: Save second journal entry with similar themes
        entry2 = "Still haven't slept well. The exam stress is overwhelming."
        analysis2 = analyze_journal_entry(entry2)
        print(f"[OK] Journal Entry 2 analyzed: emotion={analysis2['emotion_label']}, sentiment={analysis2['sentiment_score']:.2f}")
        
        result2 = update_memory_from_entry(user_id, entry2)
        print(f"[OK] Memory updated from entry 2: {result2}")
        
        # Test 3: Retrieve memory facts from database
        print("\n" + "="*50)
        print("CHECKING MEMORY FACTS IN DATABASE")
        print("="*50)
        
        facts = get_active_memory_facts(user_id, limit=10)
        print(f"Total active facts in database: {len(facts)}")
        for fact in facts:
            print(f"  - [{fact['fact_type']}] {fact['fact_text']} (occurrences: {fact['occurrence_count']})")
        
        if not facts:
            print("[WARNING] No memory facts found in database!")
            print("This suggests memory extraction is not storing to database")
        
        # Test 4: Get memory context (what would be returned to UI/API)
        print("\n" + "="*50)
        print("CHECKING MEMORY CONTEXT (API-LEVEL)")
        print("="*50)
        
        context = get_memory_context(user_id)
        print(f"Total active facts in context: {context['total_active_facts']}")
        print(f"Facts by type: {context['facts_by_type']}")
        print(f"Recent summaries: {len(context['recent_summaries'])} summaries")
        
        # Test 5: Generate pattern insight
        print("\n" + "="*50)
        print("CHECKING PATTERN INSIGHT")
        print("="*50)
        
        insight = generate_pattern_insight(user_id)
        print(f"Insight: {insight['insight']}")
        print(f"Source: {insight['source']}")
        
        # Test 6: Check raw database query
        print("\n" + "="*50)
        print("RAW DATABASE QUERY CHECK")
        print("="*50)
        
        raw_query = db.execute(
            "SELECT id, user_id, fact_type, fact_text, active, occurrence_count FROM memory_facts WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        print(f"Raw query result count: {len(raw_query)}")
        for row in raw_query:
            print(f"  - ID={row['id']}, type={row['fact_type']}, active={row['active']}, count={row['occurrence_count']}")
        
        # Test 7: Check if memory_facts table exists and has schema
        print("\n" + "="*50)
        print("DATABASE SCHEMA CHECK")
        print("="*50)
        
        try:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_facts'"
            ).fetchone()
            if tables:
                print("[OK] memory_facts table exists")
                schema = db.execute("PRAGMA table_info(memory_facts)").fetchall()
                for col in schema:
                    print(f"  - {col['name']}: {col['type']}")
            else:
                print("[ERROR] memory_facts table NOT FOUND!")
        except Exception as e:
            print(f"[ERROR] Error checking schema: {e}")
        
        # Cleanup
        print("\n" + "="*50)
        db.execute("DELETE FROM memory_facts WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        print("[OK] Cleaned up test data")

if __name__ == "__main__":
    test_full_pipeline()

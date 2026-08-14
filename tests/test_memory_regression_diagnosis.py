"""
DIAGNOSTIC TEST: Journal Memory + Risk Insights Regression
============================================================

This test traces the COMPLETE data flow from journal entry submission
through memory extraction, storage, retrieval, and risk calculation.

It will identify EXACTLY where the data stops flowing.
"""

import json
from database.db import (
    get_active_memory_facts, get_journal_entry_count, 
    insert_memory_fact
)
from ml.memory import (
    extract_facts_from_entry, update_memory_from_entry, 
    get_memory_context, get_memory_facts_for_management, generate_pattern_insight
)
from ml.emotion_analyzer import analyze_journal_entry


def test_complete_journal_memory_pipeline(app, make_user):
    """Simulate the exact flow that happens when a user submits a journal entry."""
    user_id = make_user()
    
    # The exact text that a user would submit
    entry_text = (
        "Can't sleep again. Another exam coming up. Been feeling really stressed about it. "
        "Stayed up scrolling Instagram instead of studying. Feeling lonely and overwhelmed."
    )
    
    with app.app_context():
        print("\n" + "="*80)
        print("STEP 1: Extract facts from entry")
        print("="*80)
        
        facts = extract_facts_from_entry(entry_text)
        print(f"✓ Extracted {len(facts)} facts from entry")
        for i, fact in enumerate(facts, 1):
            print(f"  {i}. [{fact['type']}] {fact['text']}")
        
        if len(facts) == 0:
            print("⚠ WARNING: No facts extracted! This is the first issue.")
            print(f"  - Entry text length: {len(entry_text)}")
            print(f"  - Entry text contains keywords like: exam, sleep, stressed, overwhelmed")
            return False
        
        print("\n" + "="*80)
        print("STEP 2: Run update_memory_from_entry (the main function)")
        print("="*80)
        
        result = update_memory_from_entry(user_id, entry_text)
        print(f"✓ update_memory_from_entry returned: {result}")
        print(f"  - facts_extracted: {result['facts_extracted']}")
        print(f"  - facts_touched: {result['facts_touched']}")
        
        print("\n" + "="*80)
        print("STEP 3: Verify facts were actually stored in database")
        print("="*80)
        
        # Query the database directly
        stored_facts = get_active_memory_facts(user_id)
        print(f"✓ Query returned {len(stored_facts)} active facts for user_id={user_id}")
        
        for fact in stored_facts:
            print(f"  - [{fact['fact_type']}] {fact['fact_text']} (occurrences: {fact['occurrence_count']}, active: {fact['active']})")
        
        if len(stored_facts) == 0:
            print("✗ REGRESSION FOUND: Facts were extracted but not stored!")
            print("  - Either insert_memory_fact() is failing silently")
            print("  - OR facts are being marked as inactive")
            print("  - OR database commit is not persisting the data")
            return False
        
        print("\n" + "="*80)
        print("STEP 4: Verify retrieval via get_memory_facts_for_management")
        print("="*80)
        
        management_facts = get_memory_facts_for_management(user_id)
        print(f"✓ get_memory_facts_for_management returned {len(management_facts)} facts")
        for fact in management_facts:
            print(f"  - ID:{fact['id']} [{fact['type']}] {fact['text']} ({fact['occurrences']}x)")
        
        if len(management_facts) == 0:
            print("✗ REGRESSION: Facts exist in database but retrieval query returns empty!")
            return False
        
        print("\n" + "="*80)
        print("STEP 5: Verify get_memory_context (used by API)")
        print("="*80)
        
        context = get_memory_context(user_id)
        print(f"✓ get_memory_context returned context")
        print(f"  - total_active_facts: {context['total_active_facts']}")
        print(f"  - facts_by_type keys: {list(context['facts_by_type'].keys())}")
        
        for fact_type, items in context["facts_by_type"].items():
            print(f"  - {fact_type}: {len(items)} items")
            for item in items:
                print(f"    • {item['text']}")
        
        if context["total_active_facts"] == 0:
            print("✗ REGRESSION: get_memory_context returns zero facts!")
            print("  - This is what the frontend UI sees")
            print("  - The UI will display 'Nothing stored yet'")
            return False
        
        print("\n" + "="*80)
        print("STEP 6: Generate pattern insight (what user sees on journal page)")
        print("="*80)
        
        insight = generate_pattern_insight(user_id)
        print(f"✓ generate_pattern_insight returned:")
        print(f"  - insight: '{insight['insight']}'")
        print(f"  - source: {insight['source']}")
        
        if "Still learning" in insight["insight"]:
            print("⚠ Issue: Insight shows 'Still learning' because total_active_facts < 2")
        else:
            print("✓ Insight correctly shows the pattern!")
        
        print("\n" + "="*80)
        print("✓ COMPLETE: Pipeline works end-to-end!")
        print("="*80)
        
        return True


def test_user_id_isolation(app, make_user):
    """Verify that User A's memory doesn't appear for User B"""
    user_a = make_user()
    user_b = make_user()
    
    with app.app_context():
        print("\n" + "="*80)
        print("TESTING USER ISOLATION")
        print("="*80)
        
        # User A writes an entry
        entry_text = "I'm stressed about exams"
        update_memory_from_entry(user_a, entry_text)
        
        # Check User A's memory
        facts_a = get_active_memory_facts(user_a)
        print(f"User A has {len(facts_a)} facts")
        
        # Check User B's memory
        facts_b = get_active_memory_facts(user_b)
        print(f"User B has {len(facts_b)} facts")
        
        if len(facts_a) > 0 and len(facts_b) == 0:
            print("✓ PASS: User isolation works correctly")
            return True
        else:
            print("✗ FAIL: User isolation issue detected!")
            return False


def test_journal_entry_count(app, make_user):
    """Verify that get_journal_entry_count is returning correct values"""
    from database.db import save_journal_entry
    user_id = make_user()
    
    with app.app_context():
        print("\n" + "="*80)
        print("TESTING JOURNAL ENTRY COUNT")
        print("="*80)
        
        # Simulate saving a journal entry
        analysis = analyze_journal_entry("Test entry about stress")
        entry = save_journal_entry(user_id, "Test entry about stress", analysis)
        print(f"✓ Saved journal entry: {entry['id']}")
        
        count = get_journal_entry_count(user_id)
        print(f"✓ Journal entry count for user_id={user_id}: {count}")
        
        if count > 0:
            print("✓ PASS: Journal entry count is correct")
            return True
        else:
            print("✗ FAIL: Journal entry count is zero!")
            return False


if __name__ == "__main__":
    print("Run these tests with: pytest tests/test_memory_regression_diagnosis.py -v -s")

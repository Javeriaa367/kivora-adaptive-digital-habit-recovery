"""
spec section 20 -- Retrieval:
    * relevant memory returned
    * irrelevant memory excluded

Also covers spec section 6/9 ("do NOT send every stored memory to Gemini" /
memory lifecycle): retrieval must be bounded and must exclude
deactivated/pruned facts.
"""
from database.db import deactivate_memory_fact, insert_memory_fact
from ml.memory import CONTEXT_FACT_LIMIT, get_memory_context, get_memory_prompt_block


def test_relevant_fact_is_returned(app, make_user):
    user_id = make_user()
    with app.app_context():
        insert_memory_fact(user_id, "stressor", "stressed about exams", "stressed exams", 0.6, "journal")
        context = get_memory_context(user_id)

    assert context["total_active_facts"] == 1
    assert "stressed about exams" in context["facts_by_type"]["stressor"][0]["text"]


def test_deactivated_fact_is_excluded_from_retrieval(app, make_user):
    """A fact the system has decayed/pruned (active=0) is 'irrelevant' now
    and must never be surfaced again -- retrieval only reads active=1."""
    user_id = make_user()
    with app.app_context():
        keep_id = insert_memory_fact(user_id, "goal", "wants to improve sleep", "wants improve sleep", 0.6, "journal")
        stale_id = insert_memory_fact(user_id, "stressor", "one-off minor annoyance", "one off minor annoyance", 0.4, "journal")
        deactivate_memory_fact(stale_id)

        context = get_memory_context(user_id)

    assert context["total_active_facts"] == 1
    all_text = str(context["facts_by_type"])
    assert "wants to improve sleep" in all_text
    assert "one-off minor annoyance" not in all_text


def test_other_users_facts_never_appear(app, make_user):
    """Retrieval is inherently per-user -- never global. (Full cross-user
    access control is covered in test_memory_security.py; this checks the
    read path in isolation.)"""
    user_a = make_user()
    user_b = make_user()
    with app.app_context():
        insert_memory_fact(user_a, "goal", "user A's private goal", "user a private goal", 0.6, "journal")
        context_b = get_memory_context(user_b)

    assert context_b["total_active_facts"] == 0
    assert "user A's private goal" not in str(context_b)


def test_retrieval_is_bounded_not_a_full_dump(app, make_user):
    """spec section 6: never send every stored memory to a prompt. Insert
    more facts than CONTEXT_FACT_LIMIT and confirm the context returned is
    still capped."""
    user_id = make_user()
    with app.app_context():
        for i in range(CONTEXT_FACT_LIMIT + 15):
            insert_memory_fact(
                user_id, "theme", f"distinct theme number {i}", f"distinct theme number {i}", 0.5, "journal"
            )
        context = get_memory_context(user_id)

    assert context["total_active_facts"] <= CONTEXT_FACT_LIMIT


def test_memory_prompt_block_reflects_relevant_facts(app, make_user):
    """This is the exact string handed to the chatbot/companion system
    prompt (ml/chatbot.py) -- confirm it contains the stored fact text and
    is a plain string, never a raw dict dump."""
    user_id = make_user()
    with app.app_context():
        insert_memory_fact(user_id, "sleep_pattern", "reported poor sleep", "reported poor sleep", 0.6, "journal")
        block = get_memory_prompt_block(user_id)

    assert isinstance(block, str)
    assert "reported poor sleep" in block


def test_memory_prompt_block_empty_for_new_user(app, make_user):
    user_id = make_user()
    with app.app_context():
        block = get_memory_prompt_block(user_id)
    assert block == "(no stored facts yet)"

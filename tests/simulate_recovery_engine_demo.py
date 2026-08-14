from ml.recovery_state import RecoveryState, InterventionHistoryItem
from ml.selector import select_next_intervention

from ml import recovery_plans as rp
from database import db as DB


def print_choice(label, rs):
    choice = select_next_intervention(rs)
    print(f"\n=== {label} ===")
    if not choice:
        print("No choice returned")
        return
    print("id:", choice.get("id"))
    print("text:", choice.get("text"))
    print("selection_reason:", choice.get("selection_reason"))
    print("difficulty:", choice.get("difficulty"))


def scenario_1():
    # Different mechanisms
    a = RecoveryState(user_id=10)
    a.primary_mechanism = "automatic_checking"
    a.stage = 1

    b = RecoveryState(user_id=11)
    b.primary_mechanism = "boredom"
    b.stage = 1

    print_choice("Mechanism A: automatic_checking", a)
    print_choice("Mechanism B: boredom", b)


def scenario_2():
    # Failure of Intervention A
    s = RecoveryState(user_id=12)
    s.primary_mechanism = "automatic_checking"
    s.stage = 1
    s.intervention_history = [InterventionHistoryItem("auto_location_1", "ineffective", 1.0, None)]
    print_choice("After ineffective auto_location_1", s)


def scenario_3():
    # Success leads to progression (stage up)
    s = RecoveryState(user_id=13)
    s.primary_mechanism = "automatic_checking"
    s.stage = 2
    s.intervention_history = [InterventionHistoryItem("auto_pause_1", "success", 5.0, None)]
    print_choice("After successful auto_pause_1, stage 2", s)


def scenario_4():
    # Repeated failure / fatigue
    s = RecoveryState(user_id=14)
    s.primary_mechanism = "automatic_checking"
    s.stage = 1
    s.intervention_history = [
        InterventionHistoryItem("auto_pause_1", "ineffective", 1.0, None),
        InterventionHistoryItem("auto_location_1", "ineffective", 1.0, None),
    ]
    s.fatigue_score = 5.0
    print_choice("After repeated failures (high fatigue)", s)


def scenario_5():
    # Relapse response wiring and plan persistence
    # Create or reuse a test user so foreign key constraints succeed
    existing = DB.get_user_by_email("demo-relapse@example.invalid")
    if existing:
        user_id = existing["id"]
    else:
        user = DB.create_user("Demo Relapse", "demo-relapse@example.invalid", None)
        user_id = user["id"]
    # Monkeypatch RecoveryState.build so that _instantiate_plan will see relapse
    original_build = RecoveryState.build

    def fake_build(uid, lookback_days=30):
        rs = RecoveryState(user_id=uid)
        rs.primary_mechanism = "automatic_checking"
        rs.relapse = True
        rs.stage = 1
        return rs

    RecoveryState.build = staticmethod(fake_build)
    try:
        plan = rp._instantiate_plan(user_id, "digital_detox", source="test", reason="relapse_test",
                                     mechanism="automatic_checking", mechanism_reasons=["demo"], stage=1,
                                     is_relapse_response=True)
        print("\n=== Relapse plan created ===")
        print("plan id", plan.get("id"))
        tasks = DB.get_recovery_plan_tasks(plan["id"])
        # find day 2 timer
        timer = next((t for t in tasks if t["day_number"] == 2 and t["activity_type"] == "timer"), None)
        print("day2 task text:", timer["task_text"]) if timer else print("no timer task")
        print("intervention_id on task:", timer.get("intervention_id") if timer else None)
    finally:
        RecoveryState.build = original_build


def scenario_6():
    # Journal signal -> memory trigger -> infer_mechanism -> selection
    # create or reuse test user
    existing = DB.get_user_by_email("demo-journal@example.invalid")
    if existing:
        user_id = existing["id"]
    else:
        user = DB.create_user("Demo Journal", "demo-journal@example.invalid", None)
        user_id = user["id"]
    text = "I keep opening Instagram automatically whenever I sit down to study."
    DB.insert_memory_fact(user_id, "trigger", text, text, 0.7, source="journal")
    # Add a synthetic recent assessment so the mechanism inference has numeric signals
    DB.save_prediction(user_id, {"Scroll_Without_Purpose": 8, "Daily_Usage_Hours": 5}, {})
    mech, reasons, evidence = __import__("ml.behavioral_mechanisms", fromlist=["infer_mechanism"]).infer_mechanism(user_id)
    print("\n=== Journal-derived memory trigger ===")
    print("Inserted journal text as memory trigger for user", user_id)
    print("infer_mechanism ->", mech)
    print("reasons ->", reasons)
    rs = RecoveryState.build(user_id)
    print_choice("Selection after journal-based trigger", rs)


if __name__ == '__main__':
    scenario_1()
    scenario_2()
    scenario_3()
    scenario_4()
    scenario_5()
    scenario_6()

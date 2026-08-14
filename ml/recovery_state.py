from dataclasses import dataclass, field
from typing import List, Dict, Optional

from database.db import (
    get_latest_risk_profile, get_recent_activity_results, get_recent_predictions,
    get_last_finished_recovery_plan, get_recovery_plan_tasks, get_journal_entries_since,
)
from ml.behavioral_mechanisms import infer_mechanism


@dataclass
class InterventionHistoryItem:
    intervention_id: Optional[str]
    outcome: Optional[str]
    usefulness: Optional[float]
    completed_at: Optional[str]


@dataclass
class RecoveryState:
    user_id: int
    risk_profile: List[Dict] = field(default_factory=list)
    primary_mechanism: Optional[str] = None
    secondary_mechanism: Optional[str] = None
    mechanism_reasons: List[str] = field(default_factory=list)
    mechanism_has_evidence: bool = False
    intervention_history: List[InterventionHistoryItem] = field(default_factory=list)
    stage: int = 1
    relapse: bool = False
    recent_checkins: List[Dict] = field(default_factory=list)
    recent_journals: List[Dict] = field(default_factory=list)
    barriers: List[str] = field(default_factory=list)
    fatigue_score: float = 0.0

    @staticmethod
    def build(user_id: int, lookback_days: int = 30) -> "RecoveryState":
        state = RecoveryState(user_id=user_id)
        state.risk_profile = get_latest_risk_profile(user_id)

        mech, reasons, has_evidence = infer_mechanism(user_id)
        state.primary_mechanism = mech
        state.mechanism_reasons = reasons or []
        state.mechanism_has_evidence = has_evidence

        # recent check-ins and journals
        from datetime import datetime, timezone, timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        state.recent_checkins = get_recent_activity_results(user_id, "checkin", since)
        state.recent_journals = get_journal_entries_since(user_id, since)

        # intervention history: read last finished plan tasks
        last_plan = get_last_finished_recovery_plan(user_id)
        if last_plan:
            state.stage = last_plan.get("stage") or 1
            try:
                outcome = last_plan.get("outcome_json")
                if outcome and isinstance(outcome, str) and "relapse" in outcome:
                    state.relapse = True
            except Exception:
                state.relapse = False

        # Build intervention history from recent tasks in the last finished plan
        hist: List[InterventionHistoryItem] = []
        if last_plan:
            tasks = get_recovery_plan_tasks(last_plan["id"])
        else:
            tasks = []
        for t in tasks:
            result = None
            if t.get("result_json"):
                try:
                    import json
                    result = json.loads(t["result_json"])
                except Exception:
                    result = None
            hist.append(InterventionHistoryItem(
                intervention_id=t.get("intervention_id"),
                outcome=("success" if result and isinstance(result.get("usefulness"), (int, float)) and result.get("usefulness") >= 4 else ("partial" if result and isinstance(result.get("usefulness"), (int, float)) and result.get("usefulness") >= 2 else ("ineffective" if result else None))),
                usefulness=(result.get("usefulness") if isinstance(result, dict) else None),
                completed_at=t.get("completed_at"),
            ))
        state.intervention_history = hist

        # barriers: extract from recent_journals if user mentioned 'barrier' keywords
        barrier_keywords = ("not enough time", "no time", "busy", "no privacy", "can't", "cant")
        for j in state.recent_journals:
            text = (j.get("entry_text") or "").lower()
            for kw in barrier_keywords:
                if kw in text:
                    state.barriers.append(kw)
                    break

        # Fatigue score heuristic: skips + declining usefulness
        skips = sum(1 for t in tasks if t.get("state") == "skipped")
        usefulness_vals = [h.usefulness for h in hist if h.usefulness is not None]
        avg_use = sum(usefulness_vals) / len(usefulness_vals) if usefulness_vals else None
        state.fatigue_score = (skips * 1.0) + (0 if avg_use is None else max(0, 3 - avg_use))

        return state

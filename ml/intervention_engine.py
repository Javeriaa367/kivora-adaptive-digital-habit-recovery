"""Simple intervention engine: outcome classification and selection.

This module provides deterministic, easily-testable helpers used by the
Adaptive Recovery Engine to interpret outcomes and pick a next
intervention from the `ml.interventions` library.
"""
from typing import Dict, List, Optional
from ml.interventions import INTERVENTION_LIBRARY


def classify_outcome(task_result: Dict) -> str:
    """Classify an activity result: 'success', 'partial', or 'ineffective'.

    Rules (deterministic, conservative):
    - Prefer explicit `usefulness` when present (>=4 success, 2-3 partial, <=1 ineffective)
    - Timers that meet planned_seconds -> success; >=50%% planned -> partial
    - Otherwise fall back to 'ineffective'.
    """
    if not isinstance(task_result, dict):
        return "ineffective"

    u = task_result.get("usefulness")
    if isinstance(u, (int, float)):
        if u >= 4:
            return "success"
        if u >= 2:
            return "partial"
        return "ineffective"

    if "actual_seconds" in task_result and "planned_seconds" in task_result:
        try:
            actual = int(task_result.get("actual_seconds", 0))
            planned = int(task_result.get("planned_seconds", 0))
        except (TypeError, ValueError):
            return "ineffective"
        if planned and actual >= planned:
            return "success"
        if planned and actual >= planned * 0.5:
            return "partial"
        return "ineffective"

    return "ineffective"


def select_next_intervention(
    current_intervention_id: Optional[str],
    mechanism: str,
    history: List[Dict],
    stage: int = 1,
    is_relapse: bool = False,
    barriers: Optional[List[str]] = None,
) -> Optional[Dict]:
    """Choose the next intervention for a given mechanism.

    Selection considers:
    - candidate difficulty relative to `stage` (stage 1 easy, 3 harder)
    - prior history outcomes (prefer untried or previously 'partial')
    - relapse flag (prefer higher-intensity strategies)
    - reported barriers/tags to avoid suggested strategies that match barriers

    History items are dicts with keys: 'intervention_id', 'outcome' ('success'|'partial'|'ineffective'),
    optional 'usefulness' numeric. The function returns the chosen intervention dict or None.
    """
    candidates = INTERVENTION_LIBRARY.get(mechanism) or []
    if not candidates:
        return None

    # Build quick lookup of past outcomes
    past = {h.get("intervention_id"): h for h in history if h.get("intervention_id")}

    # Filter out candidates that conflict with reported barriers (if any)
    if barriers:
        cand_filtered = [c for c in candidates if not set(c.get("tags", [])) & set(barriers)]
        if cand_filtered:
            candidates = cand_filtered

    # Scoring: base score favors untried, then partial, then success (avoids repeating successes),
    # then prefer difficulty nearer to desired stage.
    def score(c):
        s = 0
        cid = c.get("id")
        past_rec = past.get(cid)
        if not past_rec:
            s += 50
        else:
            outcome = past_rec.get("outcome")
            if outcome == "partial":
                s += 30
            elif outcome == "ineffective":
                s += 40
            elif outcome == "success":
                s += 10

        # Stage adjustment: prefer difficulty close to 1+(stage-1)
        target_difficulty = min(max(1, stage), 4)
        diff = abs((c.get("difficulty") or 2) - target_difficulty)
        s += max(0, 20 - diff * 5)

        # Relapse: boost higher-difficulty items
        if is_relapse:
            s += (c.get("difficulty") or 1) * 5

        return s

    chosen = max(candidates, key=score)

    # If chosen equals current and there are untried alternatives, pick an untried one instead
    if current_intervention_id and chosen.get("id") == current_intervention_id:
        untried = [c for c in candidates if c.get("id") not in past]
        if untried:
            chosen = untried[0]

    return chosen


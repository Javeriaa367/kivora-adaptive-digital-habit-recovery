from typing import List, Dict, Optional
from ml.interventions import INTERVENTION_LIBRARY
from ml.recovery_state import RecoveryState


def select_next_intervention(recovery_state: RecoveryState) -> Optional[Dict]:
    """Deterministic selection of the next intervention given a RecoveryState.

    Returns the chosen intervention dict with an added `selection_reason` key.
    """
    mech = recovery_state.primary_mechanism
    if not mech:
        return None
    candidates = INTERVENTION_LIBRARY.get(mech, [])
    if not candidates:
        return None

    # Build fast lookups from history
    tried = {h.intervention_id: h for h in recovery_state.intervention_history if h.intervention_id}

    # Avoid interventions recently tried and failed
    def base_score(c):
        score = 0
        cid = c.get("id")
        hist = tried.get(cid)
        if not hist:
            score += 50
        else:
            if hist.outcome == "success":
                score += 10
            elif hist.outcome == "partial":
                score += 30
            elif hist.outcome == "ineffective":
                score += 40

        # Stage proximity: prefer difficulty near current stage
        target = min(max(1, recovery_state.stage), 4)
        diff = abs((c.get("difficulty") or 2) - target)
        score += max(0, 20 - diff * 5)

        # Fatigue: penalize higher-difficulty items
        if recovery_state.fatigue_score > 2:
            score -= (c.get("difficulty") or 1) * 5

        # Barriers: if any barrier tag overlaps, penalize heavily
        if recovery_state.barriers and set(c.get("tags", [])) & set(recovery_state.barriers):
            score -= 30

        # Relapse: prefer stronger interventions
        if recovery_state.relapse:
            score += (c.get("difficulty") or 1) * 5

        return score

    chosen = max(candidates, key=base_score)

    # Ensure we don't repeat an immediately ineffective intervention
    last = recovery_state.intervention_history[-1] if recovery_state.intervention_history else None
    if last and last.intervention_id == chosen.get("id") and last.outcome == "ineffective":
        # pick next best untried or partial
        alt = sorted(candidates, key=base_score, reverse=True)
        for a in alt:
            if a.get("id") != last.intervention_id:
                chosen = a
                break

    chosen = dict(chosen)
    chosen["selection_reason"] = (
        f"Mechanism '{mech}' selected; difficulty {chosen.get('difficulty')}; "
        f"stage {recovery_state.stage}; fatigue {recovery_state.fatigue_score:.1f}"
    )
    return chosen

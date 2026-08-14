"""
Adaptive Brain Exercises (Feature: Recovery companion micro-training).

A small, self-contained cognitive-training layer for the recovery plan.
Each plan day gets one micro-exercise chosen from a short, fully
deterministic pool -- attention, working memory, updating, cognitive
reframing, and a specificity scan. Everything is auto-scorable with no
external API, and difficulty adapts to how the user actually did:

  - the exercise for a (plan, day) is built server-side and stored in
    brain_exercise_attempts WITH its ground-truth answer; the client only
    ever receives a redacted prompt, so there is nothing to cheat from
  - a row with response_json IS NULL is the day's currently-issued
    exercise; submitting it records response + score and the NEXT fetch
    for that day builds a fresh one at an adjusted difficulty tier
  - tier moves up after a strong score (>=80%), down after a weak one
    (<=40%), otherwise stays; the base tier for a fresh day comes from
    the plan's own stage

Deliberately additive: brain exercises are never required to complete a
recovery day, never touch recovery_plan_tasks, and never change how the
activity engine works.
"""
import json
import random
from datetime import datetime, timezone

from database.db import (
    complete_brain_exercise_attempt,
    count_scored_brain_exercises,
    create_brain_exercise_attempt,
    get_brain_exercise_attempt,
    get_brain_exercises_for_plan,
    get_issued_brain_exercise,
    get_latest_scored_brain_exercise,
    get_recovery_plan,
)

KIND_TITLES = {
    "attention": "Target scan",
    "working_memory": "Memory Arena",
    "updating": "Keep the largest",
    "reframe": "Inner Critic Battle",
    "gratitude_scan": "Specific appreciation",
    "worry_reality": "Worry vs Reality",
    "night_reset": "Night Mind Reset",
    "urge_breaker": "Urge Breaker",
}

KIND_INSTRUCTIONS = {
    "attention": "Read the letter stream once, then enter how many times the target letter appears.",
    "working_memory": "Study the list, then answer the exact recall question -- no scrolling back. This is retrieval, the same skill exam recall depends on.",
    "updating": "Read the number sequence once and keep only the largest value in mind.",
    "reframe": "Your inner critic just said something harsh. Look at the evidence, then pick the response that's actually fair -- not the harshest one, and not empty positivity.",
    "gratitude_scan": "Name specific, concrete things you appreciated in the last 24 hours. Generic words don't count -- the more precise, the better.",
    "worry_reality": "A racing mind can make a prediction feel like a fact. Read the thought and decide what kind of thought it actually is.",
    "night_reset": "Not every thought needs handling right now. Decide whether this one is something you can act on this second, or something to park until morning.",
    "urge_breaker": "Notice the urge without acting on it right away. Pick what actually helps for the next five minutes.",
}

# Which plan type gets which user-facing recovery exercise. This is the
# one place that decides the mapping -- every plan gets exactly one,
# genuinely distinct cognitive exercise instead of a kind cycled by day
# number, which is what made all five plans feel interchangeable before.
PLAN_KIND_MAP = {
    "self_esteem": "reframe",         # Inner Critic Battle
    "anxiety": "worry_reality",       # Worry vs Reality
    "sleep": "night_reset",           # Night Mind Reset
    "exam_stress": "working_memory",  # Memory Arena
    "digital_detox": "urge_breaker",  # Urge Breaker
}

# KINDS covers every kind the scorer/builder understand -- both the five
# currently issued to users (via PLAN_KIND_MAP) and two older kinds kept
# for backward compatibility (attention, gratitude_scan are no longer
# issued as anyone's primary plan exercise, per the digital-detox review:
# a generic gratitude prompt doesn't teach urge-surfing).
KINDS = ("attention", "working_memory", "updating", "reframe", "gratitude_scan",
         "worry_reality", "night_reset", "urge_breaker")

WORKING_MEMORY_POOL = [
    "bridge", "lantern", "compass", "bicycle", "orchard", "candle", "anchor", "river",
    "saddle", "window", "tunnel", "garden", "pencil", "mirror", "shelter", "pyramid",
    "meadow", "pocket", "harbor", "ladder", "basket", "cottage", "satchel", "bonfire",
    "pebble", "pillow", "blanket", "station", "harbor", "marble",
]

UPDATING_NUMBER_RANGE = (1, 40)

# Each entry: situation, the anxious/pessimistic thought, three alternative
# framings. The balanced one is at the index marked by answer -- the other
# two are plausible but overgeneralized/catastrophizing, so picking them
# gets progressively harder to defend at higher tiers (distractors get
# subtler the higher the tier).
REFRAME_BANKS = {
    1: [
        ("You have a recovery day with three tasks on the plan.",
         "I'm going to fail the whole plan if I don't do every task perfectly.",
         ["I'll do what I can today and that's genuinely enough for recovery.",
          "I should abandon the plan since it's already ruined.",
          "Missing anything today proves I can never improve."],
         0),
        ("A friend didn't reply to your message for a few hours.",
         "They're annoyed with me and our friendship is falling apart.",
         ["They're probably busy; I can check in later without assuming the worst.",
          "I should stop talking to them entirely to avoid the rejection.",
          "One slow reply means I am fundamentally unlikeable."],
         0),
        ("You opened a social app when you meant to study for 20 minutes.",
         "I have zero self-control and my whole day is now wasted.",
         ["One slip doesn't erase the last 20 minutes of focus I did get.",
          "I might as well give up studying entirely today.",
          "This proves I'll never be able to change my habits."],
         0),
    ],
    2: [
        ("You felt anxious during the morning check-in activity.",
         "Feeling anxious now means my recovery isn't working at all.",
         ["Anxiety comes and goes; this morning's reading is one data point, not a verdict.",
          "I should have been cured by now, so recovery is pointless.",
          "If I feel anxious again tomorrow I'm back to square one."],
         0),
        ("You skipped one task on Day 3 of the plan.",
         "I've already broken the streak, so finishing the rest doesn't matter.",
         ["Skipping one task tells me what to adjust, not that the plan has failed.",
          "A broken streak means the entire plan is meaningless now.",
          "I'm the kind of person who never follows through, so why bother."],
         0),
        ("Your reflection took longer than expected and used most of your evening.",
         "Everything now feels rushed, so today's progress doesn't count.",
         ["I spent real time reflecting, which is the point of the day even if it ran long.",
          "Running late invalidates whatever I managed to finish.",
          "I'll never be able to fit recovery into a normal schedule."],
         0),
    ],
    3: [
        ("You compared your progress to someone else's post online.",
         "That person is doing better than me, so my recovery is behind schedule.",
         ["I'm only seeing a highlight, and my plan isn't a race against anyone else.",
          "If I'm not where they are, my entire recovery has failed.",
          "I should mirror their exact routine to be allowed to feel okay."],
         0),
        ("You had one rough evening where you checked your phone a lot.",
         "One bad evening means all the earlier wins this week were fake.",
         ["A rough evening is a signal to ease tomorrow's load, not proof the week failed.",
          "The whole week's progress is cancelled by one evening.",
          "I need to double every effort tomorrow to make up for it."],
         0),
        ("Your plan suggested a lower-effort task because it detected some skipped days.",
         "The app lowering the bar proves I'm not capable of a real recovery plan.",
         ["A lower-effort task is a sensible adjustment, not a judgment on my ability.",
          "Adapting the plan means I've been demoted and should quit.",
          "I need to push myself twice as hard to earn the original plan back."],
         0),
    ],
}

# Worry vs Reality (anxiety). Each entry: the thought as it shows up in
# someone's head, the three classification options, and the index of the
# correct one. The point is teaching prediction != fact and worry != fact
# -- higher tiers use thoughts where the surface wording sounds more
# fact-like even though it's still a prediction or a worry.
WORRY_CLASSIFICATION_OPTIONS = ["A FACT", "A PREDICTION", "A WORRY"]

WORRY_BANKS = {
    1: [
        ("My alarm went off at 7 AM today.", 0),
        ("I'm going to fail tomorrow's exam.", 1),
        ("Something bad might happen at the interview.", 2),
    ],
    2: [
        ("My heart is racing right now.", 0),
        ("He'll probably think I'm incompetent after that meeting.", 1),
        ("What if I completely blank during the presentation?", 2),
    ],
    3: [
        ("I haven't heard back about the job in three days.", 0),
        ("They're going to reject me because I haven't heard back yet.", 1),
        ("I just have this feeling something's going to go wrong today.", 2),
    ],
}

WORRY_FEEDBACK = {
    0: "That's something you can point to -- it already happened or is directly observable. Facts don't need reframing.",
    1: "That's a prediction dressed up as certainty. The mind treats it like a fact, but it's a guess about the future -- and guesses can be wrong.",
    2: "That's a worry: a vague sense of dread with no specific claim attached. Naming it as worry (not fact) takes some of its weight away.",
}

# Night Mind Reset (sleep). Each entry: the thought, and whether it's
# something actually actionable right this second (True) or something to
# park until morning (False). Deliberately mostly False, since almost
# nothing is truly actionable at bedtime -- the few True cases exist so
# the classification stays a real judgment call, not a foregone answer.
NIGHT_CONTROL_OPTIONS = ["YES -- I can handle this right now", "NO -- this can wait until tomorrow"]

NIGHT_BANKS = {
    1: [
        ("The room feels a little too warm.", True),
        ("My exam tomorrow is going to ruin everything.", False),
        ("I forgot to reply to a text from a friend today.", False),
    ],
    2: [
        ("I'm thirsty right now.", True),
        ("Tomorrow's meeting could go badly.", False),
        ("I might have left the stove on.", True),
    ],
    3: [
        ("My phone alarm might not be loud enough.", True),
        ("What if I say something awkward at tomorrow's event?", False),
        ("I never finished today's to-do list.", False),
    ],
}

# Urge Breaker (digital detox). Each entry: a short trigger + feeling
# scenario, four possible next moves, and the index of the one that
# actually creates a delay and a replacement behavior (per the "urge
# surfing" mechanism) rather than a disguised way of giving in anyway.
URGE_BANKS = {
    1: [
        ("You're bored and your hand is already reaching for your phone to check social media.",
         ["Open the app for just one minute", "Stand up and drink a glass of water first",
          "Check notifications quickly, then decide", "Scroll for a bit to relax"], 1),
        ("You're avoiding a task and keep unlocking your phone out of habit.",
         ["Put the phone in another room and return to the task", "Just check one app first",
          "See what's new, then get back to it", "Reply to messages, then start the task"], 0),
    ],
    2: [
        ("A notification popped up and now you feel a pull to check everything else too.",
         ["Read that one notification and nothing else, then set the phone face-down",
          "Since it's already open, scan a couple more apps", "Clear all notifications first",
          "Reply to it later tonight when you have more time"], 0),
        ("You're stressed about something else and scrolling feels like it would help.",
         ["A short walk, then reassess how you feel", "Scroll for five minutes to decompress",
          "Watch a few short videos to unwind", "Message a friend about how stressed you are"], 0),
    ],
    3: [
        ("You feel restless and a little lonely, and social media seems like the fastest fix.",
         ["Text one real person instead of opening the feed", "Open the app but only look at close friends' posts",
          "Post something to see who responds", "Check just for two minutes, then stop"], 0),
        ("You told yourself you'd only check the time, but you're still holding the phone.",
         ["Set the phone down and stretch for a minute", "Since it's already unlocked, glance at one more thing",
          "Check one app you've been curious about", "Look at the time again to be sure"], 0),
    ],
}


BANNED_GRATITUDE_WORDS = {
    "family", "friends", "health", "food", "home", "work", "life", "everything",
    "people", "things", "stuff", "day", "morning", "night", "good", "nice",
    "sleep", "coffee", "weather",
}


class BrainError(ValueError):
    """Raised for ownership/state/input failures; routes/brain.py maps this
    to an HTTP status just like the activity engine's ActivityError."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---- Exercise builders -----------------------------------------------------

def _seed_for(user_id: int, plan_id: int, day_number: int, attempt_index: int, kind: str) -> random.Random:
    return random.Random(f"{user_id}:{plan_id}:{day_number}:{attempt_index}:{kind}")


def _build_attention(rng: random.Random, tier: int) -> dict:
    stream_len = 10 + tier * 4
    letters = "ABCDE"
    target = rng.choice(letters)
    count = min(2 + tier, stream_len // 3)
    others = [c for c in letters if c != target]
    sequence = [target] * count
    sequence += [rng.choice(others) for _ in range(stream_len - count)]
    rng.shuffle(sequence)
    return {
        "kind": "attention",
        "title": KIND_TITLES["attention"],
        "instructions": KIND_INSTRUCTIONS["attention"],
        "difficulty_tier": tier,
        "input": {
            "sequence": sequence,
            "target": target,
            "question": f"How many times does the letter {target} appear?",
        },
        "answer": count,
        "scoring": {"max_score": 1, "expected_type": "int"},
    }


def _build_working_memory(rng: random.Random, tier: int) -> dict:
    n_items = 4 + tier
    items = rng.sample(WORKING_MEMORY_POOL, n_items)
    probe_index = rng.randrange(0, n_items - 1)
    probe = items[probe_index]
    answer = items[probe_index + 1]
    return {
        "kind": "working_memory",
        "title": KIND_TITLES["working_memory"],
        "instructions": KIND_INSTRUCTIONS["working_memory"],
        "difficulty_tier": tier,
        "input": {
            "items": items,
            "question": f"Which word came right after \"{probe}\" in the list?",
        },
        "answer": answer,
        "scoring": {"max_score": 1, "expected_type": "text"},
    }


def _build_updating(rng: random.Random, tier: int) -> dict:
    n = 4 + tier
    low, high = UPDATING_NUMBER_RANGE
    sequence = rng.sample(range(low, high + 1), n)
    return {
        "kind": "updating",
        "title": KIND_TITLES["updating"],
        "instructions": KIND_INSTRUCTIONS["updating"],
        "difficulty_tier": tier,
        "input": {
            "sequence": sequence,
            "question": "What was the largest number in the sequence?",
        },
        "answer": max(sequence),
        "scoring": {"max_score": 1, "expected_type": "int"},
    }


def _build_reframe(rng: random.Random, tier: int) -> dict:
    bank = REFRAME_BANKS[tier]
    situation, thought, options, answer = rng.choice(bank)
    return {
        "kind": "reframe",
        "title": KIND_TITLES["reframe"],
        "instructions": KIND_INSTRUCTIONS["reframe"],
        "difficulty_tier": tier,
        "input": {
            "situation": situation,
            "thought": thought,
            "options": options,
            "question": "Which is the most balanced, evidence-based alternative?",
        },
        "answer": answer,
        "scoring": {"max_score": 1, "expected_type": "index"},
    }


def _build_gratitude_scan(rng: random.Random, tier: int) -> dict:
    min_items = 2 + tier
    min_words = 3 + tier
    return {
        "kind": "gratitude_scan",
        "title": KIND_TITLES["gratitude_scan"],
        "instructions": KIND_INSTRUCTIONS["gratitude_scan"],
        "difficulty_tier": tier,
        "input": {
            "question": "List the specific things you appreciated in the last 24 hours, one per line.",
            "min_items": min_items,
            "min_words": min_words,
        },
        "answer": None,  # scored by heuristics, never a fixed value
        "scoring": {"max_score": min_items, "expected_type": "list"},
    }


def _build_worry_reality(rng: random.Random, tier: int) -> dict:
    bank = WORRY_BANKS[tier]
    thought, answer = rng.choice(bank)
    return {
        "kind": "worry_reality",
        "title": KIND_TITLES["worry_reality"],
        "instructions": KIND_INSTRUCTIONS["worry_reality"],
        "difficulty_tier": tier,
        "input": {
            "thought": thought,
            "options": WORRY_CLASSIFICATION_OPTIONS,
            "question": "What kind of thought is this?",
        },
        "answer": answer,
        "scoring": {"max_score": 1, "expected_type": "index"},
    }


def _build_night_reset(rng: random.Random, tier: int) -> dict:
    bank = NIGHT_BANKS[tier]
    thought, controllable_now = rng.choice(bank)
    answer = 0 if controllable_now else 1
    return {
        "kind": "night_reset",
        "title": KIND_TITLES["night_reset"],
        "instructions": KIND_INSTRUCTIONS["night_reset"],
        "difficulty_tier": tier,
        "input": {
            "thought": thought,
            "options": NIGHT_CONTROL_OPTIONS,
            "question": "Can you act on this right now?",
        },
        "answer": answer,
        "scoring": {"max_score": 1, "expected_type": "index"},
    }


def _build_urge_breaker(rng: random.Random, tier: int) -> dict:
    bank = URGE_BANKS[tier]
    scenario, options, answer = rng.choice(bank)
    return {
        "kind": "urge_breaker",
        "title": KIND_TITLES["urge_breaker"],
        "instructions": KIND_INSTRUCTIONS["urge_breaker"],
        "difficulty_tier": tier,
        "input": {
            "scenario": scenario,
            "options": options,
            "question": "What's the most helpful move for the next 5 minutes?",
        },
        "answer": answer,
        "scoring": {"max_score": 1, "expected_type": "index"},
    }


BUILDERS = {
    "attention": _build_attention,
    "working_memory": _build_working_memory,
    "updating": _build_updating,
    "reframe": _build_reframe,
    "gratitude_scan": _build_gratitude_scan,
    "worry_reality": _build_worry_reality,
    "night_reset": _build_night_reset,
    "urge_breaker": _build_urge_breaker,
}


# ---- Scoring ----------------------------------------------------------------

def _clean_text_response(response) -> str:
    return " ".join(str(response or "").split()).lower()


def _split_list_response(response) -> list[str]:
    text = str(response or "")
    lines = [ln.strip().lstrip("-•·0123456789.)").strip() for ln in text.replace(";", "\n").splitlines()]
    return [ln for ln in lines if ln]


def score_exercise(prompt: dict, response) -> dict:
    """Scores a submitted response against the stored prompt. Never trusts
    a client-supplied answer -- the ground truth lives in `prompt`."""
    kind = prompt["kind"]
    max_score = prompt["scoring"]["max_score"]

    if kind == "attention":
        try:
            given = int(response)
        except (TypeError, ValueError):
            given = None
        correct = given == prompt["answer"]
        score = max_score if correct else 0
        feedback = (
            "Sharp focus -- you tracked the stream without dropping the target."
            if correct else
            f"The target appeared {prompt['answer']} times. Scan each letter deliberately next round."
        )
        return _result(kind, score, max_score, correct, str(prompt["answer"]), feedback)

    if kind == "working_memory":
        given = _clean_text_response(response)
        answer = _clean_text_response(prompt["answer"])
        correct = bool(answer) and given == answer
        score = max_score if correct else 0
        feedback = (
            "Recall locked in -- the list stayed in working memory."
            if correct else
            f"The word that came right after was \"{prompt['answer']}\". "
            "Chunk the list into a small story next time."
        )
        return _result(kind, score, max_score, correct, str(prompt["answer"]), feedback)

    if kind == "updating":
        try:
            given = int(response)
        except (TypeError, ValueError):
            given = None
        correct = given == prompt["answer"]
        score = max_score if correct else 0
        feedback = (
            "Correct -- you kept the largest value and dropped the noise."
            if correct else
            f"The largest number was {prompt['answer']}. Keep only one number in mind as you go."
        )
        return _result(kind, score, max_score, correct, str(prompt["answer"]), feedback)

    if kind == "reframe":
        try:
            given = int(response)
        except (TypeError, ValueError):
            given = None
        correct = given == prompt["answer"]
        score = max_score if correct else 0
        options = prompt["input"]["options"]
        feedback = (
            "That's the framing the evidence supports -- specific, not all-or-nothing."
            if correct else
            f"The balanced option was: \"{options[prompt['answer']]}\""
        )
        return _result(kind, score, max_score, correct, options[prompt["answer"]], feedback)

    if kind == "worry_reality":
        try:
            given = int(response)
        except (TypeError, ValueError):
            given = None
        correct = given == prompt["answer"]
        score = max_score if correct else 0
        options = prompt["input"]["options"]
        feedback = (
            WORRY_FEEDBACK.get(prompt["answer"], "That's the accurate read on this thought.")
            if correct else
            f"This was really {options[prompt['answer']].lower()}. " + WORRY_FEEDBACK.get(prompt["answer"], "")
        )
        return _result(kind, score, max_score, correct, options[prompt["answer"]], feedback)

    if kind == "night_reset":
        try:
            given = int(response)
        except (TypeError, ValueError):
            given = None
        correct = given == prompt["answer"]
        score = max_score if correct else 0
        options = prompt["input"]["options"]
        if prompt["answer"] == 0:
            resolution = "Handle it in one small step, then let it go for the night."
        else:
            resolution = "Park it: \"I'll deal with this tomorrow.\" Then let your attention settle."
        feedback = resolution if correct else f"The steadier read here was: {options[prompt['answer']]}. {resolution}"
        return _result(kind, score, max_score, correct, options[prompt["answer"]], feedback)

    if kind == "urge_breaker":
        try:
            given = int(response)
        except (TypeError, ValueError):
            given = None
        correct = given == prompt["answer"]
        score = max_score if correct else 0
        options = prompt["input"]["options"]
        feedback = (
            "That creates real distance from the urge instead of feeding it -- the pull fades faster than it feels like it will."
            if correct else
            f"The move that actually creates distance from the urge was: \"{options[prompt['answer']]}\". "
            "The others still feed the urge, just more slowly."
        )
        return _result(kind, score, max_score, correct, options[prompt["answer"]], feedback)

    if kind == "gratitude_scan":
        items = _split_list_response(response)
        unique_seen = set()
        passing = 0
        min_words = prompt["input"]["min_words"]
        for item in items:
            words = item.split()
            if len(words) < min_words:
                continue
            first_word = words[0].lower()
            if first_word in BANNED_GRATITUDE_WORDS:
                continue
            if item.lower() in unique_seen:
                continue
            unique_seen.add(item.lower())
            passing += 1
        score = passing
        correct = score >= max_score
        needed = max_score - score
        if correct:
            feedback = f"Done -- {score} specific, concrete appreciations. That kind of detail rewires attention over time."
        elif needed <= 0:
            feedback = "Good, but a few of those were generic. Aim for concrete, one-of-a-kind details."
        else:
            feedback = (f"Got {score}/{max_score} specific items. "
                        f"Try {needed} more with exact details (who, what, where, how it felt).")
        return _result(kind, score, max_score, correct, None, feedback)

    raise BrainError("Unknown exercise kind.")


def _result(kind, score, max_score, correct, answer_preview, feedback) -> dict:
    return {
        "kind": kind,
        "score": score,
        "max_score": max_score,
        "correct": bool(correct),
        "answer_preview": answer_preview,
        "feedback": feedback,
    }


def _next_tier(current_tier: int, score: int, max_score: int) -> int:
    if max_score <= 0:
        return current_tier
    ratio = score / max_score
    if ratio >= 0.8:
        return min(3, current_tier + 1)
    if ratio <= 0.4:
        return max(1, current_tier - 1)
    return current_tier


def _kind_for_plan(plan_type: str) -> str:
    """Every plan type gets exactly one, genuinely distinct recovery
    exercise (see PLAN_KIND_MAP) -- this replaced an earlier version that
    cycled through all five internal kinds by day number regardless of
    plan type, which meant a Sleep plan and a Digital Detox plan could
    surface the same exercise on the same day."""
    return PLAN_KIND_MAP.get(plan_type, "reframe")


# ---- Public API used by routes/brain.py -------------------------------------

def _current_day_for(plan: dict) -> int:
    started = datetime.fromisoformat(plan["started_at"])
    return min(plan["duration_days"], max(1, (datetime.now(timezone.utc) - started).days + 1))


def _redact(prompt: dict) -> dict:
    return {k: v for k, v in prompt.items() if k not in ("answer", "scoring")}


def get_or_create_today_exercise(user_id: int, plan_id: int, day_number: int):
    """Returns the day's issued exercise (public, answer-free) if the plan
    is active, or None when there's nothing to train on. Creates the
    issued row on first request for the day; reuses it unchanged until the
    user answers."""
    plan = get_recovery_plan(plan_id, user_id)
    if plan is None:
        raise BrainError("Recovery plan not found.", 404)
    if plan["status"] != "active":
        return None
    if not 1 <= day_number <= plan["duration_days"]:
        raise BrainError("Day is outside the plan.", 400)

    issued = get_issued_brain_exercise(user_id, plan_id, day_number)
    if issued is not None:
        return _to_public(issued, plan)

    last = get_latest_scored_brain_exercise(user_id, plan_id, day_number)
    attempt_index = count_scored_brain_exercises(user_id, plan_id, day_number)

    if last is not None:
        last_prompt = json.loads(last["prompt_json"])
        tier = _next_tier(last_prompt["difficulty_tier"], last["score"] or 0, last_prompt["scoring"]["max_score"])
    else:
        tier = min(3, max(1, plan["stage"] or 1))

    kind = _kind_for_plan(plan["plan_type"])
    rng = _seed_for(user_id, plan_id, day_number, attempt_index, kind)
    prompt = BUILDERS[kind](rng, tier)

    attempt_id = create_brain_exercise_attempt(
        user_id, plan_id, day_number, kind, json.dumps(prompt)
    )
    issued = {
        "id": attempt_id,
        "user_id": user_id,
        "day_number": day_number,
        "prompt_json": json.dumps(prompt),
        "exercise_kind": kind,
    }
    return _to_public(issued, plan)


def _to_public(attempt_row: dict, plan: dict) -> dict:
    prompt = json.loads(attempt_row["prompt_json"])
    last = get_latest_scored_brain_exercise(
        attempt_row["user_id"], plan["id"], attempt_row["day_number"]
    )
    public = {
        "attempt_id": attempt_row["id"],
        "day_number": attempt_row["day_number"],
        "plan_id": plan["id"],
        "plan_type": plan["plan_type"],
        "kind": prompt["kind"],
        "title": prompt["title"],
        "instructions": prompt["instructions"],
        "difficulty_tier": prompt["difficulty_tier"],
        "input": prompt["input"],
        "last": None,
    }
    if last is not None:
        last_prompt = json.loads(last["prompt_json"])
        public["last"] = {
            "score": last["score"] or 0,
            "max_score": last_prompt["scoring"]["max_score"],
            "tier": last_prompt["difficulty_tier"],
        }
    return public


def submit_attempt(user_id: int, attempt_id: int, response) -> dict:
    attempt = get_brain_exercise_attempt(attempt_id, user_id)
    if attempt is None:
        raise BrainError("Exercise not found.", 404)

    plan = get_recovery_plan(attempt["plan_id"], user_id)
    if plan is None:
        raise BrainError("Recovery plan not found.", 404)
    if plan["status"] != "active":
        raise BrainError("This plan is no longer active.", 400)

    prompt = json.loads(attempt["prompt_json"])

    # Idempotent resubmit: a double-click (or a reload) replays the
    # recorded result instead of creating a second attempt.
    if attempt["response_json"] is not None:
        recorded = score_exercise(prompt, json.loads(attempt["response_json"]))
        return _submit_result(attempt, plan, recorded)

    result = score_exercise(prompt, response)
    complete_brain_exercise_attempt(attempt_id, json.dumps(response, default=str), result["score"])
    attempt["score"] = result["score"]
    attempt["response_json"] = json.dumps(response, default=str)
    return _submit_result(attempt, plan, result)


def _submit_result(attempt: dict, plan: dict, result: dict) -> dict:
    prompt = json.loads(attempt["prompt_json"])
    progress = get_progress(attempt["user_id"], plan["id"])
    tier_after = _next_tier(prompt["difficulty_tier"], result["score"], result["max_score"])
    return {
        **result,
        "attempt_id": attempt["id"],
        "day_number": attempt["day_number"],
        "tier_after": tier_after,
        "streak": progress["streak"],
        "best_percent": progress["best_percent"],
        "next_available": progress["days"].get(str(attempt["day_number"]), {}).get("available", False),
    }


def get_progress(user_id: int, plan_id: int) -> dict:
    """Per-day state map for the plan plus streak and best-score summary.
    day state: 'todo' (nothing yet), 'issued' (an unanswered exercise is
    out), or 'done' (answered)."""
    plan = get_recovery_plan(plan_id, user_id)
    if plan is None:
        return {"days": {}, "streak": 0, "best_percent": 0, "best_score": 0, "best_max": 0}
    duration = plan["duration_days"]
    current_day = _current_day_for(plan)

    attempts = get_brain_exercises_for_plan(user_id, plan_id)
    scored_by_day: dict[int, list[dict]] = {}
    issued_days: set[int] = set()
    best_score, best_max = 0, 0
    for a in attempts:
        if a["response_json"] is not None:
            scored_by_day.setdefault(a["day_number"], []).append(a)
            prompt = json.loads(a["prompt_json"])
            if a["score"] and a["score"] > best_score:
                best_score = a["score"]
                best_max = prompt["scoring"]["max_score"]
        else:
            issued_days.add(a["day_number"])

    days: dict[str, dict] = {}
    for day in range(1, duration + 1):
        scored = scored_by_day.get(day, [])
        if scored:
            last = scored[-1]
            prompt = json.loads(last["prompt_json"])
            days[str(day)] = {
                "state": "done",
                "kind": last["exercise_kind"],
                "score": last["score"] or 0,
                "max_score": prompt["scoring"]["max_score"],
                "tier": prompt["difficulty_tier"],
                "available": day <= current_day,
            }
        elif day in issued_days:
            days[str(day)] = {
                "state": "issued", "kind": None, "score": None, "max_score": None,
                "tier": None, "available": day <= current_day,
            }
        else:
            days[str(day)] = {
                "state": "todo", "kind": None, "score": None, "max_score": None,
                "tier": None, "available": day <= current_day,
            }

    streak = 0
    start = current_day if current_day in scored_by_day else current_day - 1
    for day in range(start, 0, -1):
        if day in scored_by_day:
            streak += 1
        else:
            break
    best_percent = round(100 * best_score / best_max) if best_max else 0
    return {
        "days": days,
        "streak": streak,
        "best_percent": best_percent,
        "best_score": best_score,
        "best_max": best_max,
    }

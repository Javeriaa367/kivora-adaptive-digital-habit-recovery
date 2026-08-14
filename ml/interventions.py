
"""Evidence-informed intervention library.

Each mechanism maps to multiple intervention strategies. Interventions
include metadata used by the adaptive engine (category, difficulty,
tags, brief rationale, and source references). Texts are short user-
facing suggestions; rationale/source fields are for developer
documentation and auditability.

Sources used to inform categories (not copied text): Healthline articles
on social media and mental health, reducing screen time, sleep hygiene,
and phone-use reduction. See docs/interventions_sources.md for details.
"""

from typing import Dict, List

# Each intervention: id, text, category, difficulty (1 easy - 4 hard),
# tags, rationale, source_urls (developer doc). Keep prompts short (<200 chars).
INTERVENTION_LIBRARY: Dict[str, List[Dict]] = {
    "notification_triggered": [
        {
            "id": "notif_reduce_1",
            "text": "Turn off non-essential app notifications for the whole day.",
            "category": "notification_reduction",
            "difficulty": 1,
            "tags": ["notifications", "boundary"],
            "rationale": "Reduce external triggers that prompt checking.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "notif_batch_1",
            "text": "Check notifications only during two 15-minute windows today.",
            "category": "intentional_checking",
            "difficulty": 2,
            "tags": ["intentional_use", "scheduling"],
            "rationale": "Creates intentional windows to prevent reactive opens.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "notif_snooze_1",
            "text": "Snooze all social app alerts for work/study hours.",
            "category": "notification_reduction",
            "difficulty": 1,
            "tags": ["do_not_disturb", "schedule"],
            "rationale": "Block distractions during focus periods.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "automatic_checking": [
        {
            "id": "auto_location_1",
            "text": "Keep your phone in another room during focused periods.",
            "category": "environmental_barrier",
            "difficulty": 2,
            "tags": ["relocation", "friction"],
            "rationale": "Increase physical friction so habit loops break more easily.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "auto_pause_1",
            "text": "Pause for 10 seconds before opening any social app; name your urge.",
            "category": "urge_awareness",
            "difficulty": 1,
            "tags": ["mindfulness", "delay"],
            "rationale": "A short pause gives space to choose a different action.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "auto_logout_1",
            "text": "Log out of one social app and remove its quick access from your home screen.",
            "category": "friction_before_access",
            "difficulty": 2,
            "tags": ["logout", "reduce_reachability"],
            "rationale": "Extra steps reduce impulse-driven re-entry to apps.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "boredom": [
        {
            "id": "bored_replace_1",
            "text": "When you notice boredom, do a 10-minute replacement activity (walk, music, or call).",
            "category": "replacement_activity",
            "difficulty": 1,
            "tags": ["replacement", "boredom"],
            "rationale": "Provide a routed alternative so scrolling isn't the default.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "bored_plan_1",
            "text": "Plan two specific offline activities for likely boredom times today.",
            "category": "scheduled_offline",
            "difficulty": 1,
            "tags": ["planning", "scheduling"],
            "rationale": "Pre-commit to alternatives when risk periods occur.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "sleep_disruption": [
        {
            "id": "sleep_winddown_1",
            "text": "Start a 30-minute wind-down routine before bed with no screens.",
            "category": "bedtime_routine",
            "difficulty": 1,
            "tags": ["sleep_hygiene", "winddown"],
            "rationale": "Reduce evening stimulation to improve sleep onset.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "sleep_location_1",
            "text": "Charge your phone outside the bedroom overnight.",
            "category": "environmental_barrier",
            "difficulty": 2,
            "tags": ["relocation", "sleep"],
            "rationale": "Remove the phone as a nearby cue at bedtime.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "social_comparison": [
        {
            "id": "sc_feed_1",
            "text": "Unfollow or mute accounts that trigger comparison for one week.",
            "category": "intentional_feed",
            "difficulty": 2,
            "tags": ["curation", "boundary"],
            "rationale": "Reduce exposure to comparison triggers.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "sc_replace_1",
            "text": "After 10 minutes of browsing, write one real thing you value about yourself.",
            "category": "reflective_replacement",
            "difficulty": 1,
            "tags": ["reflection", "self_compassion"],
            "rationale": "Introduce counter-evidence to comparison moments.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "procrastination": [
        {
            "id": "pro_pomodoro_1",
            "text": "Use a 25-minute focused block on the avoided task, then a 5-minute break.",
            "category": "task_chunking",
            "difficulty": 1,
            "tags": ["pomodoro", "task_management"],
            "rationale": "Chunking reduces overwhelm that drives avoidance.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "cant_stop_once_started": [
        {
            "id": "cant_timer_1",
            "text": "Before opening social media, set a visible timer for 5 minutes and stick to it.",
            "category": "pre-commit_timer",
            "difficulty": 1,
            "tags": ["timer", "friction"],
            "rationale": "Pre-commit timers create micro-boundaries to prevent long sessions.",
            "source_urls": ["https://www.healthline.com/"],
        },
        {
            "id": "cant_block_1",
            "text": "Use an app blocker for 30 minutes when you start to browse, then review whether you achieved a goal.",
            "category": "session_limit",
            "difficulty": 2,
            "tags": ["blocker", "session_limit"],
            "rationale": "Limit session length to prevent runaway browsing.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "stress_triggered": [
        {
            "id": "stress_label_1",
            "text": "When the urge appears, name the stress (1-2 words) before acting.",
            "category": "urge_awareness",
            "difficulty": 1,
            "tags": ["labeling", "stress"],
            "rationale": "Labeling emotions reduces reactive behavior.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "emotional_avoidance": [
        {
            "id": "emo_sit_1",
            "text": "Sit with the feeling for one minute and describe it silently.",
            "category": "exposure_short",
            "difficulty": 1,
            "tags": ["mindfulness", "tolerance"],
            "rationale": "Brief exposure reduces avoidance-driven scrolling.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],

    "loneliness_driven": [
        {
            "id": "lonely_reach_1",
            "text": "Send a short message or call one person you know today.",
            "category": "social_replacement",
            "difficulty": 1,
            "tags": ["connection", "replacement"],
            "rationale": "Replace passive browsing with direct social contact.",
            "source_urls": ["https://www.healthline.com/"],
        },
    ],
}


def get_interventions_for_mechanism(mechanism: str):
    return INTERVENTION_LIBRARY.get(mechanism, [])


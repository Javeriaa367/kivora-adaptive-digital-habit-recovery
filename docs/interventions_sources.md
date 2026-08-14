## Intervention sources and developer notes

This document lists the high-level sources consulted to expand KIVORA's
intervention library and the mapping philosophy used. The content in
`ml/interventions.py` is original and does not copy source text; these
references were used to identify evidence-informed categories and
behavioral strategies.

Primary reference (used as a general, consumer-facing survey):

- Healthline: articles on social media and mental health; reducing
  screen time; phone-use reduction; and sleep hygiene.

Secondary guidance and rationale: general behavior-change literature
and widely used strategies such as stimulus control, implementation
intentions, habit-stacking, and graded exposure. Where KIVORA makes
any health-related claim, prefer qualified, evidence-informed phrasing
and avoid clinical diagnostic language.

Mapping philosophy
- Interventions are grouped under behavioral mechanisms (e.g.
  `notification_triggered`, `automatic_checking`). Each mechanism
  contains multiple candidate strategies varying in difficulty and
  category (environmental, cognitive, scheduling, replacement).
- The adaptive engine selects among candidates using real outcome
  signals (usefulness, completion, prior outcome), stage, relapse
  detection, and user-reported barriers.

Source links (developer reference)
- https://www.healthline.com/ (search: social media and mental health, reduce screen time, sleep hygiene)

Notes
- This is a living document. Add study references here when an
  intervention is tied to a peer-reviewed paper or guideline.

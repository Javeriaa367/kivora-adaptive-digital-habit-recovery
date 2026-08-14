import unittest
from ml.recovery_state import RecoveryState, InterventionHistoryItem
from ml.selector import select_next_intervention


class DummyState(RecoveryState):
    pass


class SelectorTests(unittest.TestCase):
    def test_different_mechanisms_choose_different_interventions(self):
        # Build states for two mechanisms
        s1 = RecoveryState(user_id=1)
        s1.primary_mechanism = "automatic_checking"
        s1.stage = 1

        s2 = RecoveryState(user_id=2)
        s2.primary_mechanism = "boredom"
        s2.stage = 1

        i1 = select_next_intervention(s1)
        i2 = select_next_intervention(s2)
        self.assertIsNotNone(i1)
        self.assertIsNotNone(i2)
        self.assertNotEqual(i1.get("id"), i2.get("id"))

    def test_failed_intervention_changes_selection(self):
        s = RecoveryState(user_id=3)
        s.primary_mechanism = "automatic_checking"
        s.stage = 1
        # simulate last tried intervention ineffective
        s.intervention_history = [InterventionHistoryItem("auto_location_1", "ineffective", 1, None)]
        choice = select_next_intervention(s)
        self.assertIsNotNone(choice)
        self.assertNotEqual(choice.get("id"), "auto_location_1")

    def test_successful_intervention_progresses(self):
        s = RecoveryState(user_id=4)
        s.primary_mechanism = "automatic_checking"
        s.stage = 1
        s.intervention_history = [InterventionHistoryItem("auto_location_1", "success", 5, None)]
        choice = select_next_intervention(s)
        self.assertIsNotNone(choice)
        # Expect a higher-difficulty candidate when previous succeeded
        self.assertTrue(choice.get("difficulty", 1) >= 1)

    def test_fatigue_leads_to_lower_burden(self):
        s = RecoveryState(user_id=5)
        s.primary_mechanism = "automatic_checking"
        s.stage = 2
        s.fatigue_score = 5.0
        choice = select_next_intervention(s)
        self.assertIsNotNone(choice)
        # With high fatigue, difficulty should be low
        self.assertTrue(choice.get("difficulty", 3) <= 2)

    def test_repetition_avoidance(self):
        s = RecoveryState(user_id=6)
        s.primary_mechanism = "notification_triggered"
        s.stage = 1
        s.intervention_history = [InterventionHistoryItem("notif_reduce_1", "ineffective", 1, None)]
        choice = select_next_intervention(s)
        self.assertIsNotNone(choice)
        self.assertNotEqual(choice.get("id"), "notif_reduce_1")


if __name__ == "__main__":
    unittest.main()

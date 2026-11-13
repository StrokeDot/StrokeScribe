"""Phase 6: characterize project-leaving decisions before extraction from Qt."""
import unittest
from unittest.mock import Mock

from project_lifecycle import resolve_project_leave


SAVE='save'
DISCARD='discard'
CANCEL='cancel'


class LeaveDecisionTests(unittest.TestCase):
    def decide(self, choice, dirty=True, automatic=False, saved=True):
        question=Mock(return_value=choice)
        save=Mock(return_value='project.strokescribe' if saved else None)
        result=resolve_project_leave(dirty,question,save,
                                     save_choice=SAVE,discard_choice=DISCARD,
                                     auto_discard=automatic)
        return result, question, save

    def test_clean_projects_never_prompt_or_save(self):
        result, question, save=self.decide(CANCEL,dirty=False)
        self.assertTrue(result)
        question.assert_not_called()
        save.assert_not_called()

    def test_user_can_cancel_close_or_project_replacement(self):
        result, question, save=self.decide(CANCEL)
        self.assertFalse(result)
        question.assert_called_once()
        save.assert_not_called()

    def test_successful_save_allows_leave_but_failed_or_cancelled_save_blocks(self):
        for saved in (True,False):
            with self.subTest(saved=saved):
                result, question, save=self.decide(SAVE,saved=saved)
                self.assertEqual(result,saved)
                save.assert_called_once()

    def test_discard_is_explicit_and_does_not_call_save(self):
        result, question, save=self.decide(DISCARD)
        self.assertTrue(result)
        question.assert_called_once()
        save.assert_not_called()

    def test_headless_test_optin_never_prompts(self):
        result, question, save=self.decide(CANCEL,automatic=True)
        self.assertTrue(result)
        question.assert_not_called()
        save.assert_not_called()

    def test_unexpected_response_fails_closed(self):
        result, _, save=self.decide('unknown')
        self.assertFalse(result)
        save.assert_not_called()


if __name__=='__main__':
    unittest.main(verbosity=2)

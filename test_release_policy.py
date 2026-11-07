"""Publishing must be explicit, from approved branches and from the tested commit."""
import unittest
from tools.release_policy import authorize_publish, ReleasePolicyError

MAIN = 'refs/heads/main'
EXPERIMENTAL = 'refs/heads/fix/svg-guide-coverage-experimental12'
A = 'a'*40
B = 'b'*40


class ReleasePolicyTests(unittest.TestCase):
    def test_allow_only_explicitly_approved_manual_release(self):
        for branch in (MAIN, EXPERIMENTAL):
            with self.subTest(branch=branch):
                self.assertTrue(authorize_publish('workflow_dispatch', branch, True, A, A, A))

    def test_refuse_publish_on_pull_request_push_or_unapproved_manual_run(self):
        cases=[
            ('push', MAIN, True),
            ('pull_request', MAIN, True),
            ('workflow_dispatch', MAIN, False),
            ('workflow_dispatch', 'refs/heads/safety/release-gates-phase3', True),
            ('workflow_dispatch', 'refs/heads/feature/my-work', True),
            ('workflow_dispatch', 'refs/tags/installer-0.5.3', True),
        ]
        for event, ref, requested in cases:
            with self.subTest(event=event, ref=ref, requested=requested):
                with self.assertRaises(ReleasePolicyError):
                    authorize_publish(event, ref, requested, A, A, A)

    def test_refuse_publish_if_linux_or_windows_tested_different_sha(self):
        for linux, windows in ((B, A),(A, B),(B, B),('', A),(A, '')):
            with self.subTest(linux=linux,windows=windows):
                with self.assertRaises(ReleasePolicyError):
                    authorize_publish('workflow_dispatch', MAIN, True, A, linux, windows)

    def test_refuse_invalid_or_non_boolean_publish_input(self):
        for publish in ('true','false','yes', 1, None, {}, []):
            with self.subTest(publish=publish):
                with self.assertRaises(ReleasePolicyError):
                    authorize_publish('workflow_dispatch', MAIN, publish, A, A, A)


if __name__ == '__main__':
    unittest.main(verbosity=2)

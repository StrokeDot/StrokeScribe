"""Phase 5: unattended previews must not open unsaved-project dialogs."""
import unittest
from tools.preview_environment import configure_preview_environment


class PreviewEnvironmentTests(unittest.TestCase):
    def test_offscreen_preview_sets_unattended_discard_only_for_preview(self):
        settings={'QT_QPA_PLATFORM': 'offscreen'}
        self.assertTrue(configure_preview_environment(settings))
        self.assertEqual(settings['STROKESCRIBE_TEST_AUTODISCARD'],'1')

    def test_real_desktop_never_enables_automatic_discard(self):
        for platform in ('windows','xcb','wayland','minimal'):
            with self.subTest(platform=platform):
                settings={'QT_QPA_PLATFORM':platform}
                self.assertFalse(configure_preview_environment(settings))
                self.assertNotIn('STROKESCRIBE_TEST_AUTODISCARD',settings)

    def test_existing_setting_is_respected_for_manual_debugging(self):
        settings={'QT_QPA_PLATFORM':'offscreen','STROKESCRIBE_TEST_AUTODISCARD':'0'}
        self.assertTrue(configure_preview_environment(settings))
        self.assertEqual(settings['STROKESCRIBE_TEST_AUTODISCARD'],'0')


if __name__=='__main__':
    unittest.main(verbosity=2)

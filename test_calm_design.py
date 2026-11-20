"""exp.11 (the user's design videos): one calm accent, no purple blocks or gradients."""
import unittest
from pathlib import Path

import theme


class CalmDesignTests(unittest.TestCase):
    def test_open_panel_is_not_an_accent_block(self):
        for name in theme.PALETTES:
            css = theme.stylesheet(name, Path('assets'))
            rule = next(line for line in css.splitlines() if 'railButton:checked' in line)
            self.assertNotIn(theme.PALETTES[name]['accent'], rule)

    def test_no_accent_gradient_on_the_new_project_tile(self):
        source = Path('home_screen.py').read_text(encoding='utf-8')
        self.assertNotIn("c('accent_a')", source)

    def test_timeline_clips_are_muted(self):
        from PySide6.QtGui import QColor
        for name, c in theme.PALETTES.items():
            for key in ('draw', 'paint', 'hold', 'erase'):
                q = QColor(c[key])
                vivid = q.hsvSaturation() * q.value() / 255     # the old neon purple: about 163
                self.assertLess(vivid, 120, (name, key))

    def test_bold_is_kept_for_the_main_action(self):
        css = theme.stylesheet('dark', Path('assets'))
        self.assertNotIn('font-weight: 600', css.split('QPushButton:hover')[0].split('QPushButton {')[1])
        primary = next(line for line in css.splitlines() if line.startswith('QPushButton#primary {'))
        self.assertIn('font-weight: 600', primary)


if __name__ == '__main__':
    unittest.main()

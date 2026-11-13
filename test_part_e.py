"""exp.58: Create Image keeps each tab's prompt and result, the Suggested prompt
button, the working animation and the result that waits on its own tab."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


@unittest.skipIf(SKIP, 'needs Qt')
class CreateImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get('STROKESCRIBE_CONFIG_DIR')
        os.environ['STROKESCRIBE_CONFIG_DIR'] = self.tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop('STROKESCRIBE_CONFIG_DIR', None)
        else:
            os.environ['STROKESCRIBE_CONFIG_DIR'] = self._old
        self.tmp.cleanup()

    def test_tabs_keep_prompt_and_result(self):
        from PySide6.QtGui import QImage, QColor
        from ai_models import Hardware
        from ai_workflows import LINE_ART_PROMPT
        from create_image_dialog import CreateImageDialog, GENERATE_PROMPT
        image = Path(self.tmp.name) / 'art.png'
        q = QImage(64, 48, QImage.Format.Format_RGB32); q.fill(QColor('white')); q.save(str(image))
        d = CreateImageDialog(None, str(image), lambda *a: None,
                              hardware=Hardware('NVIDIA RTX', 16., 32., True))
        try:
            # Your own words stay when you switch tabs; the button brings back the suggested prompt.
            d.prompt.setPlainText('my own words')
            d.set_task('generate')
            self.assertEqual(d.prompt.toPlainText(), GENERATE_PROMPT)
            d.set_task('lineart')
            self.assertEqual(d.prompt.toPlainText(), 'my own words')
            d.suggested_button.click()
            self.assertEqual(d.prompt.toPlainText(), LINE_ART_PROMPT)
            # Working: the animation is drawn in the result well.
            d.set_task('generate')
            d.running_task = 'generate'; d.memory['generate'] = dict(prompt='a cup', source=None)
            d.work.update(percent=30, text='Creating… 30%', started=0.)
            d.paint_working()
            self.assertFalse(d.preview.pixmap().isNull())
            # Switch tabs while it works: the picture waits on its own tab.
            d.set_task('lineart')
            out = Path(self.tmp.name) / 'made.png'
            q.save(str(out))
            d.on_result(str(out))
            self.assertIsNone(d.result_path)                          # not on the line-art tab
            self.assertIn('ready', d.status.text())
            d.set_task('generate')
            self.assertEqual(d.result_path, str(out))
            self.assertTrue(d.use_button.isEnabled())
            self.assertFalse(d.preview.pixmap().isNull())
        finally:
            d.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""AI image feature: model choice per PC, workflows, downloads, line-art tracing."""
import http.server
import math
import os
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import ai_engine
import ai_models
from ai_models import FIT_GOOD, FIT_NO, FIT_SLOW, Hardware
from ai_workflows import LINE_ART_PROMPT, build


def pc(vram, ram, gpu='NVIDIA GeForce RTX 4070 Ti SUPER'):
    return Hardware(gpu if vram else None, vram, ram, bool(vram))


class ModelChoiceTests(unittest.TestCase):
    def test_registry_is_consistent(self):
        names = set()
        for m in ai_models.MODELS:
            sizes = [v.min_vram_gb for v in m.variants]
            self.assertEqual(sizes, sorted(sizes, reverse=True), m.id)
            for f in [v.diffusion for v in m.variants] + list(m.shared) + list(m.low_ram_shared):
                self.assertTrue(f.url.startswith('https://huggingface.co/'), f.url)
                self.assertIn('/resolve/main/', f.url)
                self.assertGreater(f.size, 1e8)
                self.assertIn(f.folder, ('diffusion_models', 'text_encoders', 'vae', 'loras'))
                names.add((f.folder, f.name))
            for v in m.variants:
                self.assertEqual(v.loader == 'gguf', v.diffusion.name.endswith('.gguf'))
        self.assertGreater(len(names), 15)
        self.assertEqual({m.license for m in ai_models.MODELS if not m.needs_acceptance}, {'Apache 2.0'})
        self.assertTrue(ai_models.FLUX2_DEV.needs_acceptance)

    def test_versions_follow_the_graphics_card(self):
        q, k, d = ai_models.QWEN_EDIT, ai_models.FLUX2_KLEIN, ai_models.FLUX2_DEV
        sixteen = pc(16, 32)
        self.assertEqual(ai_models.choose_variant(q, sixteen), (q.variants[2], FIT_GOOD))     # Q4_K_M
        self.assertEqual(ai_models.choose_variant(k, sixteen), (k.variants[0], FIT_GOOD))     # full
        variant, fit = ai_models.choose_variant(d, sixteen)
        self.assertEqual((variant.id, fit), ('q3', FIT_SLOW))                                 # RAM < 64
        twelve = pc(12, 32, 'NVIDIA GeForce RTX 4070 Ti')
        self.assertEqual(ai_models.choose_variant(q, twelve)[0].id, 'q4_0')
        self.assertEqual(ai_models.choose_variant(k, twelve)[0].id, 'bf16')
        self.assertEqual(ai_models.choose_variant(q, pc(24, 64))[0].id, 'fp8')
        self.assertEqual(ai_models.choose_variant(d, pc(48, 128)), (d.variants[0], FIT_GOOD))
        self.assertEqual(ai_models.choose_variant(k, pc(8, 16))[0].id, 'fp8')
        self.assertEqual(ai_models.choose_variant(q, pc(None, 64))[1], FIT_NO)
        self.assertEqual(ai_models.choose_variant(d, pc(16, 16))[1], FIT_NO)                  # too little RAM
        # Low RAM swaps FLUX.2 [dev]'s text encoder for the smaller one.
        low = d.files(d.variants[3], 32)
        self.assertIn(ai_models.DEV_TEXT_SMALL, low)
        self.assertIn(ai_models.DEV_TEXT, d.files(d.variants[3], 64))

    def test_workflows_are_complete_graphs(self):
        for model in ai_models.MODELS:
            for variant in model.variants:
                for image in ((None, 'in.png') if 'generate' in model.tasks else ('in.png',)):
                    g = build(model, variant, LINE_ART_PROMPT, 123, image_name=image, ram_gb=64)
                    types = {n['class_type'] for n in g.values()}
                    self.assertIn('SaveImage', types)
                    self.assertEqual('LoadImage' in types, bool(image))
                    self.assertIn('UnetLoaderGGUF' if variant.loader == 'gguf' else 'UNETLoader', types)
                    for node in g.values():
                        for value in node['inputs'].values():
                            if isinstance(value, list):
                                self.assertIn(value[0], g, f'{model.id} dangling link')
        with self.assertRaises(ValueError):
            build(ai_models.QWEN_EDIT, ai_models.QWEN_EDIT.variants[0], 'x', 1)

    def test_settings_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['STROKESCRIBE_CONFIG_DIR'] = tmp
            try:
                s = ai_engine.load_settings()
                s['root'] = str(Path(tmp) / 'engine')
                ai_engine.save_settings(s)
                paths = ai_engine.Paths()
                self.assertEqual(paths.root, Path(tmp) / 'engine')
                self.assertFalse(paths.engine_installed())
                f = ai_models.FLUX2_VAE
                self.assertEqual(paths.model_path(f), paths.models / 'vae' / 'flux2-vae.safetensors')
                self.assertFalse(paths.has_files([f]))
            finally:
                del os.environ['STROKESCRIBE_CONFIG_DIR']


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    payload = bytes(range(256)) * 4000
    fail_after = None

    def do_GET(self):
        start = 0
        header = self.headers.get('Range')
        if header:
            start = int(header.split('=')[1].split('-')[0])
            self.send_response(206)
        else:
            self.send_response(200)
        body = self.payload[start:]
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        limit = RangeHandler.fail_after
        if limit is not None:
            RangeHandler.fail_after = None
            self.wfile.write(body[:limit])
            return
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DownloadTests(unittest.TestCase):
    def test_download_resumes_and_checks_size(self):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), RangeHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_address[1]}/file.bin'
        size = len(RangeHandler.payload)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'models' / 'file.bin'
                RangeHandler.fail_after = 300000            # connection drops part way
                with self.assertRaises(RuntimeError):
                    ai_engine.download(url, target, size)
                part = target.with_name('file.bin.part')
                self.assertEqual(part.stat().st_size, 300000)
                seen = []
                ai_engine.download(url, target, size, progress=lambda d, t: seen.append(d))
                self.assertEqual(target.read_bytes(), RangeHandler.payload)
                self.assertFalse(part.exists())
                self.assertGreater(seen[0], 300000)          # continued, not restarted
                ai_engine.download(url, target, size)        # already there: no-op
                with self.assertRaises(ai_engine.Cancelled):
                    ai_engine.download(url, Path(tmp) / 'b.bin', size, cancelled=lambda: True)
        finally:
            server.shutdown()


def drawing_pair(dx=0, dy=0, s=1.):
    w, h = 640, 480
    colour = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(colour)
    d.rounded_rectangle((80, 60, 560, 420), 30, fill=(120, 80, 40, 255))
    d.rectangle((120, 100, 420, 380), fill=(30, 30, 30, 255))
    d.ellipse((450, 130, 530, 210), fill=(200, 200, 200, 255))
    lines = Image.new('RGB', (w, h), 'white')
    e = ImageDraw.Draw(lines)
    T = lambda x, y: ((x - 320) * s + 320 + dx, (y - 240) * s + 240 + dy)
    e.rounded_rectangle((*T(80, 60), *T(560, 420)), 30, outline='black', width=4)
    e.rectangle((*T(120, 100), *T(420, 380)), outline='black', width=4)
    e.ellipse((*T(450, 130), *T(530, 210)), outline='black', width=4)
    return colour, lines


class LineGuideTests(unittest.TestCase):
    def test_shifted_ai_drawing_is_lined_up(self):
        import cv2
        from ai_lineart import guide_image
        colour, truth = drawing_pair()
        truth = np.asarray(truth.convert('L')) < 128
        for dx, dy, s in ((0, 0, 1.), (14, -9, 1.04), (-20, 10, .97), (30, 20, 1.06)):
            _, moved = drawing_pair(dx, dy, s)
            guide, score = guide_image(colour, moved.resize((900, 675)))
            self.assertEqual(guide.size, colour.size)
            self.assertGreater(score, .9)
            ink = np.asarray(guide.convert('L')) < 128
            near = cv2.dilate(ink.astype(np.uint8), np.ones((7, 7))) > 0
            self.assertGreater((near & truth).sum() / truth.sum(), .97, (dx, dy, s))

    def test_line_drawing_becomes_one_stroke_per_line(self):
        from ai_lineart import guide_image
        from lineart import line_drawing_strokes
        colour, lines = drawing_pair()
        guide, _ = guide_image(colour, lines)
        strokes, outlines = line_drawing_strokes(guide, 'medium')
        self.assertEqual(outlines, 1)                     # the artwork silhouette
        inner = strokes[outlines:]
        # Screen rectangle and dial: each one long closed-ish stroke.
        ring = [s for s in inner if all(abs(math.dist(p, (490, 170)) - 40) < 6 for p in s)]
        self.assertTrue(ring)
        self.assertLess(len(inner), 8)


@unittest.skipIf(os.environ.get('STROKESCRIBE_SKIP_QT') == '1', 'needs Qt')
class CreateImageWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['STROKESCRIBE_CONFIG_DIR'] = self.tmp.name
        s = ai_engine.load_settings()
        s['root'] = str(Path(self.tmp.name) / 'engine')
        ai_engine.save_settings(s)

    def tearDown(self):
        del os.environ['STROKESCRIBE_CONFIG_DIR']
        self.tmp.cleanup()

    def test_window_guides_through_setup(self):
        from create_image_dialog import CreateImageDialog
        image = Path(self.tmp.name) / 'art.png'
        drawing_pair()[0].save(image)
        used = []
        dialog = CreateImageDialog(None, str(image), lambda *a: used.append(a),
                                   hardware=pc(16, 32))
        try:
            self.assertEqual(dialog.task, 'lineart')
            self.assertIn('Qwen-Image-Edit', dialog.model_box.currentText())
            self.assertIn('Fits your PC', dialog.model_box.currentText())
            self.assertFalse(dialog.generate_button.isEnabled())      # engine not installed
            self.assertTrue(dialog.install_button.isVisibleTo(dialog))
            self.assertIn('Q4_K_M', dialog.download_button.text())
            self.assertIn('23.7 GB', dialog.download_button.text())   # model + text encoder + VAE + LoRA
            self.assertEqual(dialog.prompt.toPlainText(), LINE_ART_PROMPT)
            dialog.set_task('generate')
            names = [dialog.model_box.itemText(i) for i in range(dialog.model_box.count())]
            self.assertEqual(len(names), 2)
            self.assertFalse(any('Qwen' in n for n in names))         # editor only
            dialog.model_box.setCurrentIndex(
                next(i for i, n in enumerate(names) if 'dev' in n))
            self.assertTrue(dialog.accept_license.isVisibleTo(dialog))
            self.assertFalse(dialog.download_button.isEnabled())      # license first
            dialog.accept_license.setChecked(True)
            self.assertTrue(dialog.download_button.isEnabled())
            self.assertIn('flux2_dev', ai_engine.load_settings()['accepted_licenses'])
            # Version override is remembered.
            dialog.variant_box.setCurrentIndex(dialog.variant_box.findData('q2'))
            self.assertEqual(dialog.variant().id, 'q2')
            self.assertEqual(ai_engine.load_settings()['variant_override']['flux2_dev'], 'q2')
            # A finished result can be used.
            out = Path(self.tmp.name) / 'result.png'
            drawing_pair()[1].save(out)
            dialog.set_task('lineart')
            dialog.on_result(str(out))
            self.assertTrue(dialog.use_button.isEnabled())
            dialog.use()
            self.assertEqual(used, [('lineart', str(out), str(image))])
        finally:
            dialog.close()

    def test_main_window_traces_a_line_drawing(self):
        from app import Window
        colour, lines = drawing_pair(12, -8, 1.03)
        image = Path(self.tmp.name) / 'colour.png'; colour.save(image)
        guide = Path(self.tmp.name) / 'lines.png'; lines.save(guide)
        w = Window()
        try:
            self.assertTrue(hasattr(w, 'create_image_button'))
            self.assertTrue(hasattr(w, 'own_lines_button'))
            w.source_type.setCurrentIndex(1)
            w.build_image(str(image), line_guide=str(guide))
            w.builder.wait(60000)
            self.app.processEvents()
            self.assertTrue(w.builder.success, w.builder.failed_message)
            self.assertIsNotNone(w.image_result)
            self.assertGreater(getattr(w.drawing, 'line_guide_score', 0), .8)
            self.assertTrue(any('AI line drawing' in x for x in w.drawing.warnings))
            self.assertEqual(w.image_guide, str(guide))
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)

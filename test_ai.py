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
                self.assertIn(f.folder, ('diffusion_models', 'text_encoders', 'vae', 'loras', 'checkpoints'))
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

    def test_sound_model(self):
        from ai_workflows import SOUND_PROMPTS
        s = ai_models.STABLE_AUDIO_SFX
        self.assertTrue(s.needs_acceptance)
        self.assertEqual(ai_models.choose_variant(s, pc(None, 16))[1], ai_models.FIT_SLOW)  # no GPU: still runs
        self.assertEqual(ai_models.choose_variant(s, pc(12, 32))[1], FIT_GOOD)
        self.assertEqual(ai_models.choose_variant(s, pc(12, 4))[1], ai_models.FIT_NO)
        self.assertLess(ai_models.download_size(s, s.variants[0]), 4e9)
        g = build(s, s.variants[0], SOUND_PROMPTS['Pencil'], 5, seconds=7)
        types = {n['class_type'] for n in g.values()}
        self.assertTrue({'CheckpointLoaderSimple', 'EmptyLatentAudio', 'VAEDecodeAudio', 'SaveAudio'} <= types)
        self.assertEqual(g['5']['inputs']['seconds'], 7.)
        for node in g.values():
            for value in node['inputs'].values():
                if isinstance(value, list):
                    self.assertIn(value[0], g)

    def test_workflows_are_complete_graphs(self):
        for model in ai_models.MODELS:
            if 'sound' in model.tasks:
                continue
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
    slow = 0.
    slow_start = None
    requests = []

    def do_GET(self):
        start, end = 0, None
        header = self.headers.get('Range')
        if header:
            first, last = header.split('=')[1].split('-')
            start = int(first); end = int(last) if last else None
            self.send_response(206)
        else:
            self.send_response(200)
        RangeHandler.requests.append(header)
        body = self.payload[start:None if end is None else end + 1]
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        limit = RangeHandler.fail_after
        if limit is not None:
            RangeHandler.fail_after = None
            self.wfile.write(body[:limit])
            return
        if RangeHandler.slow_start is not None and start == RangeHandler.slow_start:
            import time as _t
            for k in range(0, len(body), 4096):     # one very slow piece
                _t.sleep(.05)
                try:
                    self.wfile.write(body[k:k + 4096])
                except OSError:
                    return
            return
        if RangeHandler.slow:
            import time as _t
            for k in range(0, len(body), 4096):
                _t.sleep(RangeHandler.slow)
                try:
                    self.wfile.write(body[k:k + 4096])
                except OSError:
                    return
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


class ParallelDownloadTests(unittest.TestCase):
    """Big model files: several connections at once, resumable pieces, quick Cancel."""

    def setUp(self):
        self.old = (ai_engine.SEGMENT, ai_engine.PARALLEL_FROM, ai_engine.BLOCK)
        ai_engine.SEGMENT, ai_engine.PARALLEL_FROM, ai_engine.BLOCK = 64 << 10, 0, 16 << 10
        RangeHandler.slow = 0.; RangeHandler.fail_after = None; RangeHandler.requests = []
        RangeHandler.slow_start = None
        self.old_split = ai_engine.MIN_SPLIT; ai_engine.MIN_SPLIT = 16 << 10
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), RangeHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/file.bin'
        self.size = len(RangeHandler.payload)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        ai_engine.SEGMENT, ai_engine.PARALLEL_FROM, ai_engine.BLOCK = self.old
        ai_engine.MIN_SPLIT = self.old_split
        RangeHandler.slow = 0.; RangeHandler.slow_start = None
        self.server.shutdown()
        self.tmp.cleanup()

    def test_pieces_over_several_connections(self):
        target = Path(self.tmp.name) / 'a.bin'
        seen = []
        ai_engine.download(self.url, target, self.size, progress=lambda d, t: seen.append(d))
        self.assertEqual(target.read_bytes(), RangeHandler.payload)
        self.assertEqual(seen[-1], self.size)
        pieces = [r for r in RangeHandler.requests if r and r != 'bytes=0-0']
        self.assertGreaterEqual(len(pieces), self.size // (64 << 10))
        self.assertFalse(target.with_name('a.bin.part.json').exists())

    def test_cut_piece_is_fetched_again(self):
        target = Path(self.tmp.name) / 'c.bin'
        RangeHandler.fail_after = 1000          # the first connection drops part way
        ai_engine.download(self.url, target, self.size)
        self.assertEqual(target.read_bytes(), RangeHandler.payload)

    def test_cancel_is_quick_and_resumes(self):
        import time as _t
        target = Path(self.tmp.name) / 'b.bin'
        RangeHandler.slow = .05                  # a slow server
        began = _t.time()
        stop_at = began + .8
        with self.assertRaises(ai_engine.Cancelled):
            ai_engine.download(self.url, target, self.size, cancelled=lambda: _t.time() > stop_at)
        self.assertLess(_t.time() - began, 5.)   # stops within a few seconds
        sidecar = target.with_name('b.bin.part.json')
        self.assertTrue(sidecar.exists())
        RangeHandler.slow = 0.
        RangeHandler.requests = []
        ai_engine.download(self.url, target, self.size)
        self.assertEqual(target.read_bytes(), RangeHandler.payload)

    def test_slow_piece_is_shared(self):
        import time as _t
        target = Path(self.tmp.name) / 'e.bin'
        ai_engine.SEGMENT = 512 << 10                # 2 pieces; the second one is very slow
        RangeHandler.slow_start = 512 << 10
        began = _t.time()
        ai_engine.download(self.url, target, self.size, connections=4)
        self.assertEqual(target.read_bytes(), RangeHandler.payload)
        # Alone, the slow piece would take about 6 s; shared with the idle connections it is much quicker.
        self.assertLess(_t.time() - began, 4.)

    def test_old_single_download_continues(self):
        target = Path(self.tmp.name) / 'd.bin'
        part = target.with_name('d.bin.part')
        part.write_bytes(RangeHandler.payload[:300000])          # left by an older version
        ai_engine.download(self.url, target, self.size)
        self.assertEqual(target.read_bytes(), RangeHandler.payload)
        asked = [r for r in RangeHandler.requests if r and r != 'bytes=0-0']
        self.assertFalse(any(r.startswith('bytes=0-') for r in asked))   # the start was not fetched again


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
        import library
        ls = library.load_settings(); ls['root'] = str(Path(self.tmp.name) / 'Library')
        library.save_settings(ls)

    def tearDown(self):
        del os.environ['STROKESCRIBE_CONFIG_DIR']
        self.tmp.cleanup()

    def test_ai_memory_is_released_after_result_error_and_cancel(self):
        from unittest.mock import Mock
        from create_image_dialog import AIWorker
        for outcome in ('success', 'error', 'cancel'):
            with self.subTest(outcome=outcome):
                engine = Mock()
                engine.percent = None
                engine.run.return_value = str(Path(self.tmp.name) / 'generated.png')
                if outcome == 'error':
                    engine.run.side_effect = RuntimeError('bad model')
                if outcome == 'cancel':
                    engine.run.side_effect = ai_engine.Cancelled('Cancelled.')
                worker = AIWorker('generate')
                ready = []
                worker.done.connect(ready.append)
                if outcome == 'success':
                    worker._generate(engine, {}, None)
                    self.assertEqual(ready, [str(Path(self.tmp.name) / 'generated.png')])
                else:
                    with self.assertRaisesRegex(Exception, 'bad model|Cancelled'):
                        worker._generate(engine, {}, None)
                    self.assertEqual(ready, [])
                engine.stop.assert_called_once()

    def test_keeping_ai_loaded_is_explicit_opt_in(self):
        from unittest.mock import Mock
        from create_image_dialog import AIWorker, CreateImageDialog
        dialog = CreateImageDialog(None, None, hardware=pc(16, 64))
        try:
            self.assertTrue(dialog.release_ai_memory.isChecked())
            dialog.release_ai_memory.setChecked(False)
            self.assertFalse(ai_engine.load_settings()['release_ai_memory'])
            engine = Mock()
            engine.percent = None
            engine.run.return_value = 'generated.png'
            AIWorker('generate')._generate(engine, {}, None, release_after=False)
            engine.stop.assert_not_called()
        finally:
            dialog.close()

    def test_created_pictures_are_kept_in_library(self):
        import time as _t
        import library
        from create_image_dialog import keep_in_library, picture_name
        settings = library.load_settings(); settings['root'] = str(Path(self.tmp.name) / 'Library')
        library.save_settings(settings)
        self.assertEqual(picture_name('lineart', 'A cat, reading a book! in the park with friends', _t.localtime(0))
                         [:31], 'AI line art - A cat reading a b')
        made = Path(self.tmp.name) / 'ComfyUI_00001_.png'
        drawing_pair()[0].save(made)
        kept = keep_in_library(made, 'generate', 'a lighthouse at night')
        self.assertTrue(Path(kept).is_file())
        self.assertEqual(Path(kept).parent, library.Library().folder('images'))
        self.assertTrue(Path(kept).name.startswith('AI picture - a lighthouse at night - '))
        names = [i.name for i in library.Library().items('images')]
        self.assertTrue(any(n.startswith('AI picture') for n in names))

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
            self.assertIn('Q4_K_M', dialog.variant_box.currentText())
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
            # The picture is drawn from its copy in the Library → Images (the engine folder is temporary).
            import library
            self.assertEqual(len(used), 1)
            kind, kept, original = used[0]
            self.assertEqual((kind, original), ('lineart', str(image)))
            self.assertEqual(Path(kept).parent, library.Library().folder('images'))
            self.assertEqual(Path(kept).read_bytes(), out.read_bytes())
        finally:
            dialog.close()

    def test_create_a_sound(self):
        import numpy as np
        import sound
        from create_image_dialog import CreateImageDialog
        from ai_workflows import SOUND_PROMPTS
        used = []
        dialog = CreateImageDialog(None, None, lambda *a: used.append(a), hardware=pc(None, 16), task='sound')
        try:
            self.assertEqual(dialog.task, 'sound')
            self.assertIn('Stable Audio 3', dialog.model_box.currentText())
            self.assertIn('slower', dialog.model_box.currentText())        # no graphics card: CPU
            self.assertEqual(dialog.prompt.toPlainText(), SOUND_PROMPTS['Pencil'])
            self.assertTrue(dialog.sound_for.isVisibleTo(dialog))
            self.assertFalse(dialog.size_box.isVisibleTo(dialog))
            self.assertIn('3.5 GB', dialog.download_button.text())
            self.assertFalse(dialog.download_button.isEnabled())             # license first
            dialog.accept_license.setChecked(True)
            self.assertTrue(dialog.download_button.isEnabled())
            dialog.sound_for.setCurrentText('Eraser'); dialog.sound_for.activated.emit(2)
            self.assertIn('eraser', dialog.prompt.toPlainText())
            self.assertEqual(dialog.use_button.text(), 'Use as eraser sound')
            t = np.arange(sound.RATE * 2) / sound.RATE
            mono = (np.sin(2 * np.pi * 500 * t) * 8000).astype(np.int16)
            out = sound.write_wav(Path(self.tmp.name) / 'made.wav', np.stack([mono, mono], 1))
            dialog.on_result(str(out))
            self.assertTrue(dialog.play_button.isEnabled())
            dialog.use()
            self.assertEqual(used, [('sound', str(out.with_name('made_normal.wav')), 'sound_eraser_file')])
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

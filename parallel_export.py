"""Faster export: render and save the PNG frames on several CPU cores.

The frames of an animation do not depend on each other, so they are split into
small chunks and handed to worker processes (separate Python processes, because
the rendering is mostly Python and one process can only use one core). Each
worker receives the drawing and the export options once, renders its chunks
and writes the PNG files itself. The frames are exactly the same as a
single-core export: images travel as raw pixels, never re-compressed.

If anything about the parallel path fails before frames are written (an object
that cannot be sent to a worker, workers that cannot start), export_frames
simply renders on one core as before.
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from pathlib import Path

MIN_FRAMES = 120            # shorter exports: starting workers is not worth it
CHUNK = 6                   # frames per task (small: smooth progress, quick cancel)
MAX_WORKERS = 8


def worker_count(count, requested=None):
    """How many worker processes to use for `count` frames (1 = no parallel export)."""
    env = os.environ.get('STROKESCRIBE_EXPORT_WORKERS')
    if env is not None:
        try:
            requested = int(env)
        except ValueError:
            pass
    if requested is not None and int(requested) == 1:
        return 1
    cores = os.cpu_count() or 1
    if requested:                                    # explicit number (tests, power users)
        return max(1, min(int(requested), 32))
    if count < MIN_FRAMES or cores < 3:
        return 1
    return max(1, min(cores - 1, MAX_WORKERS, count // CHUNK))


# ------------------------------------------------------------ sending images

def _rebuild_image(width, height, fmt, stride, data, attrs):
    from PySide6.QtGui import QImage
    image = QImage(data, width, height, stride, QImage.Format(fmt)).copy()
    if attrs:
        import tools_kit
        tool = tools_kit.painting_tool(image, attrs['own_tip'], 1., 1., attrs['base_anchor'])
        tool.relative = attrs['relative']
        return tool
    return image


class _Pickler(pickle.Pickler):
    def reducer_override(self, obj):
        try:
            from PySide6.QtGui import QImage
        except ImportError:
            return NotImplemented
        if isinstance(obj, QImage):
            attrs = None
            if getattr(obj, 'own_tip', None) is not None:
                attrs = dict(own_tip=tuple(obj.own_tip), base_anchor=tuple(obj.base_anchor),
                             relative=float(obj.relative))
            if obj.isNull():
                return (QImage, ())
            data = bytes(obj.constBits())[:obj.sizeInBytes()]
            return (_rebuild_image, (obj.width(), obj.height(), obj.format().value, obj.bytesPerLine(), data, attrs))
        return NotImplemented


def pack(payload):
    buffer = io.BytesIO()
    _Pickler(buffer, protocol=pickle.HIGHEST_PROTOCOL).dump(payload)
    return buffer.getvalue()


# ------------------------------------------------------------ worker side

_STATE = {}


def _start_worker(payload, plan):
    if sys.platform != 'win32':
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QGuiApplication
    _STATE['app'] = QGuiApplication.instance() or QGuiApplication(['strokescribe-export'])
    data = pickle.loads(payload)
    _STATE.update(data)
    if plan:
        try:
            import adaptive_hand
            image = data['options'].get('final_image')
            key = adaptive_hand._plan_key(data['drawing'], image, data['options']['brush_width'],
                                          data['options']['stroke_spacing'])
            adaptive_hand._CACHE[key] = pickle.loads(plan)
        except Exception:
            pass                                    # the worker plans the brush route itself


def _render_chunk(start, stop, count):
    from engine import PNG_FAST_QUALITY, _frame_bytes, _reuse_frame
    from frame_render import compose_frame
    folder = Path(_STATE['folder'])
    previous = None
    for i in range(start, stop):
        img = compose_frame(_STATE['drawing'], i / (count - 1), _STATE['options'], _STATE['camera_path'])
        path = folder / f'frame_{i:06d}.png'
        pixels = _frame_bytes(img)
        if previous is not None and pixels == previous[0]:
            _reuse_frame(previous[1], path)
        else:
            if not img.save(str(path), 'PNG', PNG_FAST_QUALITY):
                raise OSError('Unable to save PNG frame.')
            previous = (pixels, path)
    return stop - start


# ------------------------------------------------------------ main side

def _brush_plan(drawing, options):
    """The cached brush plan for this export, pickled (or None)."""
    try:
        import adaptive_hand
        image = options.get('final_image')
        if image is None:
            return None
        if options.get('reveal_mode') in ('adaptive', 'zigzag', 'rows', 'columns'):
            drawing.paint_method = options['reveal_mode']
        key = adaptive_hand._plan_key(drawing, image, options['brush_width'], options['stroke_spacing'])
        plan = adaptive_hand._CACHE.get(key)
        return pack(plan) if plan is not None else None
    except Exception:
        return None


class NotStarted(Exception):
    """The parallel export could not start; nothing was written."""


def export_parallel(drawing, folder, options, camera_path, count, workers, callback=None):
    """Render frames 0..count-1 into `folder` with `workers` processes.

    Raises NotStarted if the work could not even be handed to the workers
    (the caller then renders on one core), InterruptedError when cancelled.
    """
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed
    try:
        payload = pack(dict(drawing=drawing, options=options, camera_path=camera_path, folder=str(folder)))
    except Exception as exc:
        raise NotStarted(f'cannot send the drawing to workers: {exc}')
    plan = _brush_plan(drawing, options)
    try:
        pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
                                   initializer=_start_worker, initargs=(payload, plan))
    except Exception as exc:
        raise NotStarted(str(exc))
    done = 0
    cancelled = False
    try:
        try:
            futures = [pool.submit(_render_chunk, a, min(count, a + CHUNK), count) for a in range(0, count, CHUNK)]
        except Exception as exc:
            raise NotStarted(str(exc))
        for future in as_completed(futures):
            done += future.result()
            if callback and callback(done, count) is False:
                cancelled = True
                for f in futures:
                    f.cancel()
                break
    except NotStarted:
        raise
    except Exception as exc:
        if done == 0 and not any(Path(folder).glob('frame_*.png')):
            raise NotStarted(str(exc))
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if cancelled:
        raise InterruptedError('Export cancelled; partial frames remain in the export folder.')
    return count

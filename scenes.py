"""Scenes: several drawings in one video, joined by camera moves.

A scene is a complete project state (drawing, colours, hand and every
setting, as Window.scene_state() makes it) plus the transition that leads to
the next scene. Each scene is rendered with the normal exporter (so all
features work per scene), then the scenes are joined: transition frames are
made from the last frame of one scene and the first frame of the next.

The output settings (resolution, frame rate, formats, background, sound
on/volume, CPU cores) are the same for every scene: those of the scene being
edited when you export.
"""
from __future__ import annotations

import json
import math
import shutil
import wave
from pathlib import Path

import numpy as np

# 'Same page': the next scene is another picture drawn on the same page; the
# pictures before it stay on the page (several pictures in one place).
SAME_PAGE = 'Same page'
SHOW_ALL = 'Show everything'      # after the last scene: zoom out to the whole board
TRANSITIONS = ('Camera move', 'Pan left', 'Pan right', 'Pan up', 'Pan down', 'Zoom in', 'Fade', 'Cut', SAME_PAGE,
               SHOW_ALL)
DEFAULT_TRANSITION = 'Camera move'
DEFAULT_TRANSITION_SECONDS = 1.2
# Output settings shared by all scenes (taken from the scene being edited).
GLOBAL_SETTINGS = ('res', 'fps', 'webm', 'webm_quality', 'mov', 'mp4', 'mp4_background', 'keep_png',
                   'sound_on', 'sound_volume', 'fast_export', 'preview_background', 'background_color',
                   'sound_pencil_file', 'sound_brush_file', 'sound_eraser_file')


def transition_seconds(kind, seconds, last=False):
    """Length of the move after a scene (after the last one: only for Show everything)."""
    import board
    return board.transition_seconds(kind, seconds, last)


def _ease(t):
    t = max(0., min(1., t))
    return t * t * (3 - 2 * t)


def transition_frame(a, b, kind, t):
    """Frame at t (0..1) of a transition from image a (end of a scene) to b (start of the next)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    w, h = a.width(), a.height()
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    e = _ease(t)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    def put(image, x, y, scale=1., opacity=1.):
        if opacity <= 0:
            return
        p.setOpacity(min(1., opacity))
        p.drawImage(QRectF(x + w * (1 - scale) / 2, y + h * (1 - scale) / 2, w * scale, h * scale), image)

    if kind == 'Pan left':                  # the camera moves left: pictures move right
        put(a, e * w, 0); put(b, -(1 - e) * w, 0)
    elif kind == 'Pan right':
        put(a, -e * w, 0); put(b, (1 - e) * w, 0)
    elif kind == 'Pan up':
        put(a, 0, e * h); put(b, 0, -(1 - e) * h)
    elif kind == 'Pan down':
        put(a, 0, -e * h); put(b, 0, (1 - e) * h)
    elif kind == 'Zoom in':                 # rush into the old picture, the new one opens up
        put(a, 0, 0, 1 + 1.6 * e, 1 - min(1., e * 1.4))
        put(b, 0, 0, .7 + .3 * e, max(0., (e - .35) / .65))
    elif kind == 'Fade':
        put(a, 0, 0, 1, 1 - min(1., 2 * e))
        put(b, 0, 0, 1, max(0., 2 * e - 1))
    else:                                   # Camera move: zoom out, travel along the board, zoom in
        zoom = 1 - .42 * math.sin(math.pi * t)
        distance = w * 1.12
        camera = e * distance
        for image, world in ((a, 0.), (b, distance)):
            put(image, (world - camera) * zoom, 0, zoom)
    p.end()
    return out


# ------------------------------------------------------------ pictures on one page

def on_page(scenes, k):
    """True when scene k is a picture added to the page of scene k-1."""
    return k > 0 and scenes[k - 1].get('transition') == SAME_PAGE


def finished_art(drawing, options, background=True):
    """The finished picture (no hand) at the options' size, as it stays on the page."""
    from frame_render import compose_frame
    opts = {k: v for k, v in options.items() if k not in ('fps', 'audio', 'workers')}
    opts.update(layers='art', ghost=0, background=background)
    return compose_frame(drawing, 1., opts)


def stack(base, top, blend_mode='Normal', opacity=100):
    """Composite one artwork over an existing scene without changing inputs."""
    if top is None:
        return base
    from PySide6.QtGui import QImage, QPainter
    from artwork_compositor import bounded_opacity
    from blend_modes import composition_mode
    if base is None:
        base = QImage(top.size(), QImage.Format.Format_ARGB32_Premultiplied)
        base.fill(0)
    out = base.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).copy()
    p = QPainter(out)
    p.setCompositionMode(composition_mode(blend_mode))
    p.setOpacity(bounded_opacity(opacity))
    p.drawImage(0, 0, top)
    p.end()
    return out


def for_page(options):
    """Options of a picture added to a page: no own background, no camera follow."""
    out = dict(options)
    out['background'] = False
    out['camera_zoom'] = 1.
    return out


# ------------------------------------------------------------ one scene

def job_from_state(data, hand=None, overrides=None):
    """(drawing, options, settings) for a saved scene/project state."""
    from export_job import options_from_settings
    from projects import drawing_from_dict, qimage_from_b64
    from tools_kit import hand_from_project, restore_paint_hand
    s = dict(data.get('settings', {}))
    if overrides:
        s.update(overrides)
    drawing = drawing_from_dict(data['drawing'])
    scene_hand = hand
    if data.get('hand'):
        scene_hand = hand_from_project(data['hand'])[0] or hand
    if data.get('paint_hand_png'):
        s['paint_hand_path'] = restore_paint_hand(s.get('paint_hand_path'), data['paint_hand_png'])
    if data.get('audio') and not s.get('audio_path'):
        s['audio_path'] = data['audio']
    if s.get('audio_path') and not Path(s['audio_path']).is_file():
        s['audio_path'] = None                     # moved voiceover: export without it
    if data.get('source') == 'image' and data.get('image'):
        from adaptive_hand import pil_image
        from image_regions import segment_regions
        image = qimage_from_b64(data['image']['png'])
        detail = data['image'].get('detail', 'medium')
        drawing.image_regions = segment_regions(pil_image(image), 'high' if detail == 'max' else detail)
        options = options_from_settings(s, drawing, hand=scene_hand, image_source=image, image_mode=True)
    else:
        from color_reveal import project_color
        options = options_from_settings(s, drawing, color_image=project_color(data)[1], hand=scene_hand)
    options['overlays'] = list(data.get('overlays') or [])
    return drawing, options, s


def seconds_of(drawing, options):
    from frame_render import timeline_seconds
    return timeline_seconds(drawing, options)


def frame_count(seconds, fps):
    return max(2, round(seconds * fps))          # same rule as engine.export_frames


def thumbnail(drawing, options, width=192):
    """Small picture of the finished scene (before any erase)."""
    from frame_render import compose_frame
    opts = {k: v for k, v in options.items() if k not in ('fps', 'audio', 'workers')}
    ratio = opts['height'] / opts['width']
    opts.update(width=width, height=max(2, round(width * ratio)), erase=None, layers='all')
    opts['hand_scale'] = opts.get('hand_scale', .75) / max(.01, opts.get('artwork_scale', 1.))
    return compose_frame(drawing, 1., opts)


# ------------------------------------------------------------ whole video

def plan(scenes, hand=None, overrides=None):
    """Prepared scenes: [{drawing, options, seconds, transition, transition_seconds, move_seconds, frame}].

    Every scene gets its frame on the board (board.py). A scene whose frame shows
    pictures drawn before it is drawn over them, without its own background."""
    import board
    out = []
    for i, scene in enumerate(scenes):
        drawing, options, settings = job_from_state(scene['state'], hand, overrides)
        last = i == len(scenes) - 1
        kind = scene.get('transition', DEFAULT_TRANSITION)
        move = float(scene.get('transition_seconds', DEFAULT_TRANSITION_SECONDS))
        out.append(dict(drawing=drawing, options=options, settings=settings,
                        seconds=seconds_of(drawing, options), transition=kind, move_seconds=move,
                        transition_seconds=transition_seconds(kind, move, last)))
    aspect = out[0]['options']['height'] / out[0]['options']['width'] if out else 9 / 16
    for p, frame in zip(out, board.frames(scenes, aspect)):
        p['frame'] = frame
    all_frames = [p['frame'] for p in out]
    for k, p in enumerate(out):
        if board.has_base(all_frames, k, aspect):
            p['options'] = dict(p['options'], background=False)
    return out


def _read_wav(path):
    with wave.open(str(path)) as f:
        data = np.frombuffer(f.readframes(f.getnframes()), np.int16).reshape(-1, f.getnchannels())
    return data


def _fit(audio, samples):
    if len(audio) >= samples:
        return audio[:samples]
    return np.vstack([audio, np.zeros((samples - len(audio), audio.shape[1]), np.int16)])


def export_scenes(scenes, folder, settings, hand=None, progress=lambda i, n: None, interrupted=lambda: False):
    """Render all scenes into one PNG sequence + videos. `settings`: the editor's settings
    (its output settings are used for every scene). Returns a summary text."""
    from engine import export_frames
    from export_job import encode_outputs, formats_from_settings
    from sound import RATE, soundtrack, write_wav
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    overrides = {k: settings[k] for k in GLOBAL_SETTINGS if k in settings}
    prepared = plan(scenes, hand, overrides)
    import board
    from PySide6.QtGui import QImage
    from frame_render import camera_for
    fps = int(prepared[0]['options']['fps'])
    width, height = prepared[0]['options']['width'], prepared[0]['options']['height']
    aspect = height / width
    all_frames = [p['frame'] for p in prepared]
    layers = prepared[0]['options'].get('layers', 'all')
    world = board.World([dict(drawing=p['drawing'], options=p['options'], frame=p['frame'], key=('scene', k))
                         for k, p in enumerate(prepared)], aspect)
    counts = [frame_count(p['seconds'], fps) for p in prepared]
    joins = [round(p['transition_seconds'] * fps) for p in prepared]
    total = sum(counts) + sum(joins)
    done = 0
    index = 0
    ranges = []
    work = folder / '_scenes'
    work.mkdir()

    def write(image):
        nonlocal index, done
        if not image.save(str(folder / f'frame_{index:06d}.png'), 'PNG', 80):
            raise OSError('Unable to save PNG frame.')
        index += 1; done += 1
        progress(done, total)
    try:
        for k, scene in enumerate(prepared):
            options = dict(scene['options'])
            options.pop('audio', None)
            base = done

            def tick(i, n, base=base):
                progress(base + i, total)
                return not interrupted()
            part = work / f'scene_{k + 1}'
            export_frames(scene['drawing'], part, callback=tick, **options)
            frames = sorted(part.glob('frame_*.png'))
            done = base + len(frames)
            if layers != 'hand' and board.has_base(all_frames, k, aspect):
                # Pictures drawn before this scene can be seen in its frame: draw over them
                # (following this scene's camera, if it follows the hand).
                camera = camera_for(scene['drawing'], options, float(options.get('camera_zoom', 1.)))
                still = None
                for i, frame in enumerate(frames):
                    if camera is None:
                        if still is None:
                            still = world.view(all_frames[k], width, height, upto=k)
                        under = still
                    else:
                        view = board.sub_view(all_frames[k], *camera.at(i / max(1, len(frames) - 1)), aspect)
                        under = world.view(view, width, height, upto=k)
                    # Export uses the exact same separation as whole-video
                    # preview: artwork gets this scene's blend and opacity,
                    # the moving hand remains opaque and normally colored.
                    from artwork_compositor import composite_element
                    if layers=='all' and (
                            options.get('blend_mode','Normal')!='Normal' or
                            options.get('artwork_opacity',100)!=100):
                        display_opts=dict(options)
                        display_opts['hand_scale']=float(display_opts.get('hand_scale',.75)) / max(
                            .25,float(display_opts.get('artwork_scale',1)))
                        display_opts['width'],display_opts['height']=width,height
                        output=composite_element(under,scene['drawing'],
                            i/max(1,len(frames)-1),display_opts,camera)
                    else:
                        output=stack(under,QImage(str(frame)),
                            options.get('blend_mode','Normal'),
                            options.get('artwork_opacity',100))
                    if not output.save(str(frame), 'PNG', 80):
                        raise OSError('Unable to save PNG frame.')
            start = index
            for frame in frames:
                frame.replace(folder / f'frame_{index:06d}.png')
                index += 1
            ranges.append((start, index))
            # The move after this scene: the camera flies over the board to the next frame
            # (or, after the last scene, out to the whole board).
            n = joins[k]
            kind = scene['transition']
            last = k == len(prepared) - 1
            screens = None
            for j in range(n):
                t = (j + 1) / n if last else (j + 1) / (n + 1)
                if layers == 'hand':
                    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied); image.fill(0)
                elif kind in board.SCREEN_KINDS and not last:
                    if screens is None:
                        screens = (world.view(all_frames[k], width, height, upto=k + 1),
                                   world.view(all_frames[k + 1], width, height, upto=k + 1))
                    image = transition_frame(screens[0], screens[1], kind, t)
                else:
                    view = board.join_view(all_frames, k, kind, t, aspect, scene['move_seconds'])
                    image = world.view(view, width, height, upto=k + 1)
                write(image)
            if interrupted():
                raise InterruptedError('Export cancelled; partial frames remain in the export folder.')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    seconds = index / fps
    (folder / 'sequence.json').write_text(json.dumps(dict(
        width=prepared[0]['options']['width'], height=prepared[0]['options']['height'], fps=fps,
        frames=index, duration=seconds,
        scenes=[dict(first_frame=a, frames=b - a,
                     transition_after=p['transition'] if k < len(prepared) - 1 or joins[k] else None,
                     board_frame=dict(zip(('cx', 'cy', 'w'), p['frame'])))
                for k, ((a, b), p) in enumerate(zip(ranges, prepared))]), indent=2))
    # Sound: every scene's pencil/brush/eraser sounds in place, silence during
    # transitions; each scene's voiceover starts with its scene.
    formats = formats_from_settings(settings)
    effects = formats['sound_volume']             # None: pencil sounds off
    audio = None
    if effects is not None or any(p['options'].get('audio') for p in prepared):
        progress(0, 0)
        parts = []
        for k, scene in enumerate(prepared):
            frames = ranges[k][1] - ranges[k][0]
            gap = joins[k - 1] if k else 0
            if gap:
                parts.append(np.zeros((round(gap / fps * RATE), 2), np.int16))
            samples = round(frames / fps * RATE)
            if effects is not None:
                opts = dict(scene['options']); opts.pop('audio', None)
                path = soundtrack(scene['drawing'], opts, folder / f'_sound_{k}.wav', effects)
                parts.append(_fit(_read_wav(path), samples))
                path.unlink()
            else:
                parts.append(np.zeros((samples, 2), np.int16))
        if joins[-1]:                              # the zoom out to the whole board at the end
            parts.append(np.zeros((round(joins[-1] / fps * RATE), 2), np.int16))
        track = np.vstack(parts)
        voices = [(k, p['options']['audio']) for k, p in enumerate(prepared) if p['options'].get('audio')]
        audio = write_wav(folder / ('pencil_sounds.wav' if voices else 'soundtrack.wav'), track)
        if voices:
            from audio_track import mix
            for n, (k, voice) in enumerate(voices):
                start = ranges[k][0] / fps
                target = folder / ('soundtrack.wav' if n == len(voices) - 1 else f'_mix_{n}.wav')
                mixed = mix(audio, voice['path'], voice['volume'], start + voice['offset'], seconds, target)
                if audio.name.startswith('_mix_'):
                    audio.unlink()
                audio = mixed
    return encode_outputs(folder, fps, audio=audio, progress=progress, interrupted=interrupted, **formats)


# ------------------------------------------------------------ preview timing

def locate(lengths, joins, seconds):
    """Where `seconds` falls: ('scene', k, fraction) or ('join', k, t) between k and k+1."""
    t = 0.
    for k, length in enumerate(lengths):
        if seconds <= t + length or k == len(lengths) - 1:
            return 'scene', k, max(0., min(1., (seconds - t) / max(1e-9, length)))
        t += length
        gap = joins[k]
        if gap > 0 and seconds < t + gap:
            return 'join', k, (seconds - t) / gap
        t += gap
    return 'scene', len(lengths) - 1, 1.


# ------------------------------------------------------------ project files

def scenes_from_project(data):
    """[{state, transition, transition_seconds}] from a project file's data.

    The project's main body is the scene that was being edited; the 'scenes'
    list holds the others, with state None at the edited scene's place."""
    listed = data.get('scenes')
    main = {k: v for k, v in data.items() if k not in ('scenes', 'scene_index')}
    if not listed:
        return [dict(state=main, transition=DEFAULT_TRANSITION, transition_seconds=DEFAULT_TRANSITION_SECONDS)]
    out = []
    for item in listed:
        state = item.get('state') or main
        out.append(dict(state=state, transition=item.get('transition', DEFAULT_TRANSITION),
                        transition_seconds=float(item.get('transition_seconds', DEFAULT_TRANSITION_SECONDS)),
                        name=item.get('name'), board=item.get('board')))
    return out


def scenes_to_project(main_state, scene_list, index):
    """Project data: the edited scene as the main body plus every scene in order."""
    data = dict(main_state)
    if len(scene_list) > 1:
        data['scenes'] = [dict(state=None if k == index else s['state'], transition=s['transition'],
                               transition_seconds=s['transition_seconds'], name=s.get('name'),
                               board=s.get('board'))
                          for k, s in enumerate(scene_list)]
        data['scene_index'] = index
    return data

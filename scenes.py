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
                   'sound_pencil_file', 'sound_brush_file', 'sound_eraser_file',
                   'hand_rest', 'hand_rest_corner', 'hand_rest_travel')       # exp.143


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
    out.pop('cam_plan', None)
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


def on_tracks(scenes):
    """True when an element has its own start or a track above Track 1 (timeline_model)."""
    return any(s.get('start') is not None or (s.get('track') or 0) or s.get('hidden') or s.get('muted')
               for s in scenes)


def with_holds(titles, move_starts, total, page_at=None):
    """exp.123: texts with no way out stay to the end of the video, on their page (like the
    drawings): page_at(seconds) gives the page the camera shows when the text starts."""
    import overlays
    out = []
    for o in titles or ():
        end = overlays.end_of(o)
        extra = {'_until': max(end, total)}
        if page_at is not None:
            extra['_page'] = page_at(float(o.get('start', 0)))
        out.append(dict(o, **extra))
    return out


def paint_titles(folder, fps, titles, world=None, views=None):
    """exp.116: the video's texts / pictures on top, drawn over the finished PNG frames
    (in seconds of the whole video). exp.123: on their page, where the camera's view of the
    frame (views[i]) has it."""
    if not titles:
        return
    import overlays
    import timeline_render
    from PySide6.QtGui import QImage
    from frame_writer import FrameWriter
    writer = FrameWriter()
    try:
        _paint_titles(folder, fps, titles, world, views, writer)
    finally:
        writer.close()


def _paint_titles(folder, fps, titles, world, views, writer):
    import overlays
    import timeline_render
    from PySide6.QtGui import QImage
    for path in sorted(Path(folder).glob('frame_*.png')):
        i = int(path.stem.split('_')[-1])
        t = i / float(fps)
        if not any(overlays.state_at(o, t) is not None for o in titles):
            continue
        image = QImage(str(path)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        view = views[i] if views is not None and i < len(views) else None
        if world is not None and view is not None:
            image = timeline_render.paint_texts(image, titles, t, world.frames, world.place, view)
        else:
            overlays.paint(image, titles, t)
        writer.write(image, path)


def _resting_options(lay, elements, seconds, hidden=()):
    """exp.143: the options to draw the waiting hand with at `seconds` of a video on tracks
    (None while an element's own hand draws or travels, or when it does not wait)."""
    from frame_render import hand_window
    chosen = None
    for it in lay.items:
        if it.k in hidden:
            continue
        e = elements[it.k]
        if not e['options'].get('hand_travel'):
            continue
        window = hand_window(e['drawing'], e['options'])
        if window is None:
            continue
        if chosen is None or it.start <= seconds:
            chosen = e['options']
        if it.start - 1e-6 <= seconds < it.start + window[0] - 1e-6:
            return None
    return chosen


def export_timeline(scenes, folder, settings, hand=None, progress=lambda i, n: None, interrupted=lambda: False,
                    titles=None, cameras=None):
    """The whole video when elements are on tracks: every frame is one moment of the
    timeline (timeline_render.compose), at the export size. The sounds of each element
    start with it; voiceovers too."""
    import board
    import timeline_render
    from export_job import encode_outputs, formats_from_settings
    from frame_render import camera_for
    from sound import RATE, soundtrack, write_wav
    from timeline_model import layout, state_at
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    overrides = {k: settings[k] for k in GLOBAL_SETTINGS if k in settings}
    prepared = plan(scenes, hand, overrides)
    fps = int(prepared[0]['options']['fps'])
    width, height = prepared[0]['options']['width'], prepared[0]['options']['height']
    aspect = height / width
    world = board.World([dict(drawing=p['drawing'], options=p['options'], frame=p['frame'], key=('scene', k))
                         for k, p in enumerate(prepared)], aspect)
    lay = layout([p['seconds'] for p in prepared], [p['transition_seconds'] for p in prepared],
                 [s.get('start') for s in scenes], [s.get('track') or 0 for s in scenes])
    elements = []
    for p in prepared:
        options = {k: v for k, v in p['options'].items() if k not in ('audio', 'fps', 'workers')}
        # compose_frame takes the hand size relative to the scaled artwork (like the preview).
        options['hand_scale'] = float(options.get('hand_scale', .18)) / max(.25, float(options.get('artwork_scale', 1.)))
        zoom = float(options.get('camera_zoom', 1.) or 1.)
        camera = camera_for(p['drawing'], options, zoom) if zoom > 1.0001 or options.get('cam_plan') else None
        if cameras:                                     # exp.119: the Camera track
            import camera_clips
            item = lay.items[len(elements)]
            camera = camera_clips.wrap(camera, item.start, cameras, [(m.start, m.end) for m in lay.moves],
                                       item.length)
        if cameras:
            import camera_clips
            hand_sig = camera_clips.hand_signature(cameras)       # exp.147: the Hand row
            if hand_sig:
                options.update(hand_away=hand_sig, hand_video_start=lay.items[len(elements)].start)
        elements.append(dict(drawing=p['drawing'], options=options, camera=camera,
                             transition=p['transition'], move_seconds=p['move_seconds']))
    total = max(1, round(lay.total * fps))
    titles = with_holds(titles, [m.start for m in lay.moves], lay.total,
                        page_at=lambda sec: timeline_render.page_of(lay, sec))
    hidden = {k for k, s in enumerate(scenes) if s.get('hidden')}       # their track is hidden
    from dataclasses import replace
    from frame_writer import FrameWriter
    import applog
    import time as _time
    began = _time.perf_counter()
    writer = FrameWriter()                       # exp.125: PNGs saved on other threads
    try:
        for i in range(total):
            state = state_at(lay, i / fps)
            if hidden:
                active = [(k, f) for k, f in state.active if k not in hidden]
                state = replace(state, active=active, finished=[k for k in state.finished if k not in hidden],
                                top=active[-1][0] if active else -1)
            image = timeline_render.compose(world, lay, state, elements, width, height, titles=titles, seconds=i / fps)
            rest = _resting_options(lay, elements, i / fps, hidden)
            if rest is not None:                     # exp.143: the hand waiting in its corner
                from frame_render import paint_rest_hand
                image = paint_rest_hand(image, rest, i / fps)
            writer.write(image, folder / f'frame_{i:06d}.png')
            progress(i + 1, total)
            if interrupted():
                raise InterruptedError('Export cancelled; partial frames remain in the export folder.')
    finally:
        writer.close()
    applog.info('Export: %d frames (%d x %d, %d fps) drawn and saved in %.1f s', total, width, height, fps,
                _time.perf_counter() - began)
    seconds = total / fps
    (folder / 'sequence.json').write_text(json.dumps(dict(
        width=width, height=height, fps=fps, frames=total, duration=seconds,
        scenes=[dict(first_frame=round(it.start * fps), frames=round(it.length * fps), track=it.track,
                     board_frame=dict(zip(('cx', 'cy', 'w'), prepared[it.k]['frame'])))
                for it in lay.items]), indent=2))
    formats = formats_from_settings(settings)
    effects = formats['sound_volume']
    audio = None
    if effects is not None or any(p['options'].get('audio') for p in prepared):
        progress(0, 0)
        track = np.zeros((round(seconds * RATE) + 1, 2), np.int32)
        if effects is not None:
            for it in lay.items:
                if scenes[it.k].get('muted') or it.k in hidden:
                    continue                           # its track is muted (or hidden)
                opts = dict(prepared[it.k]['options']); opts.pop('audio', None)
                path = soundtrack(prepared[it.k]['drawing'], opts, folder / f'_sound_{it.k}.wav', effects)
                part = _read_wav(path).astype(np.int32); path.unlink()
                at = round(it.start * RATE)
                part = part[:max(0, len(track) - at)]
                track[at:at + len(part)] += part
        audio = write_wav(folder / 'soundtrack.wav', np.clip(track, -32768, 32767).astype(np.int16))
        voices = [(it, prepared[it.k]['options']['audio']) for it in lay.items if prepared[it.k]['options'].get('audio')]
        if voices:
            from audio_track import mix
            for n, (it, voice) in enumerate(voices):
                target = folder / (f'_mix_{n}.wav' if n < len(voices) - 1 else 'soundtrack_mixed.wav')
                mixed = mix(audio, voice['path'], voice['volume'], it.start + voice['offset'], seconds, target)
                if audio.name.startswith('_mix_'):
                    audio.unlink()
                audio = mixed
    return encode_outputs(folder, fps, audio=audio, progress=progress, interrupted=interrupted, **formats)


def export_scenes(scenes, folder, settings, hand=None, progress=lambda i, n: None, interrupted=lambda: False,
                  titles=None, cameras=None):
    """Render all scenes into one PNG sequence + videos. `settings`: the editor's settings
    (its output settings are used for every scene). Returns a summary text."""
    if on_tracks(scenes):
        return export_timeline(scenes, folder, settings, hand, progress, interrupted, titles, cameras)
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
    if cameras:
        # exp.119: the Camera track: every element's frames (and the moves) with the clips.
        import camera_clips
        starts, moves, at = [], [], 0
        for c, j in zip(counts, joins):
            starts.append(at / fps); at += c
            moves.append((at / fps, (at + j) / fps)); at += j
        sig = camera_clips.signature(cameras)
        hand_sig = camera_clips.hand_signature(cameras)          # exp.147: the Hand row
        for k, p in enumerate(prepared):
            p['options'] = dict(p['options'], video_camera=(starts[k], sig, tuple(moves)))
            if hand_sig:
                p['options'].update(hand_away=hand_sig, hand_video_start=starts[k])
    total = sum(counts) + sum(joins)
    done = 0
    index = 0
    ranges = []
    work = folder / '_scenes'
    work.mkdir()

    cameras = {}
    views, pages = [], []                # exp.123: per frame: the camera's view, the page shown

    def scene_camera(j):
        """Element j's own camera (exp.115: the moves start and land on it)."""
        if not 0 <= j < len(prepared):
            return None
        if j not in cameras:
            o = prepared[j]['options']
            cameras[j] = camera_for(prepared[j]['drawing'], o, float(o.get('camera_zoom', 1.)))
        return cameras[j]

    from frame_writer import FrameWriter
    writer = FrameWriter()                       # exp.125: PNGs saved on other threads

    def write(image):
        nonlocal index, done
        writer.write(image, folder / f'frame_{index:06d}.png')
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
                        from frame_render import resting, paint_rest_hand
                        if display_opts.get('hand_travel') and resting(scene['drawing'],display_opts,i/max(1,len(frames)-1)):
                            output=paint_rest_hand(output,display_opts)      # exp.143
                    else:
                        output=stack(under,QImage(str(frame)),
                            options.get('blend_mode','Normal'),
                            options.get('artwork_opacity',100))
                    writer.write(output, frame)
            writer.flush()                       # the files are renamed next
            start = index
            camera = scene_camera(k)
            for i, frame in enumerate(frames):
                frame.replace(folder / f'frame_{index:06d}.png')
                index += 1
                # exp.123: what the camera shows in this frame (texts are drawn on their page).
                views.append(board.sub_view(all_frames[k], *camera.at(i / max(1, len(frames) - 1)), aspect)
                             if camera is not None else all_frames[k])
                pages.append(k)
            ranges.append((start, index))
            # The move after this scene: the camera flies over the board to the next frame
            # (or, after the last scene, out to the whole board).
            n = joins[k]
            kind = scene['transition']
            last = k == len(prepared) - 1
            screens = None
            for j in range(n):
                t = (j + 1) / n if last else (j + 1) / (n + 1)
                view = None
                if layers == 'hand':
                    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied); image.fill(0)
                elif kind in board.SCREEN_KINDS and not last:
                    if screens is None:
                        screens = (world.view(all_frames[k], width, height, upto=k + 1),
                                   world.view(all_frames[k + 1], width, height, upto=k + 1))
                    image = transition_frame(screens[0], screens[1], kind, t)
                else:
                    view = board.join_view(all_frames, k, kind, t, aspect, scene['move_seconds'],
                                           leaving=scene_camera(k), arriving=scene_camera(k + 1))
                    image = world.view(view, width, height, upto=k + 1)
                if options.get('hand_travel') and layers != 'art':
                    # exp.143: the hand waits in its corner while the camera moves.
                    from frame_render import paint_rest_hand
                    image = paint_rest_hand(image, dict(options, width=width, height=height,
                        hand_scale=float(options.get('hand_scale', .75)) / max(.25, float(options.get('artwork_scale', 1.)))),
                        index / fps)
                if kind in board.SCREEN_KINDS and not last:
                    views.append(None)
                else:
                    views.append(view)
                pages.append(min(k + 1, len(prepared) - 1))
                write(image)
            if interrupted():
                raise InterruptedError('Export cancelled; partial frames remain in the export folder.')
    finally:
        try:
            writer.close()
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if titles:
        starts, at = [], 0
        for c, j in zip(counts, joins):
            at += c
            if j: starts.append(at / fps)
            at += j
        titles = with_holds(titles, starts, index / fps,
                            page_at=lambda sec: pages[min(len(pages) - 1, max(0, round(sec * fps)))] if pages else 0)
    paint_titles(folder, fps, titles, world, views)
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
        return [dict(state=main, transition=DEFAULT_TRANSITION, transition_seconds=DEFAULT_TRANSITION_SECONDS,
                     uid=data.get('scene_uid'), rev=data.get('scene_rev'), thumb_png=data.get('thumb_png'))]
    out = []
    for item in listed:
        state = item.get('state') or main
        out.append(dict(state=state, transition=item.get('transition', DEFAULT_TRANSITION),
                        transition_seconds=float(item.get('transition_seconds', DEFAULT_TRANSITION_SECONDS)),
                        name=item.get('name'), board=item.get('board'),
                        uid=item.get('uid'), rev=item.get('rev'),
                        start=item.get('start'), track=item.get('track') or 0,
                        hidden=bool(item.get('hidden')), muted=bool(item.get('muted')),
                        thumb_png=item.get('thumb_png')))
    return out


def scenes_to_project(main_state, scene_list, index):
    """Project data: the edited scene as the main body plus every scene in order."""
    data = dict(main_state)
    if len(scene_list) > 1:
        data['scenes'] = [dict(state=None if k == index else s['state'], transition=s['transition'],
                               transition_seconds=s['transition_seconds'], name=s.get('name'),
                               board=s.get('board'), uid=s.get('uid'), rev=s.get('rev'),
                               start=s.get('start'), track=s.get('track') or 0,
                               hidden=bool(s.get('hidden')), muted=bool(s.get('muted')))
                          for k, s in enumerate(scene_list)]
        data['scene_index'] = index
    elif scene_list:
        # One element: its revision (ready frames found again next session).
        data['scene_uid'], data['scene_rev'] = scene_list[0].get('uid'), scene_list[0].get('rev')
    return data

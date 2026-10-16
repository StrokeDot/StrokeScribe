"""Shared export steps (single export and batch export) and settings → options.

`options_from_settings` turns the Studio settings (the values of the inspector
controls, as saved in projects) into render options, so the window, project
files and batch export always produce the same animation.
"""
from __future__ import annotations

from pathlib import Path

REVEAL_BY_TEXT = {'Brush painting': 'brush', 'Adaptive Hand Painting': 'adaptive',
                  'Zigzag sweep': 'zigzag'}
MP4_BACKGROUNDS = ('white', 'dark', 'black')
CAMERA_BY_TEXT = {'Off': 'off', 'Gentle zoom': 'gentle', 'Close-up zoom': 'close'}


def options_from_settings(s, drawing, color_image=None, hand=None, image_source=None, image_mode=None):
    """Render options for export_frames.

    s: settings dict (see Window.PROJECT_SETTINGS). color_image: colour PNG for
    SVG sources. image_source: QImage of an image source (then its colours are
    painted and the Image source rules apply).
    """
    width, height = [int(x.strip()) for x in str(s.get('res', '1920 × 1080')).split('×')]
    reveal = REVEAL_BY_TEXT.get(s.get('reveal_mode'), 'adaptive')
    options = dict(
        duration=float(s.get('duration', 4)) / max(.01, float(s.get('speed', 1))),
        fps=int(s.get('fps', 30)), width=width, height=height,
        thickness=float(s.get('thickness', 1)),
        hand=hand if s.get('showhand', True) else None,
        hand_scale=float(s.get('handsize', .75)), anchor=(float(s.get('ax', .08)), float(s.get('ay', .13))),
        final_image=color_image if s.get('use_color', False) else None,
        fade_duration=float(s.get('color_fade', .4)), hold_duration=float(s.get('color_hold', .6)),
        reveal_mode=reveal, brush_width=float(s.get('brush_width', .14)),
        stroke_spacing=float(s.get('stroke_spacing', .55)),
        artwork_scale=float(s.get('artwork_size', 100)) / 100.,
        painting_hand=None)
    from tools_kit import painting_hand
    options['painting_hand'] = painting_hand(s, hand)
    options['erase'] = erase_from_settings(s, hand)
    options['workers'] = 0 if s.get('fast_export', True) else 1
    if drawing is not None:
        # Timing control (stroke_timing): pauses are in seconds of drawing time.
        drawing.draw_seconds = options['duration']
        drawing.pen_ease = 'natural' if str(s.get('pen_ease') or '').startswith('Natural') else 'off'
    audio_path = s.get('audio_path')
    options['audio'] = (dict(path=audio_path, volume=float(s.get('audio_volume', 100)) / 100.,
                             offset=float(s.get('audio_offset', 0)))
                        if audio_path else None)
    from camera import ZOOMS
    options['camera_zoom'] = ZOOMS[CAMERA_BY_TEXT.get(s.get('camera') or 'Off', 'off')]
    if image_mode is None:
        image_mode = image_source is not None
    if image_mode:
        paint_only = s.get('image_animation') == 'Paint Only'
        if drawing is not None:
            drawing.image_animation = 'paint_only' if paint_only else 'draw_paint'
            drawing.drawing_visibility = 'progressive'
        options.update(final_image=image_source if image_source is not None
                       and (s.get('preserve_colors', True) or paint_only) else None,
                       fade_duration=float(s.get('image_duration', 8)),
                       reveal_mode=reveal if reveal in ('adaptive', 'zigzag') else 'adaptive',
                       duration=0. if paint_only else options['duration'])
    return options


_ERASER_IMAGE = None


def builtin_eraser():
    global _ERASER_IMAGE
    if _ERASER_IMAGE is None:
        from PySide6.QtGui import QImage
        from eraser import DEFAULT_ERASER
        _ERASER_IMAGE = QImage(str(DEFAULT_ERASER))
    return _ERASER_IMAGE


def erase_from_settings(s, hand=None):
    """Erase-stage settings for the renderer, or None when erasing is off."""
    from eraser import ERASER_TIP, MODES
    mode = MODES.get(s.get('erase_mode') or 'Off')
    if not mode:
        return None
    size = float(s.get('erase_size', 8)) / 100.
    use_hand = s.get('eraser') == 'Pen hand' and hand is not None and not hand.isNull()
    return dict(mode=mode, seconds=float(s.get('erase_time', 3)), size=size,
                image=hand if use_hand else builtin_eraser(),
                anchor=(float(s.get('ax', .08)), float(s.get('ay', .13))) if use_hand else ERASER_TIP,
                width=float(s.get('handsize', .75)) if use_hand else max(.1, size * 2.2))


def formats_from_settings(s):
    return dict(mov=bool(s.get('mov')), webm=bool(s.get('webm')),
                webm_quality=int(s.get('webm_quality', 28)), keep_png=bool(s.get('keep_png')),
                mp4=bool(s.get('mp4')),
                mp4_background=(s.get('mp4_background') or 'White').lower(),
                sound_volume=(int(s.get('sound_volume', 80)) / 100) if s.get('sound_on', True) else None)


def run_export(drawing, folder, options, mov=False, webm=False, webm_quality=28, keep_png=True,
               mp4=False, mp4_background='white', sound_volume=None, progress=lambda i, n: None,
               interrupted=lambda: False):
    """Frames, optional soundtrack, then the chosen videos. Returns a summary."""
    from engine import export_frames
    folder = Path(folder)
    options = dict(options)
    voice = options.pop('audio', None)

    def tick(i, n):
        progress(i, n)
        return not interrupted()
    export_frames(drawing, folder, callback=tick, **options)
    audio = None
    if voice and not Path(voice['path']).is_file():
        raise FileNotFoundError('The voiceover/music file was not found: ' + str(voice['path']))
    if sound_volume is not None:
        progress(0, 0)
        from sound import soundtrack
        audio = soundtrack(drawing, options, folder / ('pencil_sounds.wav' if voice else 'soundtrack.wav'),
                           sound_volume)
    if voice:
        progress(0, 0)
        from audio_track import mix
        from frame_render import timeline_seconds
        audio = mix(audio, voice['path'], voice['volume'], voice['offset'],
                    timeline_seconds(drawing, options), folder / 'soundtrack.wav')
    return encode_outputs(folder, options['fps'], mov, webm, webm_quality, keep_png, mp4, mp4_background,
                          audio=audio, progress=progress, interrupted=interrupted)


def encode_outputs(folder, fps, mov=False, webm=False, webm_quality=28, keep_png=True, mp4=False,
                   mp4_background='white', sound_volume=None, audio=None, progress=lambda i, n: None,
                   interrupted=lambda: False):
    """Encode the PNG frames in `folder` into the chosen videos. Returns a summary."""
    from engine import encode_mov, encode_mp4, encode_webm
    folder = Path(folder)
    videos = []
    for wanted, make in ((webm, lambda: encode_webm(folder, fps, webm_quality, audio)),
                         (mov, lambda: encode_mov(folder, fps, audio)),
                         (mp4, lambda: encode_mp4(folder, fps, mp4_background, audio))):
        if not wanted:
            continue
        if interrupted():
            raise InterruptedError('Export cancelled; completed files were retained.')
        progress(0, 0)
        videos.append(make())
    if videos and not keep_png:
        # Only remove intermediate frames once every selected format encoded
        # successfully. Never remove user-supplied artwork.
        for frame in folder.glob('frame_*.png'):
            frame.unlink()
    if videos:
        details = ', '.join(f'{v.name} ({v.stat().st_size / 1048576:.1f} MB)' for v in videos)
        return f'Saved: {details} in {folder}'
    return f'Saved PNG sequence: {folder}'

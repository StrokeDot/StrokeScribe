"""One frame of the final video, exactly as preview and export show it.

Order: render the artwork (larger when the camera is zoomed in), apply Artwork
size, put the hand on its own layer, crop the camera view, then the optional
lettering background.
"""
from __future__ import annotations


def compose_frame(drawing, fraction, options, camera_path=None):
    """options: render_color_timeline keywords plus artwork_scale (and duration)."""
    from camera import crop, render_size
    from engine import render, scale_animation_frame, apply_lettering_background
    from hand_layer import capture
    opts = dict(options)
    scale = opts.pop('artwork_scale', 1.0)
    width, height = opts['width'], opts['height']
    zoom, cx, cy = camera_path.at(fraction) if camera_path is not None else (1., .5, .5)
    big_w, big_h = render_size(width, height, zoom)
    opts['width'], opts['height'] = big_w, big_h
    with capture() as hands:
        if opts.get('final_image') is not None and not opts['final_image'].isNull():
            from color_reveal import render_color_timeline
            frame = render_color_timeline(drawing, fraction, **opts)
        else:
            frame = render(drawing, fraction, big_w, big_h, opts.get('thickness', 1.),
                           opts.get('hand'), opts.get('hand_scale', .18), opts.get('anchor', (.1, .1)))
    frame = scale_animation_frame(frame, scale, hands)
    frame = crop(frame, width, height, zoom, cx, cy)
    return apply_lettering_background(frame, drawing)


def camera_for(drawing, options, zoom, rate=30.):
    """Plan the camera path for these options (None when the camera is off)."""
    import camera
    import motion
    if zoom <= 1.0001 or drawing is None:
        return None
    total = timeline_seconds(drawing, options)
    w, h = options.get('width', 1920), options.get('height', 1080)
    samples = motion.track(drawing, dict(options, width=w, height=h), total, rate)
    return camera.plan(samples, total, w, h, zoom)


def timeline_seconds(drawing, options):
    """Length of the animation in seconds for these options."""
    from color_reveal import timeline_duration
    image = options.get('final_image')
    if image is None or image.isNull():
        return max(.001, float(options.get('duration', 4)))
    if getattr(drawing, 'source_kind', None) == 'image' and getattr(drawing, 'image_animation', None) == 'paint_only':
        return max(.001, float(options.get('fade_duration', .4))) + max(0., float(options.get('hold_duration', .6)))
    return timeline_duration(options.get('duration', 4), image, options.get('fade_duration', .4),
                             options.get('hold_duration', .6))

"""exp.57 (the user): Ctrl+C / Ctrl+V for whatever is chosen, in This element, Whole video and
Board (and Advanced edit), like Delete: lines of the element (the line list or the preview has
the keyboard), camera clips and Hand motions, texts / pictures / stickers / erasers on top, or
else the chosen element. A paste goes at the playhead: clips start there, an element goes where
a new element goes (after the element under the playhead). Text fields keep their own copy and
paste."""

import copy
import uuid

# what was copied: dict(kind=..., data=...); kept for the whole program (paste in another project too)
CLIPBOARD = {}


def _clean(item):
    """A copy without what the program works out while it runs (keys starting with _)."""
    return {k: copy.deepcopy(v) for k, v in item.items() if not str(k).startswith('_')}


def lines_have_keys(w, focus=None):
    """True when the copy is about the element's lines: the line list or (This element) the
    preview has the keyboard and lines are chosen."""
    if not getattr(w, 'drawing', None):
        return False
    try:
        rows = w.selected_rows()
    except Exception:
        return False
    if not rows:
        return False
    order, canvas = getattr(w, 'order', None), getattr(w, 'canvas', None)
    inside = lambda box: box is not None and focus is not None and (focus is box or box.isAncestorOf(focus))
    if inside(order):
        return True
    return inside(canvas) and not (w.all_scenes() or w.board_mode())


def copy_selection(w, focus=None, lines_only=False):
    """Ctrl+C. Returns the kind copied, or None."""
    if lines_have_keys(w, focus):
        rows = sorted(set(w.selected_rows()))
        strokes = [copy.deepcopy(w.drawing.strokes[i]) for i in rows if 0 <= i < len(w.drawing.strokes)]
        CLIPBOARD.clear(); CLIPBOARD.update(kind='lines', data=strokes)
        w.status.setText(f'Copied {len(strokes)} line(s). Ctrl+V pastes them into the element you are editing.')
        return 'lines'
    if lines_only or not getattr(w, 'drawing', None):
        return None
    tl = getattr(w, 'stage_timeline', None)
    cid = getattr(w, 'selected_camera', None)
    clip = w.find_camera(cid) if cid else None
    if clip is not None:
        CLIPBOARD.clear(); CLIPBOARD.update(kind='camera', data=[_clean(clip)])
        w.status.setText(f'Copied "{clip.get("kind", "camera clip")}". Ctrl+V pastes it at the playhead.')
        return 'camera'
    chosen = [o for o in w.chosen_overlays()] if hasattr(w, 'chosen_overlays') else []
    if not chosen and getattr(w, 'selected_overlay', None):
        one = w.find_overlay(w.selected_overlay)
        chosen = [one] if one is not None else []
    if chosen:
        CLIPBOARD.clear(); CLIPBOARD.update(kind='overlays', data=[_clean(o) for o in chosen])
        name = chosen[0].get('name') or 'clip'
        w.status.setText((f'Copied "{name}"' if len(chosen) == 1 else f'Copied {len(chosen)} clips') +
                         '. Ctrl+V pastes at the playhead.')
        return 'overlays'
    if tl is not None and getattr(tl, 'selected_bg', None) is not None:
        w.status.setText('Ctrl+C: a piece of the Background row cannot be copied (right-click it to change it).')
        return None
    k = w.scene_index
    if not 0 <= k < len(w.scenes):
        return None
    w.store_scene(thumbnail=False)
    scene = w.scenes[k]
    snap = {key: copy.deepcopy(v) for key, v in scene.items() if key not in ('thumb', 'start', 'track', 'board')}
    thumb = scene.get('thumb')
    try:
        snap['thumb'] = thumb.copy() if thumb is not None else None
    except Exception:
        snap['thumb'] = None
    CLIPBOARD.clear(); CLIPBOARD.update(kind='element', data=snap)
    w.status.setText(f'Copied element {k + 1} ({w.scene_label(k)}). Ctrl+V pastes a copy at the playhead.')
    return 'element'


def _free_track(items, start, end, track):
    """The first overlay track from `track` up with nothing between start and end."""
    while any(int(o.get('track', 0) or 0) == track and float(o.get('start', 0)) < end - 1e-6 and
              float(o.get('start', 0)) + float(o.get('duration', 0)) > start + 1e-6 for o in items):
        track += 1
    return track


def paste(w, focus=None, lines_only=False):
    """Ctrl+V. Returns the kind pasted, or None."""
    kind = CLIPBOARD.get('kind')
    if not kind or not getattr(w, 'drawing', None):
        return None
    if kind == 'lines':
        copies = [copy.deepcopy(s) for s in CLIPBOARD['data']]
        if not copies:
            return None
        strokes = list(w.drawing.strokes) + copies
        w.change_lines(strokes, keep={id(s) for s in copies}, current=len(strokes) - 1,
                       status=f'Pasted {len(copies)} line(s) at the end of the drawing order. Ctrl+Z takes them out.')
        return 'lines'
    if lines_only:
        return None
    import camera_clips
    t = w.video_seconds()
    if kind == 'camera':
        if len(w.scenes) > 1 and not w.all_scenes():
            w.preview_scope.setCurrentIndex(1)
        w.record_structure('paste camera clip')
        total = max(.5, w.video_length())
        last = None
        for item in CLIPBOARD['data']:
            clip = copy.deepcopy(item); clip['id'] = uuid.uuid4().hex[:10]
            clip['start'] = round(max(0., min(t, total - float(clip.get('duration') or .5))), 2)
            if not (clip.get('kind') in camera_clips.HAND_KINDS or camera_clips.fixed(clip)):
                clip['lane'] = camera_clips.free_lane(w.cameras, float(clip['start']), camera_clips.until(clip))
            w.cameras.append(clip); last = clip
        w.project_changes.mark_changed()
        w.select_camera(last['id'])
        w.status.setText(f'Pasted "{last.get("kind", "camera clip")}" at {last["start"]:.1f} s. Ctrl+Z takes it out.')
        return 'camera'
    if kind == 'overlays':
        if len(w.scenes) > 1 and not w.all_scenes():
            w.preview_scope.setCurrentIndex(1)
        items = CLIPBOARD['data']
        first = min(float(o.get('start', 0)) for o in items)
        w.record_structure('paste text')
        new_ids = []
        for item in items:
            twin = copy.deepcopy(item); twin['id'] = uuid.uuid4().hex[:10]
            twin['start'] = round(max(0., t + float(item.get('start', 0)) - first), 2)
            end = twin['start'] + float(twin.get('duration', 0))
            twin['track'] = _free_track(w.overlays, twin['start'], end, int(item.get('track', 0) or 0))
            w.overlays.append(twin); new_ids.append(twin['id'])
        w.selected_overlay = new_ids[-1]; w.selected_overlays = set(new_ids)
        w.project_changes.mark_changed()
        for name in ('sync_titles_timeline', 'sync_titles_choice'):
            if hasattr(w, name):
                getattr(w, name)()
        w.refresh()
        w.status.setText((f'Pasted "{items[0].get("name") or "clip"}"' if len(items) == 1 else f'Pasted {len(items)} clips') +
                         f' at {t:.1f} s. Ctrl+Z takes it out.')
        return 'overlays'
    if kind == 'element':
        k, start = w.playhead_slot()
        return 'element' if w.add_element_at(k, start, 'paste') else None
    return None

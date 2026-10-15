"""Image-only drawing/painting modes with synchronized temporary contour removal.

The original full-color source is always composited from its true pixels.
Paint Only uses the same unseen reconstruction geometry and region brush route
as Draw Then Paint. No post-paint cleanup or third animation phase exists.
"""
import numpy as np
import cv2
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from adaptive_hand import adaptive_paint_mask, plan_for, qimage


def original_frame(drawing, image, width, height):
    from color_reveal import artwork_rect
    frame=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    frame.fill(Qt.GlobalColor.transparent)
    painter=QPainter(frame)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(artwork_rect(drawing,image,width,height),image)
    painter.end()
    return frame


def _nearest_paint_timing(plan):
    """Painting time for each original source-grid cell and closest support.

    Contours aren't guaranteed to align perfectly with source PNG alpha.
    Outside-alpha line pixels inherit the time of their nearest paintable
    image cell, so outlines do not linger and pop off at the final frame.
    This extrapolation does NOT affect the actual colored source reveal.
    """
    cached=getattr(plan,'_contour_timing_field',None)
    if cached is not None:
        return cached
    gw,gh=plan.size
    painted_support=np.asarray(plan.labels,dtype=np.int32).reshape(gh,gw)>0
    if not painted_support.any():
        raise ValueError('No painted pixels available for contour synchronization.')
    times=np.asarray(plan.arrival,dtype=np.float64).reshape(gh,gw)
    missing=np.where(painted_support,0,1).astype(np.uint8)
    _,nearest=cv2.distanceTransformWithLabels(
        missing,cv2.DIST_L2,3,labelType=cv2.DIST_LABEL_PIXEL)
    lookup=np.full(int(nearest.max())+1,np.inf,dtype=np.float64)
    lookup[nearest[painted_support]]=times[painted_support]
    timing=lookup[nearest]
    if not np.isfinite(timing).all():
        raise ValueError('Contour cleanup requires a complete painting plan.')
    plan._contour_timing_field=timing
    return timing


def _contour_erase_mask(drawing,image,width,height,rect,progress,plan):
    """Retire temporary ink wherever the actual brush has reached nearby color.

    The nearest colored support extrapolates painting arrival to off-silhouette
    guide strokes. This is spatial synchronization, not a timed erase phase.
    """
    gw,gh=plan.size
    field=_nearest_paint_timing(plan)
    x=np.clip(((np.arange(width)+.5-rect.left())/max(.001,rect.width())*gw)
              .astype(np.int32),0,gw-1)
    y=np.clip(((np.arange(height)+.5-rect.top())/max(.001,rect.height())*gh)
              .astype(np.int32),0,gh-1)
    arrival=field[np.ix_(y,x)]*(.98/max(plan.total,1e-9))
    # Short local feathering (~1.5% of paint duration) prevents harsh
    # pixel-grid stepping while still following each actual brush arrival.
    strength=np.clip((float(progress)-arrival)/.015,0.,1.)
    alpha=Image.fromarray(np.asarray(np.rint(strength*255),dtype=np.uint8),'L')
    layer=Image.new('RGBA',(width,height),(255,255,255,0))
    layer.putalpha(alpha)
    return qimage(layer)


def paint_frame(drawing,image,width,height,progress,thickness,brush_width,
                stroke_spacing,painting_hand,hand_scale,anchor,show_outlines):
    """One uninterrupted painting phase: colors appear and guides retire together."""
    from color_reveal import artwork_rect, draw_hand
    from engine import render
    progress=max(0.,min(1.,float(progress)))
    if progress<=0:
        if show_outlines:
            return render(drawing,1,width,height,thickness,image_timing=False)
        empty=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        empty.fill(Qt.GlobalColor.transparent)
        return empty
    # Plan.mask(.98) is complete; no extra line-erasing time is added.
    if progress>=.98:
        return original_frame(drawing,image,width,height)
    rect=artwork_rect(drawing,image,width,height)
    mask,tip=adaptive_paint_mask(drawing,image,width,height,rect,progress,
                                 brush_width,stroke_spacing)
    result=original_frame(drawing,image,width,height)
    p=QPainter(result)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawImage(0,0,mask)
    p.end()
    if show_outlines:
        plan=plan_for(drawing,image,brush_width,stroke_spacing)
        guides=render(drawing,1,width,height,thickness,image_timing=False)
        p=QPainter(guides)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        p.drawImage(0,0,_contour_erase_mask(
            drawing,image,width,height,rect,progress,plan))
        p.end()
        p=QPainter(guides)
        p.drawImage(0,0,result)
        p.end()
        result=guides
    p=QPainter(result)
    draw_hand(p,tip,painting_hand,width,hand_scale,anchor)
    p.end()
    return result

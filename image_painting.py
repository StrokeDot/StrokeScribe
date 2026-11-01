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
    from source_render import draw_source
    draw_source(painter,artwork_rect(drawing,image,width,height),image)
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
    timing=np.where(painted_support,timing,
                    np.minimum(timing,_empty_area_timing(times,painted_support,plan.total)))
    plan._contour_timing_field=timing
    return timing


# exp.174 (the user: the painting looked finished but the lines were still there until the
# hand went back): lines where the picture is EMPTY (nothing will ever be painted there) used
# to wait for their single nearest painted spot, often one of the last small touches. Now they
# go once most of the picture around them is painted, and at the latest at this share of the
# painting.
EMPTY_REACH=.2          # around: this share of the picture's width
EMPTY_DONE=.6           # gone once this share of the picture around is painted
EMPTY_LATEST=.7         # and at the latest at this share of the painting
EMPTY_FEATHER=.08       # they fade out over this share of the painting (not a pop)


def _empty_area_timing(times,support,total):
    """For every cell: the moment EMPTY_DONE of the picture around it is painted."""
    gh,gw=support.shape
    reach=max(1,int(round(gw*EMPTY_REACH)))
    box=(2*reach+1,2*reach+1)
    around=cv2.boxFilter(support.astype(np.float32),-1,box,normalize=False,
                         borderType=cv2.BORDER_CONSTANT)
    when=np.full(support.shape,float(total)*EMPTY_LATEST)
    found=np.zeros(support.shape,bool)
    for t in np.linspace(0.,float(total)*EMPTY_LATEST,48)[1:]:
        painted=cv2.boxFilter((support&(times<=t)).astype(np.float32),-1,box,normalize=False,
                              borderType=cv2.BORDER_CONSTANT)
        reached=(~found)&(around>0)&(painted>=EMPTY_DONE*around)
        when[reached]=t; found|=reached
    return when


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
    painted_support=(np.asarray(plan.labels,dtype=np.int32).reshape(gh,gw)>0)[np.ix_(y,x)]
    empty=~painted_support
    strength[empty]=np.clip((float(progress)-arrival[empty]+EMPTY_FEATHER)/EMPTY_FEATHER,0.,1.)
    alpha=Image.fromarray(np.asarray(np.rint(strength*255),dtype=np.uint8),'L')
    layer=Image.new('RGBA',(width,height),(255,255,255,0))
    layer.putalpha(alpha)
    return qimage(layer)


def paint_frame(drawing,image,width,height,progress,thickness,brush_width,
                stroke_spacing,painting_hand,hand_scale,anchor,show_outlines,display_image=None):
    """One uninterrupted painting phase: colors appear and guides retire together."""
    from color_reveal import artwork_rect, draw_hand
    from engine import render
    visible=display_image if display_image is not None else image
    progress=max(0.,min(1.,float(progress)))
    if progress<=0:
        if show_outlines:
            return render(drawing,1,width,height,thickness,image_timing=False)
        empty=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        empty.fill(Qt.GlobalColor.transparent)
        return empty
    # Plan.mask(.98) is complete; no extra line-erasing time is added.
    from adaptive_hand import painting_done
    if painting_done(drawing,image,progress,brush_width,stroke_spacing):     # exp.182: at the last stroke
        return original_frame(drawing,visible,width,height)
    rect=artwork_rect(drawing,image,width,height)
    mask,tip=adaptive_paint_mask(drawing,image,width,height,rect,progress,
                                 brush_width,stroke_spacing)
    result=original_frame(drawing,visible,width,height)
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

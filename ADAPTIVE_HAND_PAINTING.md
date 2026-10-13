# Adaptive Hand Painting — experimental v0.6

Select **Adaptive Hand Painting** in Reveal mode after importing an SVG and its
matching original colored PNG. Drawing duration is unchanged. Reveal duration
is the painting duration; use 8–20 seconds initially, or longer for detailed art.
Brush width is a fraction of artwork width. Adaptive stroke spacing / width
ranges from 0.2 (more overlap) to 0.9 (less overlap). Show hand during painting
uses the existing hand PNG and pen contact anchor.

## What actually reveals color

Every revealed mask cell has a first-contact timestamp from a brush stamp on a
timed painting segment. The same segment and clock determine the visible hand
contact point. There is no flood fill of arrival times, diffusion, global fade,
or final whole-image reveal. Pen-up transfers never stamp and hide the hand.
The route starts at the endpoint of the final stroke in the user's current order.
If that point is outside PNG alpha, the first segment is a hidden transfer to the
nearest valid region: painting outside the source would violate the alpha constraint.

## Region planning

1. Build conservative alpha support on an artwork-relative grid (up to 224 pixels
   on the longest axis), retaining even tiny alpha components.
2. Rasterize sufficiently closed SVG contours and assign smaller interiors first.
   Split by 4-connected components. Open paths do not create invented enclosures;
   they fall back to PNG alpha connectivity.
3. Visit the nearest region from the current endpoint. Pick a horizontal or
   vertical infill direction from its shape. Alternate clipped scanline runs.
4. Shortest paths inside that region connect runs around holes and irregular
   edges. Adapt brush radius to distance from boundaries; narrow areas get
   small footprints and short passes. Brush footprints are also clipped to
   the selected region.
5. Audit coverage, then insert additional real brush paths through any missed
   cells. These are part of the same timeline, not a last-frame patch.
6. Finish all planned coverage at 98% and settle for the final 2%.

The raster grid and plan are independent of preview/export resolution. Plan cache
keys include PNG alpha, complete SVG geometry and order, and brush/spacing settings.
Original source RGB and alpha are used for rendering: no palette reduction or
color quantization. Output is clipped by original PNG alpha. During adaptive
painting, remaining SVG lines are alpha-clipped and removed where the brush paints,
preventing protruding black marks. Initial SVG rendering is untouched.

## Practical limitations and visual refinement

This is an experimental raster planner, not semantic recognition of illustration
parts. Open or mismatched contours can leave one large region. That region still
gets constrained infill, but its stroke direction may look mechanical. Planning
can block the UI briefly on complex art, and very fragmented alpha can be costly.
Tiny features and brush paths are grid approximations; narrow curves can look
stepped and a brush center may be within a partly transparent grid cell. The final
colored output always uses original PNG alpha, but perfect subpixel brush motion
is not promised. Radius limits can cause multiple passes near edges.

The SVG and PNG must have matching framing. Automatic alignment, color-based
semantic segmentation, brush texture, pressure, rotation, and a continuous
animation of lifting the hand are not implemented. A width/spacing or stroke-order
change rebuilds the plan. Zero reveal duration still means an intentional instant
transition, so choose a positive duration to see painting.

A useful future UI would let the user draw region polygons, split a region,
choose its hatch direction and priority, and preview pen-up links before export.
That would improve art direction without pretending every trace is a closed shape.

## Cloud validation and samples

The PR workflow runs the existing tests and new adaptive tests remotely on GitHub.
It produces an **adaptive-hand-painting-review** artifact containing transparent
PNG frames at 25%, 50%, 75%, and 100% painting progress, a white-background contact
sheet, the representative transparent source, and an experimental source ZIP.

The original colored headset PNG is **not in this repository**. Its traced SVG
is covered by a planning smoke test with a clearly synthetic color/alpha source.
That is not a visual headset result. Manual Windows testing with the user's real
headset PNG remains required, especially at the headband and microphone.

The existing Fade, Brush painting, Stroke-guided painting, Clean contour painting,
SVG rendering, optional hand, PNG exporter and ProRes encoder remain available.
No local Windows files are accessed by the cloud workflow.

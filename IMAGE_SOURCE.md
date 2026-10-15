# Image source: Line art

Choose **Image source → Import image…** (PNG, JPEG, WebP or BMP, up to 24 megapixels). StrokeScribe draws the image as pen strokes, then paints the original colours with the adaptive hand brush.

## Settings
- **Drawing style:** *Clean drawing* (default) draws fewer, longer, smooth strokes like an artist's drawing; shading and texture appear during the colour painting. *Detailed (all lines)* draws every line found.
- **Detail:** Low, Medium (recommended), High or Max. Higher detail draws more inner lines and takes a little longer to prepare.
- **Clean faint background leftovers:** removes pixels under ~25% visible that background removal often leaves behind, so neither the lines nor the hand go there.
- **Preserve original colors:** paint the original image after the drawing.
- **Apply image settings:** rebuild after changing settings.

## Export drawing as SVG
**Export drawing as SVG…** saves two files: `<name>_drawing.svg` (smooth, named paths in drawing order) and `<name>_drawing_color.png` (the image cropped to match). Edit the SVG in a free editor such as Inkscape (delete, redraw or reorder lines), then use **SVG source → Import SVG…** and **Load matching colored PNG…** with that PNG. The SVG stores its exact image frame, so the colour lines up perfectly.

## How Line art works
1. Work on the object itself (cropped from empty transparent canvas) at a size set by Detail.
2. Smooth textures while keeping edges, then find lines with the TEED line model (MIT, `models/teed.onnx`) plus directly detected dark ink lines.
3. Thin lines to their centres, trace them into strokes, join pieces that continue smoothly, link small gaps, and smooth the curves.
4. Order: outer outline, then long lines, then details, each starting near where the previous one ended.

The final frame is always the exact original image. Strokes are a reconstruction, not the artist's real drawing history. Pencil sketches and photos get a guide drawing; their shading appears during painting.

## Removed methods
Auto trace, Stroke reconstruction and AI redraw (local Ollama/Qwen) were removed in v0.5.3-experimental.22; Line art replaced them.

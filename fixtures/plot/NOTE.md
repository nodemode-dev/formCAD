# Plot fixtures

Made from `fixtures/sheet.fcad` through the plot engine (`app.output.plot.run`), then checked by reading the PDF content streams with pikepdf (scratch venv, not a repo dependency) and by rasterising with pdftoppm.

| File | Request | Result |
| --- | --- | --- |
| `sheet-layout1.pdf` | layout `Layout1`, sheet as set up (A3 landscape, 5 mm margins) | 1 page, MediaBox 1190.551 x 841.890 pt (420 x 297 mm), title block text drawn as strokes (the sheet's text style is a stroke font, so there is no embedded font), one optional content group per plotted layer |
| `sheet-model-1to50.pdf` | model space, A3, scale 1:50, offset 10,10, no centring | 1 page, same page size |

## Measured length

The model holds a closed polyline 4000 mm long on its long sides. At 1:50 it must be 4000 / 50 = 80.000 mm on paper.

- `sheet-model-1to50.pdf`: the longest stroked segment measures 80.000 mm (226.772 pt between the two end points).
- `sheet-layout1.pdf`: the viewport at 1:50 shows the same edge as 80.000 mm; the paper border is 180.000 mm and the title block frame 180 mm.

A 6000 mm line plotted at 1:50 gives 120.000 mm in both the model and the viewport path.

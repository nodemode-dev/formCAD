# Drafting and output

**Drafting.** The full 2D floor: draw, modify, arrays, hatch, text, dimensions with associativity, leaders and tables. Start with `line`, `circle`, `pline`; edit with `move`, `trim`, `offset`, `fillet`; annotate with `dimlinear`, `mtext`, `table`.

**Blocks and layouts.** `block` and `insert`, attributes (`attdef`, `attedit`), the Block Editor (`bedit`), external references (`xattach`), paper space (`layout`, `mview`, `pagesetup`).

**Plotting.** `plot` to PDF with layers and searchable text, PNG (`pngout`) and SVG (`svgout`); plot styles through `stylesmanager`.

**Interchange.** DXF R12 to R2018, SVG in, STEP AP203, AP214 and AP242 with semantic product manufacturing information, IGES and 3DM through the kernel, meshes STL, OBJ, PLY, 3MF and GLB. Use `import`, `export`, `open`, `saveas`.

**Limits.** DWG needs a converter you install. Mesh formats without units get a warning. A trimmed 3DM face is kept better by STEP. Details in the manual, chapters 2 to 4.

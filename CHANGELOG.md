# Changelog

Versions follow `v*.*.*`. Dates are UTC.

## 0.4.0 · 2026-11-02

- Every Modify command: erase and restore, move, copy, rotate, scale, mirror, stretch, offset, trim and extend (quick and standard), break, join, lengthen, align, reverse, fillet, chamfer, blend, explode, polyline and spline editing, nested copy, move-copy-rotate, change space and flatten.
- Selection by window, crossing, fence and polygons now follows the real shape of each object.
- Rectangular, polar and path arrays stay editable as one object; groups; match properties and the property commands; rename; linetype, colour and lineweight commands.
- The Properties palette, Quick Properties, QuickCalc, Find and Replace and Quick Select.
- Hatches and gradients with 23 patterns, island detection, gap tolerance and boundaries that the hatch follows when they move; boundary and region creation and region union, subtract and intersect; a hatch dialog with pattern swatches.
- Single-line and multiline text with an in-place editor, text styles, right-to-left text, Arabic joining, Thai and kerning.
- Every dimension type with styles, all dimension settings, 20 arrowheads, editing tools and dimensions that follow their objects; the Dimension Style Manager with a live preview.
- Leaders, multileaders, annotative scales, and tables with cell formulas such as SUM, merged cells and table styles.

## 0.3.0 · 2026-11-02

- The drawing area now draws: lines, arcs, circles, ellipses, polylines with widths, splines, points, text, fills and linetypes, in colour and lineweight, with a grid, axes, a crosshair, a view cube and a coordinate icon.
- Pan with the middle button or trackpad, zoom at the cursor with the wheel, double-click the middle button to see everything.
- Every Draw command works with all its options: line, construction line, ray, polyline, polygon, rectangle, arc (all eleven ways), circle (including tangent to two or three objects), donut, ellipse and elliptical arc, 2D solid, point, divide, measure, spline, helix, revision cloud, wipeout, 3D polyline, centre mark, centre line, multiline with styles and editing, and break line.
- Commands show a live preview while you pick points.
- Object snaps (endpoint, midpoint, centre, node, quadrant, intersection, apparent intersection, insertion, perpendicular, tangent, nearest, parallel, extension, geometric centre) with markers and tooltips; polar and object snap tracking, ortho, snap and grid, isometric drafting, typed distances along the cursor direction.
- Select by clicking, by window or by crossing; grips stretch, move, rotate, scale and mirror, with copies.
- Dynamic input shows coordinates, distances and angles next to the cursor.
- Text renders with an original single-stroke font or any installed TrueType or OpenType font, with every multiline text formatting code.
- A constraint solver for drafting and sketching reports under, fully and over defined geometry and names conflicting constraints.

## 0.2.0 · 2026-11-02

- FormCAD opens as a desktop app: a rounded splash, then the window appears whole with the FormCAD Home screen, title bar, menus and status bar.
- Home offers eight templates (2D drawings in millimetres or inches, part, assembly, drawing sheet, surface, form and graph) and lists recent files, projects and outputs.
- A docked command line takes commands with autocomplete, history, recall and clickable options; LINE, CIRCLE, ARC, PLINE, RECTANG, POINT, ERASE, MOVE, COPY, UNDO, REDO, SETVAR, LAYER and UNITS work with typed coordinates.
- The status bar switches grid, snap, ortho, polar, object snap, tracking, dynamic input and lineweight, and shows the 3D kernel's state.
- Preferences has seventeen sections with every drafting, display, selection, file and interface option; the theme follows the rest of the form family.
- Drawings save as .fcad files, keep a backup, autosave in the background and offer recovery after a crash.
- The 3D kernel runs as a separate program; in development it reports OpenCascade 8.0.1.
- The command palette (Ctrl or Cmd K) finds every interface and drafting command.

## 0.1.0 · 2026-11-02

- The repository starts: Apache-2.0 license with the NodeAgentc, Inc. copyright, notices, readme, editor and git settings, and the rules agents follow when they work on formCAD.
- No application code yet: the development plan is waiting for review.

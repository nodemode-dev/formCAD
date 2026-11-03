# Changelog

Versions follow `v*.*.*`. Dates are UTC.

## 0.12.0 · 2026-11-03

- A Manufacture workspace: setups with stock and work coordinates, a tool library of your own, feeds and speeds, and operations that regenerate when the model changes.
- Milling: face, pocket, contour with leads, adaptive clearing, drilling cycles, rest machining, and 3D parallel, waterline, scallop and adaptive roughing; NC output through post templates for LinuxCNC and grbl with a cycle time.
- Stock removal simulation with gouge marks, 3+2 indexing and simultaneous 5-axis on a table-table machine with collision checks.
- Turning, mill-turn setups, probing cycles, and laser, plasma, waterjet and router cutting with kerf, leads, pierce points and cut order; parts and flat patterns nested onto sheets.
- 3D printing: FormCAD's own slicer with perimeters, rectilinear, grid and gyroid infill, skins, supports, bridges, retraction and Marlin G-code, an orientation study, build plate arrangement, 3MF plates and a layer-by-layer preview; metal printing gets orientation, block supports and warnings.

## 0.11.0 · 2026-11-03

- Joints in assemblies: rigid, revolute, slider, cylindrical, pin-slot, planar and ball, with limits, as-built joints, joint links and drives.
- Motion studies on a timeline with plots of joint values, contact sets that stop the motion, and dynamics with gravity and contacts through MuJoCo in a job you can cancel (not available on Intel Macs).
- A local vault for your files: versions, branches, merges that list each conflict with both values, check-in and check-out with locks, lifecycle states and revisions, where-used, and comments and markup pinned to the model.
- Path-traced rendering in the 3D view, appearances and environments that name their sources, decals, turntables, and final images up to 4K rendered in the window, a hidden window or a headless browser.
- Storyboards from exploded steps, drives and camera moves, five technical illustration styles, and MP4 video export.

## 0.10.0 · 2026-11-03

- STEP files in the AP203, AP214 and AP242 schemas and IGES files carry names, colours, layers, assembly structure and units both ways; when a file's unit differs from the drawing's you choose to convert or keep the numbers.
- Product manufacturing information in 3D: dimensions, the fourteen geometric tolerance characteristics and datums attached to faces and edges, written to AP242 STEP and read back with a report of anything dropped.
- 3MF, GLB and PLY files, with a warning whenever a mesh format carries no unit.
- Form modelling: subdivision bodies with creases, primitives, forms from sketches, editing with soft selection and live symmetry, bridge and fill hole, converted to a closed solid with a continuity report.
- A mesh workspace: repair, self-intersection marks, reduce, remesh, plane sections, mesh booleans and mesh to solid with flat and cylinder face merging, each with progress and Cancel.
- Plastic parts: a rule set whose every value names its source, boss, rib, snap hook, lip and groove features, a wall thickness map and a checks report.
- Graph: the headless run takes a document, the editor reopens your last graph, and loops get scope, pass and collect settings.

## 0.9.0 · 2026-11-03

- Sheet metal parts: a rule for thickness, inside radius and bend method (K-factor, bend allowance, bend deduction or your own table); base, edge and miter flanges, closed, open, teardrop and rolled hems, jogs, bends along a sketch line, bend and corner reliefs, and converting a constant-thickness solid by finding its bends.
- Flat patterns: show and refold in place, bend lines marked up or down with angle and radius, cut list properties (blank size, area, cutting length, bend count), DXF export for laser cutting or for bending, and flat pattern views on drawings with bend notes.
- The graph: a node editor for building geometry from wired nodes, with data trees, item, list and tree access, longest, shortest and cross matching, graft, flatten, simplify and the other tree tools, and only the affected nodes recomputing when something changes.
- About 185 nodes: numbers, sliders, panels, toggles, buttons, value lists, maths and expressions, lists, sets, vectors, planes and transforms, curves, surfaces, solids, intersections, references to the open drawing and attributes; preview in the 3D view and bake into the drawing in one undoable step.
- Loops, an optimizer that tunes sliders to minimise or maximise a result, graphs run without the window from the command line, over HTTP or by an agent through MCP, `.graph` files, and node plugins that load like other plugins, with placeholders when one is missing.
- Fixes: pressing Enter at a file prompt from a macro or an agent now obeys the granted folders; detail views draw their boundary circle.

## 0.8.0 · 2026-11-03

- Analysis in the 3D view: zebra stripes, Gaussian and mean curvature, draft angle against a pull direction, deviation between surfaces or from points, and curvature combs, each with a colour scale you can edit.
- A gumball for moving, rotating and scaling with typed values, a pivot you can relocate and align, and 3D object snaps.
- 3DM files: open and save through the kernel, with curves and untrimmed surfaces kept exactly; trimmed faces are written as a surface plus its trim curves with a warning that STEP keeps them better.
- Meshes: from solids or files, weld, unify normals, fill holes, show naked edges; STL and OBJ read and write.
- Assemblies: components from part files or embedded parts, sub-assemblies, missing and changed file handling that never takes a change silently, patterns that follow part features, configurations and a bill of materials with fixed find numbers.
- Mates: thirteen kinds with degrees of freedom shown per component and an explanation when mates conflict; drive or drag a mechanism, exploded views with steps, interference and clearance checks.
- Drawings from 3D on the layout sheets: projected views in first or third angle, auxiliary, section, detail, broken and cropped views that update with the model; dimensions that follow the model, model items, centre marks, section hatching, geometric tolerance frames and datums drawn from FormCAD's own symbols, balloons, a BOM table and a title block filled from the document.
- Splitting and copying bodies now stay through a rebuild; curve drag previews come from the engine.

## 0.7.0 · 2026-11-02

- A new app icon on the desktop app, the browser tab and the splash, and a README in the form family layout.
- Parametric parts: a feature tree with a rollback bar, suppress, reorder, rename and errors that never lose the tree; sketches on planes and faces; extrude and revolve with every end condition; fillet, chamfer, shell, draft, linear and circular patterns and mirror; references that survive edits upstream.
- Sweep, loft, boundary solids, ribs and a hole builder (simple, counterbored, countersunk and tapped holes). Its size table ships with 24 coarse thread pitch rows from one public standard copy, each marked with its source and status; clearance, counterbore, countersink and tap drill sizes are left for you to fill in, because no free primary source for them could be read.
- Multibody parts, reference planes, axes, points and coordinate systems, configurations, design tables, a materials library with sources, and mass properties about any coordinate system.
- NURBS curves: by control points or through points, rebuild, fit, degree and knot editing, offset, extend, match, and blend curves up to G3, with a continuity report.
- Surfaces: loft, one and two rail sweeps, network, patch, edge, planar, blend and match surfaces to G2, extend, offset, trim, split and join; fillet, chamfer and blend edges; booleans that explain why they failed and show naked edges; a seam continuity check with G0, G1 and G2 badges in the 3D view.
- A model tolerance setting used by every 3D operation.
- Fixes: construction planes and the 3D grid are computed by the engine; installed-package plugins are checked by hash; VPORTS 4 always makes four tiles; layout tab menus update in place.

## 0.6.0 · 2026-11-02

- A built-in LISP language: type expressions at the command line, load routines with APPLOAD, run commands from routines, with file access limited to the support folders you choose and runaway routines stopped.
- Scripts (.scr) with progress, stop and resume; your own command aliases; a macro recorder that saves what you do as a script or a Python macro.
- Python macros that run in a separate, limited process after you trust each file.
- FormCAD as an MCP server for agents such as Claude Code, over stdio or HTTP, with a tool for every command; a local control protocol; a command-line tool that converts and runs files without the window.
- Plugins from a folder or from installed packages, off until you enable each one and checked against their file hashes.
- Inquiry and file commands: LIST, STATUS, TIME, COUNT, NEW, CLOSE, SAVE, AUDIT, RECOVER and COMPARE.
- A 3D view: open STEP and IGES files, create boxes, cylinders, spheres, cones, tori and extrusions, combine them, measure mass properties, and view them wireframe, shaded, with edges, hidden line, ghosted, x-ray or technical, with orbit, a view cube, named views and construction planes.
- Parametric constraints on drawings and sketches: geometric and dimensional constraints, auto-constrain, status colours, a conflict explainer that refuses over-defining dimensions, and a Parameters Manager with equations and units.
- Layouts from template files; Named Viewports shows the configuration you pick; a wider layer manager in viewports; several fixes to TRIM, ARRAYPOLAR, DIMLINEAR and MLEADER.

## 0.5.0 · 2026-11-02

- Blocks with base points, insertion at any scale and rotation, exploded insertion, writing a block to its own drawing, purge, replace and burst; attributes with prompts, defaults, display modes, editing, synchronising and the Block Attribute Manager; attribute data extraction to CSV.
- The Block Editor with dynamic block parameters and actions, in-place reference editing, and external references to other drawings with relative, absolute or no paths, nesting, reload, unload, bind and clipping.
- Layers completed: every property, filters, layer states, and the layer tools (isolate, freeze, lock, merge, delete, walk, previous and more); the Layer Properties Manager and a Layers panel.
- Layouts with paper sizes, margins and page setups; viewports with their own scale, lock, clipping and per-viewport layer overrides; switching between paper and model space; named views and tiled model viewports.
- DXF open and save from R12 to R2018, keeping layers, blocks, attributes, layouts and viewports; SVG and SVGZ import; DWG open and save through a converter you install yourself.
- Plotting to PDF (several sheets, layers you can switch in the viewer, searchable text, links), PNG at a set resolution and SVG in millimetres, with colour-dependent and named plot styles, page setups, plot preview and publishing several layouts at once.
- The Properties palette now asks the engine to change lengths, angles and areas, and Quick Select runs in the engine.
- Stretch with a crossing window drawn on the canvas now moves only the points inside it.

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

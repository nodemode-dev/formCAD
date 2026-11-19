# Changelog

Versions follow `v*.*.*`. Dates are UTC.

## 0.18.1 · 2026-11-19

- The Mac builds are accepted by Apple's notary. Both Mac builds of 0.18.0 were refused for two files, the engine's Python library as it was reached through two links: the library was signed inside its framework and then shipped as two plain copies outside it. The engine now leaves the freeze on macOS with the library as one regular file, no framework and no links, and is signed after that. Linux and Windows builds are unchanged.
- Nothing in the app itself changed since 0.18.0.

## 0.18.0 · 2026-11-19

- AMOLED Black, a true-black theme for OLED screens: the window, the panels, the drawing canvas and the 3D view are `#000000`, and panels are told apart by their borders. It is in Preferences with the other themes and paints black from the first frame of a reload.
- The tools on the left rail are grouped as in the rest of the family: 16 groups in four clusters, one button per group showing its current tool, and a flyout on press and hold or right click that lists the group's tools with their shortcuts. The chosen tool is remembered per group. Every tool that was on the rail is still there.
- The empty row between the document tabs and the canvas is gone. The array bar that used it now floats over the top edge of the canvas only while an array is edited, and the canvas no longer moves when it appears. Window > Tool Bar, which toggled that row, is removed.
- Drawing surfaces follow the theme properly: the 2D canvas, the 3D view, the render preview and the ECAD views repaint in the same frame as a theme change, the grid stays visible on black, the 3D selection highlight is the same blue as in 2D, and the `THREE.Color` warnings on every document are gone.
- The interface passes the family design-language audit: the ECAD colours moved into the token sheet and two stray literals are tokens.
- A drawing opened while the engine was still answering for another document could show an empty canvas until the next zoom: the request for the new document was dropped. The canvas now always goes on to the document that is active.
- The registry entry signs Mac builds with `apple` (Developer ID signature plus notarization), as formcompiler 0.16.0 requires of every app. The first Mac builds of this app are therefore also its first notarization.
- Known and open: in the packaged Linux build on a virtual display with software rendering, a demo opened from the home shows the grid only until the first wheel step or zoom extents. The cause is not found; it is not the fault above. `frontend/HASHOUT_LOG.md`, entry R24, has what is known.

## 0.17.0 · 2026-11-18

- The first build through formcompiler. The registry file passes its check and builds in contract mode for Apple silicon, Intel Macs, Linux and Windows; the release stays a draft on this repository. The Linux AppImage no longer stops on the physics library's plugin files, and `formCAD.bat desktop build` passes its arguments on.
- The splash bar carries the family gradient. On macOS a window whose page stops twice within two minutes offers Restart FormCAD or Quit, and the engine now exits with the shell even when its launcher was force-closed.
- The home screen follows the family layout: the formCAD mark, Start, Recent, Templates, Projects and Outputs, a list of open drawings, and a Demos section.
- Three demos open from the home screen as untitled copies: a dimensioned floor plan on an A3 sheet, a parametric plate with its feature tree, and a node graph that drives a plate with a ring of bolt holes. The part and the graph show without the 3D worker; editing them needs it.
- Three browser demos, `demo/`, `demos/part/` and `demos/graph/`: the real window over a recording of the engine, opened from `index.html` with no install and no network.
- The kernel and mesher workers are downloaded from the `formcad/` releases of nodemode-dev/formai-binaries. No worker release exists yet, so 3D editing and simulation wait for the first one.

## 0.16.2 · 2026-11-04

- A README in the Form family layout with screenshots of the part, drawing sheet, node graph and NURBS views.
- The manual, the wiki and the skill packs now state the current version.

## 0.16.1 · 2026-11-03

- The unified app icon for the desktop window, the web favicon and the README, and the family icon set.
- Co-ownership of the repository is recorded in the code owners file.

## 0.16.0 · 2026-11-03

- Two agent skill packs: `skills/formcad-harness` for agents that install, run, verify and extend FormCAD, and `skills/formcad-driving` for agents that operate it through its MCP server and command line, both passing the skill validator.
- A user manual (`docs/MANUAL.md`) covering every workspace, and a wiki (`.docs/wiki/`) on getting started, the architecture, each workspace group, automation and agents, building and releasing, licensing and data provenance, and contributing.
- Workspace panels load their data only when shown and only for the documents they serve, so editing a board or a part no longer waits on every other workspace.

## 0.15.0 · 2026-11-03

- Weldments: structural members from your own profile sketches along a frame of lines, with miter, butt, cope and trim corners, gussets and end caps, and a cut list with both cut angles placed as a table on a drawing.
- Mold tools: draft and undercut colours for a pull direction, a parting line, shut-offs for through holes, a mold block split into core and cavity with a volume check, and shrinkage.
- A toolbox of screws, nuts, washers, pins, bearings and structural shapes built from the sizes you enter or import from your own table, inserted into assemblies with their mates.
- Inspection: numbered characteristics from product manufacturing information and drawing dimensions, balloons and a first-article style report; saved model-based views.
- Cost estimates from material, machine time, setup and tooling, manufacturability checks for machining, sheet metal, printing and molding, a design checker for your own rules, and a carbon estimate from factors you enter.
- Release preparation: the binaries repository layout with checksums and the source offer, signing scripts, release workflows and the family registry files, ready to publish.

## 0.14.0 · 2026-11-03

- Generative design: preserved and obstacle regions, loads, a safety factor target and manufacturing methods (3D printing, milling, cutting, casting), giving several outcomes with mass and safety factor that you can apply as mesh or solid bodies.
- Electronics: schematic capture with generated symbols, hierarchical sheets, buses and electrical rule checks; boards with layers, footprints from FormCAD's own land pattern generator, tracks, vias, copper pours with thermal reliefs, design rule checks with fabricator profiles that name their sources, and a two-layer autorouter.
- Board outputs: Gerber X2, Excellon drill, IDF, a 3D board for assemblies, an outline kept in step with an enclosure part, and KiCad files on request.
- Harnesses routed through clips with bend radius checks, flattened to a formboard drawing with wire lists and from-to tables.
- Tube and pipe runs with bend tables for benders, generated fittings and cut lists, and electrical schematics numbered and matched to the harness wires.

## 0.13.0 · 2026-11-03

- A Simulation workspace: studies on parts and assemblies with materials that name their sources, loads, fixtures, contacts and mesh controls, meshed by a separate mesher program, with contour plots, deformed shapes, animation, probes, sections and reports.
- Linear static stress, modal frequencies, heat conduction, thermal stress and linear buckling on curved second-order elements, in jobs you can cancel, with memory checked before a solve.
- First versions of nonlinear statics with plasticity and rubber-like materials, contact, quasistatic and dynamic events, fatigue life from S-N curves, and laminated composites, each checked against a published or analytic case.
- Topology optimization with preserved regions, symmetry and a stress check that keeps the result under your limit, turned into a mesh body; basic shape optimization.
- Flow: laminar pipe and duct flow on FormCAD's own solver, an optional link to SU2 if you install it, electronics cooling, duct pressure loss, and injection fill time with pack and warp shown as estimates.

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

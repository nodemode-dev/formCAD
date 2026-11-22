# FormCAD user manual

This manual covers every workspace of FormCAD v0.24.0. Each chapter says what the workspace does, how to start, the main commands, and the limits, stated plainly. Command names are the ones you type at the command line of the window (case does not matter); each exists in the engine's command catalogue. `./formCAD` is the dispatcher script at the repository root; on Windows use the `.bat` files.

Where a chapter says "a first version", it means the feature works end to end on the cases it was checked against, and nothing more is promised. Where a number is an estimate, the interface labels it so.

## Contents

1. Conventions and first steps
2. Drafting
3. Blocks and layouts
4. Plotting and interchange
5. Automation: LISP, scripts, macros, plugins, CLI, MCP
6. Parts
7. Sheet metal
8. Surfaces and forms
9. Meshes and plastic parts
10. Assemblies
11. Joints and motion
12. Drawings
13. The graph
14. The vault
15. Render and animation
16. Manufacture and print
17. Simulation
18. Generative design
19. Electronics
20. Routing: harnesses, tubes and schematics
21. Weldments and molds
22. Toolbox
23. Inspection and costing
24. Limits that apply everywhere

## 1. Conventions and first steps

A FormCAD project is one `.fcad` file. It holds the drawing database, the part feature trees, assemblies and every record the workspaces add (studies, setups, boards, runs). Undo and redo cover all of it: most workspace settings live in the document header, so a change you undo stays undone after saving and reopening.

**Starting.** Run `./formCAD_oc_install` once, then `./formCAD` to boot the engine and the interface together. Run `./formCAD install-kernel` if you want 3D: the OpenCascade worker is a separate program, and without it only 2D and mesh work run. The simulation mesher is a second separate program (`./formCAD install-mesher`). `./formCAD doctor` checks the toolchain, the installs and the ports.

**The command line.** Press the command key, type a name, and answer the prompts. Most commands also take a JSON argument form when called from a script, a macro or an agent. `commands` through the CLI prints the catalogue.

**Units.** A drawing has units. Workspaces that compute (simulation, costing, manufacturing) store SI or millimetres internally and say which they show. When an imported file's unit differs from the drawing's, you are asked to convert or keep the numbers.

**Honest limits of the whole app.**

- The Linux build is the tested one. macOS and Windows builds are configured and untested here.
- Hardware GPU timings for rendering are not measured.
- Dynamics (joints and motion) is unavailable on an Intel Mac, because the physics library publishes no wheel for it. Everything else works there.
- Programs that FormCAD can talk to but never ships (a DWG converter, a flow solver, an electronics suite) are optional; each chapter that mentions one says it is off until you point FormCAD at your own install.

## 2. Drafting

**What it does.** The full 2D floor: lines, circles, arcs, polylines, rectangles, polygons, ellipses, splines, hatch and gradient with islands, regions, text and multiline text with right-to-left shaping, 69 dimension variables with associative dimensions, multileaders and tables with formulas.

**How to start.** Open a new drawing (`new`, `qnew`) and type `line`. Object snaps, tracking, polar, ortho, isometric drafting and dynamic input are toggled from the status bar (`dsettings`, `isodraft`, `isoplane`).

**Main commands.**

- Draw: `line`, `circle`, `arc`, `rectang`, `pline`, `polygon`, `ellipse`, `xline`, `ray`, `spline`, `helix`, `donut`, `point`, `divide`, `measure`, `mline`, `revcloud`, `wipeout`.
- Modify: `move`, `copy`, `rotate`, `scale`, `mirror`, `stretch`, `align`, `trim`, `extend`, `offset`, `break`, `fillet`, `chamfer`, `blend`, `join`, `lengthen`, `explode`, `pedit`, `splinedit`, `erase`, `oops`.
- Arrays: `arrayrect`, `arraypolar`, `arraypath`, `array`, `arrayedit`.
- Hatch: `hatch`, `gradient`, `hatchedit`.
- Text and tables: `text`, `mtext`, `textedit`, `style`, `table`, `tabledit`, `tableexport`, `datalink`.
- Dimensions: `dimlinear`, `dimaligned`, `dimradius`, `dimdiameter`, `dimangular`, `dimordinate`, `dimbaseline`, `dimcontinue`, `qdim`, `dimstyle`, `dimedit`, `dimregen`.
- Leaders: `leader`, `mleader`, `mleaderedit`, `mleaderstyle`.
- Layers and properties: `layer`, `laycur`, `layiso`, `layuniso`, `layerstate`, `properties`, `chprop`, `matchprop`, `linetype`, `lweight`, `color`.
- Selection and inquiry: `select`, `qselect`, `find`, `list`, `dist`, `id`, `count`, `measuregeom`, `cal`.
- Sketch constraints: `sketch`, `geomconstraint`, `dimconstraint`, `autoconstrain`, `parameters`, `constraintstatus`.
- Settings: `setvar`, `getvar`, `units`, `zoom`.

**Limits.** Grips work in five modes; dynamic blocks are covered in the next chapter. The constraint solver is FormCAD's own and refuses a dimension that would over-define a sketch, naming the conflict. Very large drawings are fine to a point; the performance fixture holds 100,000 lines and `formcad-engine perf` times your own.

## 3. Blocks and layouts

**What it does.** Blocks with attributes and the Block Editor, dynamic blocks, in-place editing of blocks and references, external references with relative paths, nesting and clipping, and paper-space layouts with viewports that carry their own scale and layer overrides.

**How to start.** Make a block from selected objects with `block`, place it with `insert`. For a layout, use `layout`, then `mview` to cut a viewport.

**Main commands.**

- Blocks: `block`, `insert`, `base`, `blockreplace`, `burst`, `blockspalette`, `bedit`, `bsave`, `bsaveas`, `bclose`, `refedit`, `refset`, `refclose`, `purge`, `wblock`.
- Attributes: `attdef`, `attedit`, `attdisp`, `attsync`, `battman`, `dataextraction`.
- External references: `xattach`, `xref`, `xbind`, `xopen`, `xclip`.
- Layouts: `layout`, `pagesetup`, `mspace`, `pspace`, `mview`, `vpclip`, `vplayer`, `vpmax`, `vpmin`.
- Annotation scale: `scalelistedit`, `objectscale`, `annoreset`, `annoupdate`.

**Limits.** External references resolve through relative paths first; a missing file is reported and drawn as a placeholder, never silently dropped.

## 4. Plotting and interchange

**What it does.** Plot to PDF (with layers and searchable text), PNG and SVG; read and write DXF from release 12 to 2018, read SVG, exchange STEP (AP203, AP214, AP242 with semantic product manufacturing information), IGES and 3DM through the kernel, and mesh formats STL, OBJ, PLY, 3MF and GLB. DWG goes through a converter you install yourself.

**How to start.** `plot` opens the plot flow; `export` and `import` handle other formats; `open` and `saveas` choose the format by extension.

**Main commands.** `plot`, `exportpdf`, `pngout`, `svgout`, `publish`, `preview`, `stylesmanager`, `plotstyle`, `plottermanager`, `export`, `import`, `open`, `saveas`, `info3dm`, `pmidim`, `pmitol`, `pmidatum`. Routes: `GET /api/interchange/formats`, `POST /api/interchange/inspect`, `POST /api/docs/{doc_id}/interchange/export`, `POST /api/docs/{doc_id}/plot`.

**Limits.**

- 3DM: curves and untrimmed surfaces are kept exactly. A trimmed face is written as a surface plus its trim curves, with a warning; STEP keeps trimmed faces better.
- Mesh formats that carry no unit (STL, OBJ) produce a warning on every import and export.
- DWG needs a converter at a path you configure (`GET /api/interchange/dwg`); without it DWG files are refused with a message.
- A STEP file that carries something FormCAD cannot represent is read with a report of what was dropped.

## 5. Automation: LISP, scripts, macros, plugins, CLI, MCP

**What it does.** Five ways to drive the engine without clicking, plus an agent protocol.

- **LISP**: a dialect with 188 builtins. Load with `appload`, open the console with `lispconsole`, run with `lisp`.
- **Scripts**: lists of commands as text. `script`, `rscript`, `delay`, `resume`.
- **Macros**: record what you do (`macrorecord`, `macrostop`, `macrosave`, `macroplay`, `macrorecorder` panel). Python macros run in a separate process with a scrubbed environment, a time limit, resource limits, and a guard on files, network, subprocesses and native code. Each macro's trust is bound to the hash of its source; edit it and trust is gone.
- **Plugins**: a folder with `plugin.json` listing a hash per file, found through `formcad.plugins` entry points or the data folder. Nothing is imported at discovery; `pluginenable` stores the manifest hash, and a plugin that changed since is not loaded. `plugins` lists them.
- **The CLI**: `formcad-engine info`, `convert`, `run`, `commands`, `mcp`, `perf`, `sample`, `plugin seal`, `plugin list`, `macro list`, `graph run`, `graph io`, `graph optimize`. Exit codes: 0 success, 1 a command failed, 2 usage error (graph runs add 3 missing node type, 4 timeout, 5 cancelled).
- **MCP**: `./formCAD mcp` serves the engine over standard input and output; an HTTP endpoint `POST /mcp` sits behind the session token. By default it lists the fixed `formcad_*` tools and the `cmd_*` tools for the common drafting commands; every other command runs through `formcad_execute`, and `--tools all` lists one `cmd_*` tool per command. `formcad_status` reports whether the kernel and the mesher are installed and which folders an agent may use; a study or a toolpath run is started with `formcad_sim_start` or `formcad_cam_start` and followed with `formcad_job_status`. `GET /api/automation/status` returns the exact lines to register it with your agent.

**How to start.** Open the Automation panels from the Window menu, or run `./formCAD mcp` and register it with your agent with the line the status route gives.

**The trust model in one paragraph.** The window is the highest trust class: you are there, typing. Macros and MCP agents are lower. Commands and routes that read or write files, start processes or change settings are classified: some are barred outright for macros and agents (settings, material libraries, plugin enabling, vault creation and lifecycle, converter paths), some are allowed only inside folders you granted. A typed prompt that wants a file says the word file. Details are on the wiki page Automation-and-Agents.

**Limits.** The Windows job-object guard for macros is written and not run. Agent callers get lower size caps than the window on every computing job. A macro cannot enable a plugin; an agent cannot either.

## 6. Parts

**What it does.** Parametric solid parts on the OpenCascade kernel: a feature tree with rollback, suppress and rebuild; 20 feature types; references that survive upstream edits; multibody parts; reference geometry; configurations; design tables; materials; mass properties.

**How to start.** `partworkspace` enters the part workspace, `partsketch` starts a sketch on a plane or face, `partsketchdone` finishes it, then a feature command.

**Main commands.** `featextrude`, `featcut`, `featrevolve`, `featrevolvecut`, `featadd`, `features`, `featedit`, `featdelete`, `featsuppress`, `featunsuppress`, `featrollback`, `featrebuild`, `featforcerebuild`, `combine`, `splitbody`, `movecopybody`, `refgeo`, `config`, `designtable`, `material`, `materiallib`, `bodymass`, `massprop`; primitives `box`, `cylinder`, `sphere`, `cone`, `torus`, `extrude`; edge work `filletedge`, `chamferedge`, `blendedge`; booleans `boolop`, `boolcheck`.

**Limits.** Needs the kernel worker. The materials that ship have cited values; where no cited value exists the table is empty and yours to fill. A failed feature is marked with its reason and later features wait; it never silently changes the model. Holes have their own router (`/api/holes`) and take sizes you enter.

## 7. Sheet metal

**What it does.** A rule (thickness, inside radius, bend method: K-factor, allowance, deduction or your own table), base, edge and miter flanges, hems (closed, open, teardrop, rolled), jogs, sketched bends, reliefs, conversion of a constant-thickness solid, flat patterns with bend lines and notes, and a flat DXF for cutting or bending.

**How to start.** `smrule` to see or set the rule, then `smbaseflange` from a sketch.

**Main commands.** `smbaseflange`, `smedgeflange`, `smmiterflange`, `smhem`, `smjog`, `smsketchbend`, `smbendrelief`, `smcornerrelief`, `smconvert`, `smrule`, `smtable`, `smcheck`, `smbends`, `flatpattern`, `flatexport`.

**Limits.** Bend tables are yours; no standard table ships. Conversion finds bends in constant-thickness bodies only. Flat-pattern accuracy depends on the bend data you give; FormCAD does not claim it matches a particular press brake.

## 8. Surfaces and forms

**What it does.** NURBS curves (build, interpolate, fit, rebuild, blend to G3, match, offset, extend), surfaces (loft, sweep, network, patch, extrude, revolve, blend and match to G2, trim, join), analysis (zebra, curvature, draft, deviation, curvature comb), a gumball, and subdivision forms with creases converted to closed solids.

**How to start.** `crv` or `srfloft` for NURBS; `subdbox` for a form; `analysisramp` and `zebra` for analysis.

**Main commands.**

- Curves: `crv`, `crvinterp`, `crvfit`, `crvrebuild`, `crvdegree`, `crvblend`, `crvmatch`, `crvoffset`, `crvextend`, `crvcont`.
- Surfaces: `srfloft`, `srfsweep`, `srfnetwork`, `srfpatch`, `srfextrude`, `srfrevolve`, `srfplanar`, `srfedge`, `srfblend`, `srfmatch`, `srfextend`, `srfoffset`, `srfsplit`, `srftrim`, `srfjoin`, `seamcheck`, `nakededges`, `surfreport`, `modeltol`.
- Analysis: `zebra`, `curvatureanalysis`, `draftanalysis`, `deviation`, `curvaturecomb`, `analysisoff`, `analysisramp`.
- Forms: `subdbox`, `subdcylinder`, `subdsphere`, `subdtorus`, `subdextrude`, `subdrevolve`, `subdinsertedge`, `subddivideface`, `subdcrease`, `subdbridge`, `subdfillhole`, `subdsymmetry`, `subddisplay`, `subdconvert`, `subdinfo`.
- Gumball: `gumball`.

**Limits.** Conversion of a form to a solid reports continuity and fails with a reason if the cage cannot close. Blends reach their stated continuity only within the model tolerance (`modeltol`); the badge on a seam says what was measured.

## 9. Meshes and plastic parts

**What it does.** A mesh workspace (repair, self-intersection marks, reduce, remesh, plane sections, booleans, mesh to solid with flat and cylinder face merging) and plastic part rules (wall thickness, bosses, ribs, snap hooks, lips, grooves) with checks.

**How to start.** `meshfromsolid` makes a mesh; `meshrepair` and `meshreport` follow. For plastic, `plasticrule` then `wallthickness`.

**Main commands.** `meshfromsolid`, `meshweld`, `meshunify`, `meshfill`, `meshnaked`, `meshreport`, `meshrepair`, `meshselfx`, `meshreduce`, `meshremesh`, `meshsection`, `meshboolean`, `meshtobrep`; `plasticrule`, `plasticboss`, `plasticrib`, `snaphook`, `plasticlip`, `plasticgroove`, `plasticcheck`, `wallthickness`.

**Limits.** Every mesh job has size caps checked before it starts, with lower caps for macros and agents; each has progress and Cancel. Mesh to solid on a noisy scan can produce many faces; the report says how many. Every plastic rule value names its source; where none is cited you enter your own.

## 10. Assemblies

**What it does.** Components that reference part files by safe relative paths, mates (13 kinds) with degree-of-freedom counts and conflict explanations, patterns, configurations, exploded views, interference checks and a bill of materials.

**How to start.** `asminsert` to place a component, `mate` to constrain it.

**Main commands.** `asminsert`, `asmremove`, `asmmove`, `asmflags`, `asmreload`, `asmreplace`, `asmfind`, `asmrebase`, `asmembed`, `asmpattern`, `asmconfig`, `asmbom`, `asmsearch`, `asmrefresh`, `mate`, `mateedit`, `matedelete`, `matesolve`, `matestatus`, `matedrag`, `explodeview`, `interfere`, `interferesweep`, `matesettings`. The file contract is in `docs/ASSEMBLY_SCHEMA.md`.

**Limits.** Interference checks grow with the number of pairs and are capped; a large assembly is checked in sweeps. A component file outside the granted or document folders is refused.

## 11. Joints and motion

**What it does.** Joints (rigid, revolute, slider, cylindrical, pin-slot, planar, ball) with limits and drives, as-built joints, joint links, motion studies on a timeline with plots, contact sets that stop motion, and dynamics with gravity and contacts through MuJoCo in a job you can cancel.

**How to start.** `joint`, then `motionstudy`.

**Main commands.** `joint`, `jointedit`, `jointdelete`, `jointdrive`, `jointlink`, `jointlinkdelete`, `motionstudy`, `contactset`, `dynamics`, `motionsettings`. Routes: `GET /api/docs/{doc_id}/motion`, `POST /api/docs/{doc_id}/motion/dynamics/run`.

**Limits.** Dynamics is unavailable on Intel Macs. Results are only as good as the masses and contact settings you give; FormCAD checks the cases it ships with against analytic results and says no more.

## 12. Drawings

**What it does.** Drawing views from 3D in first or third angle: base, projected, auxiliary, section, detail, broken and cropped views that update with the model; dimensions that follow the model; tolerance frames, datums, balloons, bills of materials, title blocks, center marks and section hatching.

**How to start.** On a layout, `viewbase`, then `viewprojected`.

**Main commands.** `viewbase`, `viewprojected`, `viewaux`, `viewsection`, `viewdetail`, `viewbroken`, `viewcrop`, `viewupdate`, `viewedit`, `viewdelete`, `viewprojection`, `viewdim`, `modelitems`, `gdtframe`, `gdtedit`, `datumsym`, `balloon`, `autoballoon`, `bomtable`, `bomupdate`, `bomexport`, `titleblock`, `docprops`, `centermarks`, `sectionhatch`, `finishmark`.

**Limits.** Views come from hidden line removal, not a rendering of the model; very dense models take a while and show a progress bar. Standards frames are drawn from geometry rules you can inspect; no standard's text is reproduced.

## 13. The graph

**What it does.** A node editor for building geometry from wired nodes, with data trees and matching, about 185 nodes, preview in the 3D view, bake into the drawing in one undoable step, loops, an optimizer, `.graph` files, node plugins, and headless runs.

**How to start.** `graph` opens the editor. From a terminal: `formcad-engine graph run FILE.graph --out json`.

**Main commands.** `graph`, `graphrun`, `graphimport`, `graphexport`, `graphbake`, and the CLI `graph run`, `graph io`, `graph optimize`. Formats: `docs/GRAPH_FORMAT.md`; writing nodes: `docs/NODE_SDK.md`.

**Limits.** Runs have a time budget and node-count caps; the optimizer runs in a cancellable job and takes a budget. A graph that uses a node type you lack opens with placeholders rather than failing.

## 14. The vault

**What it does.** A local, content-addressed store for your files: versions, branches, tags, diffs, merges that list every conflict with both values, check-in and check-out with locks, lifecycle states and revisions, where-used, comments pinned to the model, verify and garbage collection.

**How to start.** `vaultcreate`, then `vaultcheckin` on a document.

**Main commands.** `vaultcreate`, `vaultcheckin`, `vaultcheckout`, `vaultundo`, `vaultlog`, `vaultbranch`, `vaulttag`, `vaultdiff`, `vaultmerge`, `vaultlock`, `vaultstate`, `vaultrevise`, `vaultwhereused`, `vaultcomment`, `vaultpin`, `vaultverify`, `vaultgc`. Routes under `/api/vault`.

**Limits.** The vault is local; it is not a server and does not sync between machines. Macros and agents cannot create a vault, change lifecycle state, revise or collect garbage.

## 15. Render and animation

**What it does.** Path-traced rendering in the 3D view, appearances and environments that name their sources, decals, turntables, final images up to 4K in the window, a hidden window or a headless browser, storyboards from exploded steps, drives and camera moves, five technical illustration styles, and MP4 video export.

**How to start.** Switch the 3D view to render mode, set quality, press render. Storyboards are made from the Animation panel.

**Main commands.** Rendering and storyboards are driven from the interface and these routes: `GET /api/render/library`, `POST /api/docs/{doc_id}/renderjobs`, `GET /api/render/jobs/{job_id}`, `GET /api/docs/{doc_id}/storyboards`, `POST /api/docs/{doc_id}/storyboards/from-explode`.

**Limits.** Render speed depends on your graphics hardware; no GPU timings are claimed. Environment images are downloaded on request and carry their licences. Video export uses a muxing library under MPL-2.0 used unedited.

## 16. Manufacture and print

**What it does.** Setups with stock and work coordinates, a tool library of your own, feeds and speeds, 2D and 3D milling, 3+2 and simultaneous 5-axis with stock removal simulation and collision checks, turning, probing, laser, plasma, waterjet and router cutting with nesting, NC output for LinuxCNC and grbl, and FormCAD's own slicer with supports, orientation study, plate arrangement and a layer preview.

**How to start.** `camsetup`, `camtool`, `camop`, then `camgenerate`. For printing, `arrangeplate`, `slice`.

**Main commands.** `camsetup`, `camtool`, `camop`, `camdelete`, `camgenerate`, `camtime`, `camexport`, `camprocess`, `camnest`, `camnestexport`, `camturnprofile`, `camprobe`, `cammachine`, `slice`, `orientstudy`, `arrangeplate`, `additiveexport`.

**Limits.** Posts are for LinuxCNC and grbl only; write your own template for another controller. G-code is a program for a machine that can hurt you: simulate it, and check the output on your own machine before cutting. Cycle times are estimates. Metal printing gets orientation, block supports and warnings, not a build simulation. The slicer outputs Marlin G-code.

## 17. Simulation

**What it does.** Studies on parts and assemblies: materials that cite their sources, loads, fixtures, contacts and mesh controls, meshed by a separate Netgen-based mesher program, then linear static, modal, thermal, thermal stress and linear buckling on second-order elements, and first versions of nonlinear statics, contact, events, fatigue and laminates. Results as contour plots, deformed shapes, animation, probes, sections and reports. Flow: laminar duct flow on FormCAD's own solver, electronics cooling and injection fill estimates, with an optional link to a flow solver you install yourself.

**How to start.** `simmaterial`, `simload`, `simfixture`, then `simstudy`, `simrun`. The mesher is a separate download, like the kernel: when the Studies panel says the mesher is not installed, press Install mesher there. The app fetches it from formai-binaries, checks every file against the record it ships and installs it; nothing is installed if a file differs.

**Main commands.** `simmaterial`, `simload`, `simfixture`, `simcontact`, `simcontrol`, `simstudy`, `simrun`, `simreport`, `simprobe`, `toporun`, `topoapply`, `toposhape`. Routes: `POST /api/docs/{doc_id}/sim/studies/{sid}/mesh`, `.../run`, `GET /api/flow`.

**Limits.** Memory is checked before a solve and the job is refused with a message if it would not fit. The nonlinear, contact, event, fatigue and laminate solvers are first versions, each checked against one published or analytic case. Injection fill, pack and warp are estimates. Without the mesher installed, meshing is unavailable. Flow with the optional solver is off until you set its path.

## 18. Generative design

**What it does.** From a study with preserved and obstacle regions, loads, a safety factor target and manufacturing methods (3D printing, milling, cutting, casting), it runs several searches and gives outcomes with mass and safety factor, which you can apply as mesh or solid bodies.

**How to start.** Make a study of type generative (`simstudy`), then `genrun`; apply a chosen outcome with `genapply`.

**Main commands.** `genrun`, `genapply`. Routes: `GET /api/docs/{doc_id}/gen/limits`, `POST /api/docs/{doc_id}/gen/studies/{sid}/run`, `GET /api/docs/{doc_id}/gen/studies/{sid}/outcomes`.

**Limits.** It works on a voxel grid with a size cap (read `gen/limits`); the shapes are smoothed, not exact. A stress check keeps the outcome under your limit on the grid; it is not a certification. Manufacturing filters are simple (an overhang angle, a draw direction, a tool reach) and do not replace your own review.

## 19. Electronics

**What it does.** Schematic capture with symbols generated from pin counts and names, hierarchical sheets, buses and electrical rule checks; boards with layers, footprints from FormCAD's own land pattern generator, tracks, vias, copper pours with thermal reliefs, design rule checks with fabricator profiles that name their sources, and a two-layer autorouter. Outputs: Gerber X2, Excellon drill, IDF, a 3D board for assemblies, and an outline kept in step with an enclosure part.

**How to start.** `POST /api/docs/{doc_id}/ecad/init` creates the electronics records; the Electronics workspace drives it. Checks: `ecaderc`, `pcbdrc`. Outputs: `gerberexport`, `drillexport`, `idfexport`, `boardstep`, `ecadsync`, `ecadpush`.

**Limits.** The autorouter handles two layers and gives up on what it cannot route, listing the unrouted nets. Design rule profiles are examples with named sources; check your fabricator's own numbers. Exchange with an open electronics suite is on request and needs your own install for anything beyond writing files. Macros are refused on every export.

## 20. Routing: harnesses, tubes and schematics

**What it does.** Harnesses routed through clips with bend radius checks and flattened to a formboard drawing with wire lists and from-to tables; tube and pipe runs with bend tables for benders, generated fittings and cut lists; electrical schematics numbered and matched to harness wires.

**How to start.** `pipespec` then `piperoute`; `harness`; `schemdevice` and `schemwire`.

**Main commands.** `harness`, `harnessexport`, `pipespec`, `piperoute`, `pipecutlist`, `pipebender`, `pipefitting`, `pipeexport`, `schemdevice`, `schemwire`, `schemnumber`, `schemdraw`, `schemwirelist`, `schemexport`.

**Limits.** Tube specs and bend tables are examples you edit; they are not any maker's data. Springback is a number you give.

## 21. Weldments and molds

**What it does.** Weldments: frames of structural members along sketch lines, joints with miters or butts, gussets, end caps, and a cut list with lengths and angles, placed as a drawing table. Molds: draft and undercut analysis, a parting line, a mold block, cavity and core with shrink.

**How to start.** `weldframe`, `weldmember`; `moldsettings`, `moldsplit`.

**Main commands.** `weldframe`, `weldmember`, `weldjoint`, `weldgusset`, `weldendcap`, `weldcutlist`, `weldcuttable`, `weldcutupdate`; `moldsettings`, `molddraft`, `moldparting`, `moldblock`, `moldsplit`, `moldclear`.

**Limits.** Profiles are generated from the dimensions you enter; no standard profile table ships. Mold work is geometry only: no flow, cooling layout or ejector design, and a part with deep undercuts is reported, not solved.

## 22. Toolbox

**What it does.** Twelve generators of common hardware (screws, nuts, washers and similar) from the sizes you give, saved as part files and inserted with mates; a library file and a CSV importer for your own size lists.

**How to start.** `toolboxinsert` or `toolboximport`.

**Main commands.** `toolboxinsert`, `toolboximport`. Routes: `GET /api/toolbox/kinds`, `POST /api/toolbox/part`, `GET /api/toolbox/library`.

**Limits.** No standard size table ships. You enter sizes or import your own CSV (2 MB and 5000 row caps; the path is checked against granted folders). A generated screw is a shape from your numbers, not a certified part.

## 23. Inspection and costing

**What it does.** Inspection: collect dimensions and tolerances into a numbered table, balloons, an inspection form and a report, import of measured values; model-based definition views that group product manufacturing information. Costing: a profile of your rates and prices, per-part cost estimates by process and batch, design-for-manufacture findings against thresholds you can edit, design checks, and an emissions estimate from factors you import.

**How to start.** `inspection`, `inspectionexport`, `mbdview`. Costing is in the Costing panel; routes `GET /api/docs/{doc_id}/costing/estimate`, `.../costing/dfm`, `.../costing/sustainability`.

**Limits.** No cost rates, material prices or emission factors ship; the profile is empty and yours to fill, and every number shown traces to a value you entered. DFM thresholds are starting examples with a source and a flag when only one source backs them. Macros may read costing but never write it.

## 24. Limits that apply everywhere

- Every file path is validated; outputs get their extension forced. Every route needs the session token.
- Every job that computes has caps checked before it starts, and Cancel where it runs long.
- Where data would need a standards table, FormCAD ships a formula or an empty table you fill, never a copy of a table.
- Numbers from first-version solvers and estimates are labelled in the interface. Treat them as guidance; verify what matters by your own means.

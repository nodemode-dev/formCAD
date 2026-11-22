import type { MenuDef, MenuItem, SubMenu } from './menu';
import { WORKSPACES } from './titlebar-tools';
import { V3_MENU } from '../view3d/menu-ids';

export interface EngineCommand {
  id: string;
  label: string;
  name: string;
  option?: string;
  keys?: string[];
  group: string;
}

export const ENGINE_COMMANDS = new Map<string, EngineCommand>();

export const RECENT_SLOTS = 9;

export const engineId = (name: string, option?: string): string => `x:${name.toLowerCase()}${option ? `:${option}` : ''}`;

let group = 'General';

function E(label: string, name: string, option?: string, keys?: string[]): string {
  const id = engineId(name, option);
  if (!ENGINE_COMMANDS.has(id)) ENGINE_COMMANDS.set(id, { id, label, name: name.toLowerCase(), option, keys, group });
  return id;
}

const S = (label: string, ...items: MenuItem[]): SubMenu => ({ label, items });
const SEP = '-' as const;

function section(name: string, make: () => MenuItem[]): MenuItem[] {
  group = name;
  return make();
}

const recentItems = (count: () => number): MenuItem[] => {
  const n = Math.min(RECENT_SLOTS, count());
  const rows: MenuItem[] = [];
  for (let i = 0; i < n; i++) rows.push(`recent-${i}`);
  if (n) rows.push(SEP);
  rows.push('clear-recent');
  return rows;
};

const file = (recentCount: () => number): MenuItem[] => section('File', () => [
  'new', E('New from Template...', 'newfromtemplate'), 'open',
  { label: 'Open Recent', items: recentItems(recentCount) },
  SEP, 'close', 'close-all', SEP, 'save', 'save-as',
  S('Default Save Format', E('DXF', 'defaultsaveformat', 'dxf'), E('DWG', 'defaultsaveformat', 'dwg'), SEP,
    E('Version 2018', 'defaultsaveformat', '2018'), E('Version 2013', 'defaultsaveformat', '2013'), E('Version 2010', 'defaultsaveformat', '2010'),
    E('Version 2007', 'defaultsaveformat', '2007'), E('Version 2004', 'defaultsaveformat', '2004'), E('Version 2000', 'defaultsaveformat', '2000')),
  SEP, E('Import...', 'import'), E('Export...', 'export'), 'sm-flat-export', E('Export to PDF...', 'exportpdf'),
  E('Print...', 'plot', undefined, ['Mod+P']), E('Plot Preview', 'plotpreview'), E('Batch Publish...', 'publish'), E('Sheet Books to PDF...', 'sheetbooks'),
  SEP, E('Page Setup Manager...', 'pagesetup'), E('Plotter Manager...', 'plottermanager'), E('Plot Style Manager...', 'stylesmanager'),
  SEP, S('Drawing Utilities', E('Audit', 'audit'), E('Recover...', 'recover'), E('Drawing Recovery Manager...', 'drawingrecovery')),
]);

const edit = (): MenuItem[] => section('Edit', () => [
  'undo', 'redo', SEP, 'cut', 'copy', E('Copy with Base Point', 'copybase', undefined, ['Shift+Mod+C']), E('Cut with Base Point', 'cutbase'),
  'paste', E('Paste as Block', 'pasteblock', undefined, ['Shift+Mod+V']), E('Paste to Original Coordinates', 'pasteorig'),
  E('Clear', 'erase', 'clear', ['Delete']), SEP, 'select-all', 'open-quick-select', 'open-find', SEP, 'language',
]);

const view = (): MenuItem[] => section('View', () => [
  E('Regen', 'regen'), E('Regen All', 'regenall'), E('Redraw', 'redraw'), SEP,
  S('Zoom', E('Realtime', 'zoom', 'realtime'), E('Window', 'zoom', 'window'), E('Previous', 'zoom', 'previous'), E('In', 'zoom', 'in'), E('Out', 'zoom', 'out'),
    E('All', 'zoom', 'all'), E('Extents', 'zoom', 'extents'), E('Dynamic', 'zoom', 'dynamic'), E('Object', 'zoom', 'object')),
  S('Pan', E('Realtime', 'pan', 'realtime'), E('Left', 'pan', 'left'), E('Right', 'pan', 'right'), E('Up', 'pan', 'up'), E('Down', 'pan', 'down')),
  E('Named Views...', 'view'),
  S('Viewports', E('1 Viewport', 'vports', '1'), E('2 Viewports', 'vports', '2'), E('3 Viewports', 'vports', '3'), E('4 Viewports', 'vports', '4'), SEP,
    E('New Viewports...', 'vports'), E('Named Viewports...', 'vports', 'named'), E('Polygonal Viewport', 'mview', 'polygonal')),
  S('Attribute Display', E('Normal', 'attdisp', 'normal'), E('On', 'attdisp', 'on'), E('Off', 'attdisp', 'off')),
  S('Show Annotative Objects', E('All Scales', 'annoallvisible', 'all'), E('Current Scale Only', 'annoallvisible', 'current')),
  SEP, S('3D View', ...V3_MENU), S('Render', 'rn-toggle', 'rn-panel', SEP, 'rn-image', 'rn-turntable'), SEP, 'toggle-viewcube', 'toggle-ucs-icon', SEP,
  S('Interface Theme', 'theme-system', 'theme-light', 'theme-dark'),
  S('Accessibility', E('Show System Cursor', 'systemcursor'), S('Animation Effects', 'anim-system', 'anim-on', 'anim-off')),
  SEP, 'custom-title-bar', 'menus-in-window',
]);

const insert = (): MenuItem[] => section('Insert', () => [
  E('Block...', 'insert'), E('DWG Reference...', 'xattach'), E('Raster Image Reference...', 'imageattach'), E('PDF Underlay...', 'pdfattach'), E('Data Link...', 'datalink'), S('Layout', E('New Layout', 'layout', 'new')),
  SEP, E('Image Reference...', 'imageattach'), E('Table...', 'table'),
]);

const format = (): MenuItem[] => section('Format', () => [
  E('Layers...', 'layer'),
  S('Layer Tools', E('Make Current', 'laymcur'), E('Change to Current Layer', 'laycur'), E('Layer Match', 'laymch'), E('Previous Layer', 'layerp'),
    E('Isolate Layer', 'layiso'), E('Unisolate Layer', 'layuniso'), E('Layer Off', 'layoff'), E('Freeze Layer', 'layfrz'), E('Lock Layer', 'laylck'),
    E('Unlock Layer', 'layulk'), E('Layer Merge', 'laymrg'), E('Layer Delete', 'laydel')),
  E('Layer States Manager...', 'layerstate'), SEP,
  E('Color...', 'color'), E('Linetype...', 'linetype'), E('Lineweight...', 'lweight'), E('Plot Style...', 'plotstyle'),
  E('Text Style...', 'style'), E('Dimension Style...', 'dimstyle'), E('Table Style...', 'tablestyle'), E('Multileader Style...', 'mleaderstyle'),
  E('Multiline Style...', 'mlstyle'), E('Point Style...', 'ddptype'), SEP,
  E('Units...', 'units'), E('Drawing Limits', 'limits'), E('Thickness', 'thickness'), E('Scale List...', 'scalelistedit'), E('Rename...', 'rename'),
]);

const draw = (): MenuItem[] => section('Draw', () => [
  E('Line', 'line'), E('Polyline', 'pline'), E('3D Polyline', '3dpoly'), E('Multiline', 'mline'), E('Construction Line', 'xline'), E('Ray', 'ray'),
  S('Circle', E('Center, Radius', 'circle'), E('Center, Diameter', 'circle.cd'), E('2 Points', 'circle.2p'), E('3 Points', 'circle.3p'),
    E('Tan, Tan, Radius', 'circle.ttr'), E('Tan, Tan, Tan', 'circle.ttt')),
  S('Arc', E('3 Points', 'arc'), E('Start, Center, End', 'arc.sce'), E('Start, Center, Angle', 'arc.sca'), E('Start, Center, Length', 'arc.scl'),
    E('Start, End, Angle', 'arc.sea'), E('Start, End, Direction', 'arc.sed'), E('Start, End, Radius', 'arc.ser'), E('Center, Start, End', 'arc.cse'),
    E('Center, Start, Angle', 'arc.csa'), E('Center, Start, Length', 'arc.csl'), E('Continue', 'arc.continue')),
  S('Ellipse', E('Center', 'ellipse'), E('Axis, End', 'ellipse.axis'), E('Arc', 'ellipse.arc')),
  E('Rectangle', 'rectang'), E('Polygon', 'polygon'), E('Donut', 'donut'),
  S('Spline', E('Fit Points', 'spline'), E('Control Vertices', 'spline.cv')), E('Helix', 'helix'),
  S('Revision Cloud', E('Rectangular', 'revcloud'), E('Polygonal', 'revcloud.polygonal'), E('Freehand', 'revcloud.freehand')),
  S('Point', E('Single Point', 'point'), E('Multiple Point', 'point.multiple'), E('Divide', 'divide'), E('Measure', 'measure')),
  E('Center Mark', 'centermark'), E('Center Line', 'centerline'), E('Break Line', 'breakline'), E('2D Solid', 'solid'), E('Wipeout', 'wipeout'), E('Region', 'region'),
  SEP, E('Boundary...', 'boundary'), E('Hatch...', 'hatch'), E('Gradient...', 'gradient'), E('Table...', 'table'),
  S('Text', E('Multiline Text', 'mtext'), E('Single Line Text', 'text')),
  S('Block', E('Make...', 'block'), E('Define Attributes...', 'attdef')),
]);

const dimension = (): MenuItem[] => section('Dimension', () => [
  E('Linear', 'dimlinear'), E('Aligned', 'dimaligned'), E('Arc Length', 'dimarc'), E('Ordinate', 'dimordinate'), E('Radius', 'dimradius'),
  E('Jogged', 'dimjogged'), E('Diameter', 'dimdiameter'), E('Angular', 'dimangular'), E('Quick Dimension', 'qdim'), E('Baseline', 'dimbaseline'),
  E('Continue', 'dimcontinue'), E('Dimension', 'dim'), SEP, E('Multileader', 'mleader'), E('Leader', 'leader'), E('Tolerance...', 'tolerance'), E('Inspection', 'diminspect'),
  E('Jogged Linear', 'dimjogline'), E('Dimension Space', 'dimspace'), E('Dimension Break', 'dimbreak'), SEP,
  S('Align Text', E('Home', 'dimtedit.home'), E('Left', 'dimtedit.left'), E('Right', 'dimtedit.right'), E('Center', 'dimtedit.center'), E('Angle', 'dimtedit.angle')),
  E('Oblique', 'dimedit.oblique'), E('Override', 'dimoverride'), E('Update', 'dimstyle.update'), E('Reassociate Dimensions', 'dimreassociate'),
  SEP, E('Dimension Style...', 'dimstyle.dimension'),
]);

const modify = (): MenuItem[] => section('Modify', () => [
  'open-properties', E('Match Properties', 'matchprop'), SEP,
  E('Erase', 'erase'), E('Copy', 'copy'), E('Mirror', 'mirror'), E('Offset', 'offset'),
  S('Array', E('Rectangular Array', 'arrayrect'), E('Polar Array', 'arraypolar'), E('Path Array', 'arraypath')),
  E('Move', 'move'), E('Rotate', 'rotate'), E('Scale', 'scale'), E('Stretch', 'stretch'), E('Lengthen', 'lengthen'),
  E('Trim', 'trim'), E('Extend', 'extend'), E('Break', 'break'), E('Break at Point', 'breakatpoint'), E('Join', 'join'),
  E('Chamfer', 'chamfer'), E('Fillet', 'fillet'), E('Blend', 'blend'), E('Explode', 'explode'),
  E('Delete Duplicate Objects', 'overkill'), E('Flatten Objects', 'flatten'), E('Copy Nested Objects', 'ncopy'), E('Change Space', 'chspace'),
  SEP,
  S('Object', E('Polyline', 'pedit'), E('Spline', 'splinedit'), E('Hatch...', 'hatchedit'), E('Edit Text...', 'textedit'), E('Multiline...', 'mledit'),
    E('Edit Array', 'arrayedit'), E('Block Description...', 'blockdesc'),
    S('Attribute', E('Single...', 'attedit'), E('Global', '-attedit'), E('Block Attribute Manager...', 'battman'), E('Synchronize Attributes', 'attsync')),
    S('External Reference', E('Bind...', 'xbind')),
    S('Image', E('Adjust...', 'imageadjust')), S('PDF Underlay', E('Adjust...', 'pdfadjust')),
    S('Multileader', E('Add Leader', 'mleaderedit.add'), E('Remove Leader', 'mleaderedit.remove'), E('Align', 'mleaderalign'), E('Collect', 'mleadercollect'))),
  S('Clip', E('Viewport', 'vpclip'), E('Image', 'imageclip'), E('PDF Underlay', 'pdfclip')),
  S('3D Operations', E('Align', 'align'), 'u8-gumball', 'u8-gumball-reset'),
  S('Deform', E('Bend', 'bend'), E('Flow along Curve', 'flow'), E('Flow along Surface', 'flowsrf'), E('Cage', 'cage'), E('Cage Edit', 'cageedit'), E('Remove Cage', 'cageoff')),
  S('Solid Editing', E('Union', 'union'), E('Subtract', 'subtract'), E('Intersect', 'intersect')),
  S('Annotative Object Scale', E('Add Current Scale', 'aiobjectscaleadd'), E('Delete Current Scale', 'aiobjectscaleremove'), E('Add/Delete Scales...', 'objectscale'),
    E('Synchronize Multiple-scale Positions', 'annoreset')),
]);

const parametric = (): MenuItem[] => section('Parametric', () => [
  S('Geometric Constraints', E('Coincident', 'gccoincident'), E('Collinear', 'gccollinear'), E('Concentric', 'gcconcentric'), E('Fix', 'gcfix'),
    E('Parallel', 'gcparallel'), E('Perpendicular', 'gcperpendicular'), E('Horizontal', 'gchorizontal'), E('Vertical', 'gcvertical'),
    E('Tangent', 'gctangent'), E('Smooth', 'gcsmooth'), E('Symmetric', 'gcsymmetric'), E('Equal', 'gcequal'), E('Midpoint', 'gcmidpoint')),
  S('Dimensional Constraints', E('Linear', 'dclinear'), E('Aligned', 'dcaligned'), E('Horizontal', 'dchorizontal'), E('Vertical', 'dcvertical'),
    E('Angular', 'dcangular'), E('Radius', 'dcradius'), E('Diameter', 'dcdiameter')),
  S('Constraint Bars', E('Select Objects', 'constraintbar'), E('Show All', 'constraintbar', 'show'), E('Hide All', 'constraintbar', 'hide')),
  S('Dynamic Dimensions', E('Select Objects', 'dcdisplay'), E('Show All', 'dcdisplay', 'show'), E('Hide All', 'dcdisplay', 'hide')),
  SEP, E('AutoConstrain', 'autoconstrain'), E('Delete Constraints', 'delconstraint'), E('Constraint Settings...', 'constraintsettings'),
  E('Parameters Manager', 'parameters'),
]);

const sketch = (): MenuItem[] => section('Sketch', () => [
  E('Start Sketch', 'sketch'), E('Sketch on Plane', 'sketchplane'), E('Finish Sketch', 'sketchfinish'), SEP,
  E('Project Geometry', 'sketchproject'), E('Intersection Curve', 'sketchintersect'), E('Construction Geometry', 'sketchconstruction'), SEP,
  E('Sketch Fillet', 'fillet', 'sketch'), E('Sketch Chamfer', 'chamfer', 'sketch'), E('Sketch Trim', 'trim', 'sketch'), E('Sketch Offset', 'offset', 'sketch'), SEP,
  E('Sketch Constraints', 'autoconstrain', 'sketch'), E('Sketch Dimensions', 'dim', 'sketch'), E('Sketch Status', 'sketchstatus'),
]);

const partMenu = (): MenuItem[] => section('Part', () => [
  'pt-sketch', 'pt-finish-sketch', 'pt-edit-sketch', SEP,
  'pt-extrude', 'pt-extrude-cut', 'pt-revolve', 'pt-revolve-cut', 'pt-sweep', 'pt-sweep-cut', 'pt-loft', 'pt-loft-cut', 'pt-boundary', 'pt-rib', 'pt-hole', 'pt-thread', 'pt-thicken', SEP,
  'pt-fillet', 'pt-chamfer', 'pt-shell', 'pt-draft', 'pt-pattern', 'pt-mirror', 'pt-delete-face', SEP,
  S('Sheet Metal', 'sm-base', 'sm-convert', SEP, 'sm-edge', 'sm-miter', 'sm-hem', 'sm-jog', 'sm-sketched', SEP, 'sm-relief', 'sm-corner', SEP,
    'sm-flat', 'sm-flat-export', SEP, 'sm-rule', 'sm-tables', 'sm-cutlist'),
  S('Plastic', 'pl-boss', 'pl-rib', 'pl-snap', 'pl-lip', 'pl-groove', SEP, 'pl-panel', E('Plastic Checks', 'plasticcheck'), E('Wall Thickness Map', 'wallthickness')), SEP,
  'pt-edit', 'pt-rebuild', 'pt-force-rebuild', 'pt-roll-end', SEP,
  'pt-design-table', 'pt-materials', 'pt-mass',
]);

const model = (): MenuItem[] => section('Model', () => [
  E('Extrude', 'extrude'), E('Revolve', 'revolve'), E('Sweep', 'sweep'), E('Loft', 'loft'), SEP,
  E('Hole...', 'hole'), E('Fillet Edges', 'filletedge'), E('Chamfer Edges', 'chamferedge'), E('Shell', 'shell'), E('Draft', 'draft'), E('Rib', 'rib'), SEP,
  S('Pattern', E('Rectangular Pattern', 'patternrect'), E('Circular Pattern', 'patterncirc'), E('Mirror Body', 'mirrorbody')),
  S('Combine', E('Union', 'solidunion'), E('Subtract', 'solidsubtract'), E('Intersect', 'solidintersect')),
  S('Primitives', E('Box', 'box'), E('Cylinder', 'cylinder'), E('Sphere', 'sphere'), E('Cone', 'cone'), E('Torus', 'torus')),
  SEP, E('Move Face', 'moveface'), E('Offset Face', 'offsetface'), E('Delete Face', 'deleteface'), SEP,
  E('Measure Body', 'massprop', 'body'), E('Section Analysis', 'sectionanalysis'), 'p10-pmi-panel', 'install-kernel',
]);

const curve = (): MenuItem[] => section('Curve', () => [
  E('Control Points', 'crv'), E('Through Points', 'crvinterp'), E('Blend Curve', 'crvblend'), SEP,
  E('Match Curve', 'crvmatch'), E('Offset Curve', 'crvoffset'), E('Extend Curve', 'crvextend'), E('Sub-curve', 'crvsub'), E('Reverse Direction', 'crvreverse'), SEP,
  E('Fit to Tolerance', 'crvfit'), E('Rebuild', 'crvrebuild'), E('Change Degree', 'crvdegree'), E('Insert or Remove Knot', 'crvknot'),
  E('Simplify', 'crvsimplify'), E('Periodic or Open', 'crvperiodic'), SEP,
  E('Project onto Surface', 'crvproject'), 'u96-project-view', E('Pull onto Surface', 'crvpull'), E('Contour', 'srfcontour'), E('Extract Isocurve', 'srfisocurve'), SEP,
  E('Continuity Report', 'crvcont'), SEP, 'u7-points-cv', 'u7-points-ep', 'u7-points-off',
]);

const surface = (): MenuItem[] => section('Surface', () => [
  E('Loft', 'srfloft'), E('Sweep', 'srfsweep'), E('Network', 'srfnetwork'), E('Patch', 'srfpatch'), E('Planar', 'srfplanar'), E('From Edge Curves', 'srfedge'),
  E('Extrude Curve', 'srfextrude'), E('Revolve Curve', 'srfrevolve'), SEP,
  E('Blend', 'srfblend'), E('Fillet', 'srffillet'), E('Chamfer', 'srfchamfer'), E('Variable Fillet', 'srfvarfillet'), E('Match', 'srfmatch'), E('Extend', 'srfextend'), E('Offset', 'srfoffset'), E('Trim', 'srftrim'), E('Untrim', 'srfuntrim'), E('Shrink Trimmed', 'srfshrink'), E('Split', 'srfsplit'), E('Join', 'srfjoin'), SEP,
  S('Edge Treatment', E('Fillet Edge', 'filletedge'), E('Chamfer Edge', 'chamferedge'), E('Blend Edge', 'blendedge')),
  S('Boolean', E('Boolean with Diagnostics', 'boolop'), E('Check Boolean', 'boolcheck'), 'u7-diag-open'), SEP,
  E('Seam Continuity', 'seamcheck'), 'u7-seams-sel', E('Naked Edges', 'nakededges'), E('Surface Report', 'surfreport'), 'u7-clear-analysis', SEP,
  E('Model Tolerance...', 'modeltol'), 'u7-tol-open', SEP,
  'u7-points-cv', 'u9-zebra', 'u8-analysis-open', 'u8-analysis-off', 'u8-snap3d',
]);

const formMenu = (): MenuItem[] => section('Form', () => [
  'fm-panel', 'fm-edit', SEP,
  S('New Form', 'fm-box', 'fm-cylinder', 'fm-sphere', 'fm-quadball', 'fm-torus', 'fm-plane'),
  E('Form From Extruded Profile', 'subdextrude'), E('Form From Revolved Profile', 'subdrevolve'), SEP,
  'fm-move', 'fm-rotate', 'fm-scale', SEP,
  E('Insert Edge', 'subdinsertedge'), E('Subdivide Face', 'subddivideface'), E('Delete Form Elements', 'subddelete'), E('Bridge', 'subdbridge'), E('Fill Hole', 'subdfillhole'), SEP,
  E('Crease', 'subdcrease'), E('Uncrease', 'subduncrease'), E('Form Symmetry', 'subdsymmetry'), E('Form Display', 'subddisplay'), SEP,
  E('Form Report', 'subdinfo'), 'fm-convert',
]);

const meshMenu = (): MenuItem[] => section('Mesh', () => [
  E('Mesh From Solid', 'meshfromsolid'), SEP,
  E('Weld', 'meshweld'), E('Unify Normals', 'meshunify'), E('Fill Holes', 'meshfill'), SEP,
  'u8-mesh-naked', 'u8-mesh-naked-off', E('Count Naked Edges', 'meshnaked'), E('Mesh Report', 'meshreport'), SEP,
  'u8-mesh-import', 'u8-mesh-export', E('3DM File Info', 'info3dm'), SEP,
  'p10-mesh-panel',
]);

const assembly = (): MenuItem[] => section('Assembly', () => [
  'u8-asm-insert', E('Insert Component (typed)', 'asminsert'), SEP,
  'u8-asm-panel', 'u8-mates-panel', 'u8-explode-panel', 'u8-check-panel', 'u8-bom-panel', SEP,
  'p11-joints-panel', 'p11-motion-panel', 'p11-joint-symbols', 'p11-run-study', SEP,
  'u8-asm-solve', 'u8-asm-drag', SEP,
  E('Pin to Vault (typed)', 'vaultpin'),
]);

const manufacture = (): MenuItem[] => section('Manufacture', () => [
  'p12-cam-panel', 'p12-tool-panel', 'p12-sim-panel', 'p12-nest-panel', 'p12-turn-panel', 'p12-print-panel', SEP,
  'p12-toolpaths', 'p12-sim-stock', 'p12-layers',
]);

const simulate = (): MenuItem[] => section('Simulate', () => [
  'p13-study-panel', 'p13-result-panel', 'p13-calc-panel', SEP,
  'p13-mesh', 'p13-solve', 'p13-cancel', SEP,
  'p13-show-result',
]);

const produce = (): MenuItem[] => section('Produce', () => [
  'p15-weld-panel', 'p15-mold-panel', 'p15-toolbox-panel', SEP,
  'p15-inspect-panel', 'p15-cost-panel', 'p15-check-panel', SEP,
  'p15-draft-colours',
]);

const generate = (): MenuItem[] => section('Generate', () => [
  'p14a-gen-panel', SEP, 'p14a-gen-run', 'p14a-gen-cancel', 'p14a-gen-hide',
]);

const routing = (): MenuItem[] => section('Routing', () => [
  'p14a-harness-panel', 'p14a-pipe-panel', 'p14a-schem-panel', SEP, 'p14a-route-show',
]);

const electronics = (): MenuItem[] => section('Electronics', () => [
  'p14b-tab-sch', 'p14b-tab-pcb', 'p14b-tab-3d', SEP,
  'p14b-sch-panel', 'p14b-pcb-panel', 'p14b-out-panel', SEP,
  'p14b-drc', 'p14b-route', 'p14b-route-cancel',
]);

const drawing = (): MenuItem[] => section('Drawing', () => [
  E('New Sheet', 'layout', 'new'), E('Page Setup Manager...', 'pagesetup'), 'dw-titleblock', SEP,
  S('Base View', 'dw-base-front', 'dw-base-back', 'dw-base-left', 'dw-base-right', 'dw-base-top', 'dw-base-bottom', SEP, 'dw-base-iso', 'dw-base-iso2', 'dw-base-iso3', 'dw-base-iso4'),
  'dw-section', 'dw-detail', 'dw-aux', 'dw-break', 'dw-crop', SEP,
  'dw-update', 'dw-update-all', 'dw-update-one', 'dw-delete', S('Projection Angle', 'dw-proj-third', 'dw-proj-first'), SEP,
  'dw-dim', 'dw-frame', 'dw-frame-edit', 'dw-datum', 'dw-finish', SEP,
  'dw-balloon', 'dw-autoballoon', 'dw-bom', 'dw-bom-update', E('Hole Table', 'holetable'), E('Update Hole Tables', 'holetableupdate'), 'dw-centermarks', 'dw-hatch', SEP,
  E('Revision Table', 'revtable'), E('Add Revision...', 'revadd'), E('Remove Last Revision', 'revremove'), SEP,
  'dw-settings', 'dw-panel-views', 'dw-panel-props',
]);

const graph = (): MenuItem[] => section('Graph', () => [
  'gr-open', SEP,
  E('New Graph', 'graphnew'), E('Add Node...', 'graphnode'), E('Connect', 'graphconnect'), E('Disconnect', 'graphdisconnect'), SEP,
  E('Parameters', 'graphparams'), E('Run Graph', 'graphrun'), E('Bake to Geometry', 'graphbake'), SEP,
  E('Group Nodes', 'graphgroup'), E('Ungroup Nodes', 'graphungroup'), E('Import Graph...', 'graphimport'), E('Export Graph...', 'graphexport'),
]);

const tools = (): MenuItem[] => section('Tools', () => [
  'settings', E('Drafting Settings...', 'dsettings'), E('Cycle Isometric Plane', 'isoplane', undefined, ['F5', 'Mod+E']),
  S('Inquiry', E('Distance', 'dist'), E('Radius', 'radius.measure'), E('Angle', 'angle.measure'), E('Area', 'area'), E('Region/Mass Properties', 'massprop'),
    E('Volume', 'volume.measure'), E('List', 'list'), E('ID Point', 'id'), 'win-quickcalc', E('Set Variable', 'setvar')),
  'open-quick-select',
  S('Draw Order', E('Bring to Front', 'draworder', 'front'), E('Send to Back', 'draworder', 'back'), E('Bring Above Objects', 'draworder', 'above'),
    E('Send Under Objects', 'draworder', 'under'), E('Send Hatches to Back', 'draworder', 'hatchback'),
    S('Bring Annotations to Front', E('All Annotation Objects', 'draworder', 'annoall'), E('Text Objects Only', 'draworder', 'annotext'),
      E('Dimension Objects Only', 'draworder', 'annodim'), E('Leaders Only', 'draworder', 'annoleader'))),
  E('Group', 'group'), E('Ungroup', 'ungroup'),
  S('Isolate', E('Isolate Objects', 'isolateobjects'), E('Hide Objects', 'hideobjects'), E('End Object Isolation', 'unisolateobjects')),
  SEP, E('Block Editor', 'bedit'), E('Open Xref', 'xopen'),
  S('Xref and Block In-place Editing', E('Edit Reference In-Place', 'refedit'), E('Add to Working Set', 'refset', 'add'), E('Save Reference Edits', 'refclose', 'save')),
  SEP,
  S('Customize', E('Edit Command Aliases...', 'aliasedit')),
  S('Extra Tools', E('Break-line Symbol', 'breakline'), E('Convert Text to Mtext', 'txt2mtxt'), E('Explode Attributes to Text', 'burst'),
    E('Move/Copy/Rotate', 'mocoro'), E('Replace Block...', 'blockreplace')),
  E('Count', 'count'), E('Compare Drawings...', 'compare'), E('Data Extraction...', 'dataextraction'), SEP,
  E('LISP Console...', 'lispconsole'), E('Load Application...', 'appload'), E('Run Script...', 'script'), E('Macro Recorder...', 'macrorecorder'), E('3D Mouse...', 'mouse3d'),
]);

const windowMenu = (): MenuItem[] => section('Window', () => [
  'win-toolsets', 'win-properties', 'win-layers', 'win-quickcalc', 'toggle-quickprops', E('Reference Manager', 'xref'), SEP,
  'win-filetabs', 'win-statusbar', 'win-cmdline', 'win-cmdhistory', 'win-menubar', 'agent-dock', SEP,
  'win-hide-palettes', 'win-reset-palettes', 'win-reset-layout', SEP,
  S('Workspace', ...WORKSPACES.map((w) => `workspace-${w.id}`)),
  'home', E('Layer Manager...', 'layer', 'manager'), E('Blocks', 'blocks'), E('Parameters Manager', 'parameters'), 'jobs', 'p11-vault-panel',
]);

const help = (): MenuItem[] => section('Help', () => [
  'help', E('Open Sample Drawing', 'opensample'), E('Check for Updates...', 'checkupdates'), SEP, 'about',
]);

const annotateMenu = (): MenuItem[] => [
  S('Dimension', ...dimension()), S('Drawing', ...drawing()),
];

const modelMenu = (): MenuItem[] => [
  S('Sketch', ...sketch()), S('Parametric', ...parametric()), SEP,
  S('Part', ...partMenu()), S('Solid', ...model()), S('Assembly', ...assembly()), SEP,
  S('Curve', ...curve()), S('Surface', ...surface()), S('Form', ...formMenu()), S('Mesh', ...meshMenu()), SEP,
  S('Graph', ...graph()),
];

const engineerMenu = (): MenuItem[] => [
  S('Simulate', ...simulate()), S('Generate', ...generate()), SEP,
  S('Manufacture', ...manufacture()), S('Produce', ...produce()), SEP,
  S('Routing', ...routing()), S('Electronics', ...electronics()),
];

export function buildMenus(recentCount: () => number): MenuDef[] {
  return [
    { label: 'File', items: () => file(recentCount) },
    { label: 'Edit', items: edit },
    { label: 'View', items: view },
    { label: 'Insert', items: insert },
    { label: 'Format', items: format },
    { label: 'Draw', items: draw },
    { label: 'Modify', items: modify },
    { label: 'Annotate', items: annotateMenu },
    { label: 'Model', items: modelMenu },
    { label: 'Engineer', items: engineerMenu },
    { label: 'Tools', items: tools },
    { label: 'Window', items: windowMenu },
    { label: 'Help', items: help },
  ];
}

export function registerEngineCatalogue(): void {
  const noop = (): number => 0;
  buildMenus(noop).forEach((def) => { if (typeof def.items === 'function') def.items(); });
}

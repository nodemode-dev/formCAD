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
  SEP, E('Import...', 'import'), E('Export...', 'export'), E('Export to PDF...', 'exportpdf'),
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
  SEP, S('3D View', ...V3_MENU), SEP, 'toggle-viewcube', 'toggle-ucs-icon', SEP,
  S('Interface Theme', 'theme-system', 'theme-light', 'theme-dark'),
  S('Accessibility', E('Show System Cursor', 'systemcursor'), S('Animation Effects', 'anim-system', 'anim-on', 'anim-off')),
  SEP, 'custom-title-bar', 'menus-in-window',
]);

const insert = (): MenuItem[] => section('Insert', () => [
  E('Block...', 'insert'), E('DWG Reference...', 'xattach'), E('Data Link...', 'datalink'), S('Layout', E('New Layout', 'layout', 'new')),
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
    S('Multileader', E('Add Leader', 'mleaderedit.add'), E('Remove Leader', 'mleaderedit.remove'), E('Align', 'mleaderalign'), E('Collect', 'mleadercollect'))),
  S('Clip', E('Viewport', 'vpclip')),
  S('3D Operations', E('Align', 'align')),
  S('Solid Editing', E('Union', 'union'), E('Subtract', 'subtract'), E('Intersect', 'intersect')),
  S('Annotative Object Scale', E('Add Current Scale', 'aiobjectscaleadd'), E('Delete Current Scale', 'aiobjectscaleremove'), E('Add/Delete Scales...', 'objectscale'),
    E('Synchronize Multiple-scale Positions', 'annoreset')),
]);

const parametric = (): MenuItem[] => section('Parametric', () => [
  S('Geometric Constraints', E('Coincident', 'gccoincident'), E('Collinear', 'gccollinear'), E('Concentric', 'gcconcentric'), E('Fix', 'gcfix'),
    E('Parallel', 'gcparallel'), E('Perpendicular', 'gcperpendicular'), E('Horizontal', 'gchorizontal'), E('Vertical', 'gcvertical'),
    E('Tangent', 'gctangent'), E('Smooth', 'gcsmooth'), E('Symmetric', 'gcsymmetric'), E('Equal', 'gcequal')),
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
  'pt-extrude', 'pt-extrude-cut', 'pt-revolve', 'pt-revolve-cut', 'pt-sweep', 'pt-sweep-cut', 'pt-loft', 'pt-loft-cut', 'pt-boundary', 'pt-rib', 'pt-hole', SEP,
  'pt-fillet', 'pt-chamfer', 'pt-shell', 'pt-draft', 'pt-pattern', 'pt-mirror', SEP,
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
  E('Measure Body', 'massprop', 'body'), E('Section Analysis', 'sectionanalysis'), 'install-kernel',
]);

const curve = (): MenuItem[] => section('Curve', () => [
  E('Control Points', 'crv'), E('Through Points', 'crvinterp'), E('Blend Curve', 'crvblend'), SEP,
  E('Match Curve', 'crvmatch'), E('Offset Curve', 'crvoffset'), E('Extend Curve', 'crvextend'), E('Sub-curve', 'crvsub'), E('Reverse Direction', 'crvreverse'), SEP,
  E('Fit to Tolerance', 'crvfit'), E('Rebuild', 'crvrebuild'), E('Change Degree', 'crvdegree'), E('Insert or Remove Knot', 'crvknot'),
  E('Simplify', 'crvsimplify'), E('Periodic or Open', 'crvperiodic'), SEP,
  E('Continuity Report', 'crvcont'), SEP, 'u7-points-cv', 'u7-points-ep', 'u7-points-off',
]);

const surface = (): MenuItem[] => section('Surface', () => [
  E('Loft', 'srfloft'), E('Sweep', 'srfsweep'), E('Network', 'srfnetwork'), E('Patch', 'srfpatch'), E('Planar', 'srfplanar'), E('From Edge Curves', 'srfedge'),
  E('Extrude Curve', 'srfextrude'), E('Revolve Curve', 'srfrevolve'), SEP,
  E('Blend', 'srfblend'), E('Match', 'srfmatch'), E('Extend', 'srfextend'), E('Offset', 'srfoffset'), E('Trim', 'srftrim'), E('Split', 'srfsplit'), E('Join', 'srfjoin'), SEP,
  S('Edge Treatment', E('Fillet Edge', 'filletedge'), E('Chamfer Edge', 'chamferedge'), E('Blend Edge', 'blendedge')),
  S('Boolean', E('Boolean with Diagnostics', 'boolop'), E('Check Boolean', 'boolcheck'), 'u7-diag-open'), SEP,
  E('Seam Continuity', 'seamcheck'), 'u7-seams-sel', E('Naked Edges', 'nakededges'), E('Surface Report', 'surfreport'), 'u7-clear-analysis', SEP,
  E('Model Tolerance...', 'modeltol'), 'u7-tol-open',
]);

const assembly = (): MenuItem[] => section('Assembly', () => [
  E('Insert Component...', 'asminsert'), E('New Component', 'asmnew'), SEP,
  S('Joint', E('Rigid', 'asmjoint', 'rigid'), E('Revolute', 'asmjoint', 'revolute'), E('Slider', 'asmjoint', 'slider'), E('Cylindrical', 'asmjoint', 'cylindrical'), E('Ball', 'asmjoint', 'ball')),
  E('Mate', 'asmmate'), E('Ground', 'asmground'), E('Component Pattern', 'asmpattern'), SEP,
  E('Interference Check', 'asminterference'), E('Motion Study', 'asmmotion'), E('Exploded View', 'asmexplode'), E('Bill of Materials', 'asmbom'),
]);

const drawing = (): MenuItem[] => section('Drawing', () => [
  E('New Sheet', 'sheetnew'), E('Sheet Setup...', 'sheetsetup'), E('Title Block...', 'titleblock'), SEP,
  E('Base View', 'viewbase'), E('Projected View', 'viewproj'), E('Section View', 'viewsection'), E('Detail View', 'viewdetail'),
  E('Auxiliary View', 'viewaux'), E('Break View', 'viewbreak'), E('Update Views', 'viewupdate'), SEP,
  E('Balloon', 'balloon'), E('Parts List', 'partslist'), E('Surface Finish Symbol', 'finishsymbol'), E('Weld Symbol', 'weldsymbol'), E('Datum Feature', 'datum'),
]);

const graph = (): MenuItem[] => section('Graph', () => [
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
  'win-toolbar', 'win-filetabs', 'win-statusbar', 'win-cmdline', 'win-cmdhistory', 'win-menubar', SEP,
  'win-hide-palettes', 'win-reset-palettes', 'win-reset-layout', SEP,
  S('Workspace', ...WORKSPACES.map((w) => `workspace-${w.id}`)),
  'home', E('Layer Manager...', 'layer', 'manager'), E('Blocks', 'blocks'), E('Parameters Manager', 'parameters'), 'jobs',
]);

const help = (): MenuItem[] => section('Help', () => [
  'help', E('Open Sample Drawing', 'opensample'), E('Check for Updates...', 'checkupdates'), SEP, 'about',
]);

export function buildMenus(recentCount: () => number): MenuDef[] {
  return [
    { label: 'File', items: () => file(recentCount) },
    { label: 'Edit', items: edit },
    { label: 'View', items: view },
    { label: 'Insert', items: insert },
    { label: 'Format', items: format },
    { label: 'Draw', items: draw },
    { label: 'Modify', items: modify },
    { label: 'Dimension', items: dimension },
    { label: 'Parametric', items: parametric },
    { label: 'Sketch', items: sketch },
    { label: 'Part', items: partMenu },
    { label: 'Model', items: model },
    { label: 'Curve', items: curve },
    { label: 'Surface', items: surface },
    { label: 'Assembly', items: assembly },
    { label: 'Drawing', items: drawing },
    { label: 'Graph', items: graph },
    { label: 'Tools', items: tools },
    { label: 'Window', items: windowMenu },
    { label: 'Help', items: help },
  ];
}

export function registerEngineCatalogue(): void {
  const noop = (): number => 0;
  buildMenus(noop).forEach((def) => { if (typeof def.items === 'function') def.items(); });
}

import { onShellMounted } from '../app';
import { docStore } from './doc-store';
import { el, setDisabled, setTitle } from './dom';
import { onLanguage, t } from './i18n';
import { icon } from './icons';

interface Tool { cmd: string; icon: string; label: string }

const GROUPS: Tool[][] = [
  [
    { cmd: 'x:line', icon: 'line', label: 'Line' },
    { cmd: 'x:pline', icon: 'polyline', label: 'Polyline' },
    { cmd: 'x:3dpoly', icon: 'poly3d', label: '3D Polyline' },
    { cmd: 'x:mline', icon: 'mline', label: 'Multiline' },
    { cmd: 'x:xline', icon: 'xline', label: 'Construction Line' },
    { cmd: 'x:ray', icon: 'ray', label: 'Ray' },
  ],
  [
    { cmd: 'x:rectang', icon: 'rectangle', label: 'Rectangle' },
    { cmd: 'x:polygon', icon: 'polygon', label: 'Polygon' },
    { cmd: 'x:circle', icon: 'circle', label: 'Circle' },
    { cmd: 'x:arc', icon: 'arc', label: 'Arc' },
    { cmd: 'x:ellipse', icon: 'ellipse', label: 'Ellipse' },
    { cmd: 'x:donut', icon: 'donut', label: 'Donut' },
    { cmd: 'x:solid', icon: 'solid2d', label: '2D Solid' },
  ],
  [
    { cmd: 'x:spline', icon: 'spline', label: 'Spline' },
    { cmd: 'x:helix', icon: 'helix', label: 'Helix' },
    { cmd: 'x:revcloud', icon: 'revcloud', label: 'Revision Cloud' },
    { cmd: 'x:wipeout', icon: 'wipeout', label: 'Wipeout' },
  ],
  [
    { cmd: 'x:point', icon: 'point', label: 'Point' },
    { cmd: 'x:divide', icon: 'divide', label: 'Divide' },
    { cmd: 'x:measure', icon: 'measure', label: 'Measure' },
  ],
  [
    { cmd: 'x:centermark', icon: 'centerMark', label: 'Center Mark' },
    { cmd: 'x:centerline', icon: 'centerLine', label: 'Center Line' },
    { cmd: 'x:breakline', icon: 'breakLine', label: 'Break Line' },
  ],
  [
    { cmd: 'x:move', icon: 'move', label: 'Move' },
    { cmd: 'x:copy', icon: 'copy', label: 'Copy' },
    { cmd: 'x:rotate', icon: 'rotate', label: 'Rotate' },
    { cmd: 'x:scale', icon: 'scale', label: 'Scale' },
    { cmd: 'x:mirror', icon: 'mirror', label: 'Mirror' },
    { cmd: 'x:stretch', icon: 'stretch', label: 'Stretch' },
  ],
  [
    { cmd: 'x:offset', icon: 'offset', label: 'Offset' },
    { cmd: 'x:trim', icon: 'trim', label: 'Trim' },
    { cmd: 'x:extend', icon: 'extend', label: 'Extend' },
    { cmd: 'x:fillet', icon: 'fillet', label: 'Fillet' },
    { cmd: 'x:chamfer', icon: 'chamfer', label: 'Chamfer' },
    { cmd: 'x:blend', icon: 'blend', label: 'Blend' },
  ],
  [
    { cmd: 'x:break', icon: 'breakCut', label: 'Break' },
    { cmd: 'x:join', icon: 'join', label: 'Join' },
    { cmd: 'x:lengthen', icon: 'lengthen', label: 'Lengthen' },
    { cmd: 'x:explode', icon: 'explode', label: 'Explode' },
    { cmd: 'x:arrayrect', icon: 'array', label: 'Rectangular Array' },
    { cmd: 'x:align', icon: 'alignObj', label: 'Align' },
    { cmd: 'x:matchprop', icon: 'matchProp', label: 'Match Properties' },
    { cmd: 'x:erase', icon: 'erase', label: 'Erase' },
  ],
  [
    { cmd: 'x:hatch', icon: 'hatch', label: 'Hatch' },
    { cmd: 'x:gradient', icon: 'gradient', label: 'Gradient' },
    { cmd: 'x:boundary', icon: 'boundary', label: 'Boundary' },
    { cmd: 'x:region', icon: 'region', label: 'Region' },
  ],
  [
    { cmd: 'x:text', icon: 'text', label: 'Single Line Text' },
    { cmd: 'x:mtext', icon: 'mtext', label: 'Multiline Text' },
    { cmd: 'x:table', icon: 'table', label: 'Table' },
    { cmd: 'x:mleader', icon: 'mleader', label: 'Multileader' },
    { cmd: 'x:leader', icon: 'leader', label: 'Leader' },
  ],
  [
    { cmd: 'x:dimlinear', icon: 'dimLinear', label: 'Linear Dimension' },
    { cmd: 'x:dimaligned', icon: 'dimAligned', label: 'Aligned Dimension' },
    { cmd: 'x:dimradius', icon: 'dimRadius', label: 'Radius Dimension' },
    { cmd: 'x:dimdiameter', icon: 'dimDiameter', label: 'Diameter Dimension' },
    { cmd: 'x:dimangular', icon: 'dimAngular', label: 'Angular Dimension' },
    { cmd: 'x:dimarc', icon: 'dimArc', label: 'Arc Length Dimension' },
    { cmd: 'x:dimbaseline', icon: 'dimBaseline', label: 'Baseline Dimension' },
    { cmd: 'x:dimcontinue', icon: 'dimContinue', label: 'Continue Dimension' },
    { cmd: 'x:qdim', icon: 'qdim', label: 'Quick Dimension' },
  ],
  [
    { cmd: 'x:crv', icon: 'csCurve', label: 'Curve by Control Points' },
    { cmd: 'x:crvinterp', icon: 'csInterp', label: 'Curve through Points' },
    { cmd: 'x:crvblend', icon: 'csBlendCurve', label: 'Blend Curve' },
    { cmd: 'x:crvmatch', icon: 'csMatchCurve', label: 'Match Curve' },
    { cmd: 'x:crvrebuild', icon: 'csRebuild', label: 'Rebuild Curve' },
    { cmd: 'x:crvoffset', icon: 'csOffsetCurve', label: 'Offset Curve' },
  ],
  [
    { cmd: 'x:srfloft', icon: 'csLoftSrf', label: 'Loft Surface' },
    { cmd: 'x:srfsweep', icon: 'csSweepSrf', label: 'Sweep Surface' },
    { cmd: 'x:srfnetwork', icon: 'csNetwork', label: 'Network Surface' },
    { cmd: 'x:srfpatch', icon: 'csPatch', label: 'Patch Surface' },
    { cmd: 'x:srfplanar', icon: 'csPlanar', label: 'Planar Surface' },
    { cmd: 'x:srfblend', icon: 'csBlendSrf', label: 'Blend Surface' },
    { cmd: 'x:srfmatch', icon: 'csMatchSrf', label: 'Match Surface' },
    { cmd: 'x:boolop', icon: 'csBool', label: 'Boolean with Diagnostics' },
    { cmd: 'x:filletedge', icon: 'csFilletEdge', label: 'Fillet Edge' },
    { cmd: 'x:seamcheck', icon: 'csSeam', label: 'Seam Continuity' },
    { cmd: 'x:nakededges', icon: 'csNaked', label: 'Naked Edges' },
  ],
];

onShellMounted((ctx) => {
  const rail = ctx.hosts.rail;
  const buttons: Array<{ node: HTMLButtonElement; tool: Tool }> = [];
  GROUPS.forEach((group, i) => {
    if (i > 0) rail.append(el('<span class="cv-rail-sep" role="separator"></span>'));
    for (const tool of group) {
      const node = el<HTMLButtonElement>(`<button class="cv-tool" type="button" data-cmd="${tool.cmd}">${icon(tool.icon, 18)}</button>`);
      node.addEventListener('mousedown', (e) => e.preventDefault());
      rail.append(node);
      buttons.push({ node, tool });
    }
  });
  const paint = (): void => {
    const on = !!docStore.current();
    for (const b of buttons) {
      setDisabled(b.node, !on);
      setTitle(b.node, t(b.tool.label));
    }
  };
  paint();
  docStore.onChange(paint);
  onLanguage(paint);
});

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
];

onShellMounted((ctx) => {
  const rail = ctx.hosts.rail;
  const buttons: Array<{ node: HTMLButtonElement; tool: Tool }> = [];
  GROUPS.forEach((group, i) => {
    if (i > 0) rail.append(el('<span class="cv-rail-sep" role="separator"></span>'));
    for (const tool of group) {
      const node = el<HTMLButtonElement>(`<button class="cv-tool" type="button" data-cmd="${tool.cmd}">${icon(tool.icon, 18)}</button>`);
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

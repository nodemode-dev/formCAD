import type { CommandLineState } from '../../io/api';
import type { CanvasApi, Handle } from '../types';
import type { GripRef } from './gripper';
import type { MenuEntry } from './menu';

export interface MenuHost {
  canvas: CanvasApi;
  state(): CommandLineState;
  has(command: string): boolean;
  send(text: string): void;
  cancel(): void;
  ui(id: string): void;
  properties(): void;
  selection(): Handle[];
  clearSelection(): void;
  lastCommand(): string;
  recentCommands(): string[];
  recentInput(): string[];
  zoomPrevious(): void;
  zoomBy(k: number): void;
  gripOption(g: GripRef, option: string): void;
  gripMode(g: GripRef): void;
}

const EDIT_BY_KIND: Array<[RegExp, string, string]> = [
  [/^(text|mtext|attdef)/, 'ddedit', 'Edit Text'],
  [/^insert|block/, 'bedit', 'Block Editor'],
  [/^hatch/, 'hatchedit', 'Hatch Edit'],
  [/poly/, 'pedit', 'Polyline Edit'],
  [/^spline/, 'splinedit', 'Spline Edit'],
  [/^dim/, 'dimedit', 'Dimension Text Edit'],
  [/^mleader|^multileader/, 'mleaderedit', 'Multileader Edit'],
];

const SNAP_ITEMS: Array<[string, string]> = [
  ['Endpoint', 'end'], ['Midpoint', 'mid'], ['Intersection', 'int'], ['Apparent Intersection', 'app'], ['Extension', 'ext'], ['-', ''],
  ['Center', 'cen'], ['Geometric Center', 'gcen'], ['Quadrant', 'qua'], ['Tangent', 'tan'], ['-', ''],
  ['Perpendicular', 'per'], ['Parallel', 'par'], ['Node', 'nod'], ['Insertion', 'ins'], ['Nearest', 'nea'],
];

export class MenuBuilder {
  constructor(private readonly h: MenuHost) {}

  private cmd(label: string, name: string, extra: Partial<MenuEntry> = {}): MenuEntry | null {
    return this.h.has(name) ? { label, run: () => this.h.send(name), ...extra } : null;
  }

  private group(...items: Array<MenuEntry | null | undefined>): MenuEntry[] {
    return items.filter((x): x is MenuEntry => !!x);
  }

  private join(groups: MenuEntry[][]): MenuEntry[] {
    const out: MenuEntry[] = [];
    for (const g of groups) {
      if (!g.length) continue;
      if (out.length) out.push({ sep: true });
      out.push(...g);
    }
    return out;
  }

  private sub(label: string, items: Array<MenuEntry | null>): MenuEntry | null {
    const list = items.filter((x): x is MenuEntry => !!x);
    return list.length ? { label, sub: list } : null;
  }

  idle(kinds: string[]): MenuEntry[] {
    const sel = this.h.selection();
    const has = sel.length > 0;
    const last = this.h.lastCommand();
    const recent = this.h.recentCommands().map((c): MenuEntry => ({ label: c.toUpperCase(), run: () => this.h.send(c) }));
    const g1 = this.group(last ? { label: `Repeat ${last.toUpperCase()}`, run: () => this.h.send(last) } : { label: 'Repeat', disabled: true }, recent.length ? { label: 'Recent Commands', sub: recent } : null);
    const g3 = this.group(
      this.sub('Clipboard', [this.cmd('Cut', 'cutclip'), this.cmd('Copy', 'copyclip'), this.cmd('Copy with Base Point', 'copybase'), this.cmd('Paste', 'pasteclip'), this.cmd('Paste as Block', 'pasteblock'), this.cmd('Paste to Original Coordinates', 'pasteorig')]),
      this.sub('Isolate', [this.cmd('Isolate Objects', 'isolateobjects'), this.cmd('Hide Objects', 'hideobjects'), this.cmd('End Object Isolation', 'unisolateobjects')]),
    );
    const g4 = has
      ? this.group(
        this.cmd('Erase', 'erase'), this.cmd('Move', 'move'), this.cmd('Copy Selection', 'copy'), this.cmd('Scale', 'scale'), this.cmd('Rotate', 'rotate'),
        this.sub('Draw Order', [this.cmd('Bring to Front', 'drawordertofront'), this.cmd('Send to Back', 'drawordertoback')]),
        this.cmd('Group', 'group'), this.cmd('Ungroup', 'ungroup'),
      )
      : [];
    const uniq = new Set(kinds);
    const g5: MenuEntry[] = [];
    if (has && uniq.size === 1) {
      const k = [...uniq][0];
      for (const [re, name, label] of EDIT_BY_KIND) if (re.test(k)) { const e = this.cmd(label, name); if (e) g5.push(e); break; }
    }
    const g6 = has ? this.group(this.cmd('Add Selected', 'addselected'), this.cmd('Select Similar', 'selectsimilar'), { label: 'Deselect All', run: () => this.h.clearSelection() }) : [];
    const g7 = this.group({ label: 'Undo', run: () => this.h.ui('undo') }, { label: 'Redo', run: () => this.h.ui('redo') }, this.cmd('Pan', 'pan'), this.cmd('Zoom', 'zoom'));
    const g8 = this.group({ label: 'Quick Select...', run: () => this.h.ui('open-quick-select') }, { label: 'Find...', run: () => this.h.ui('open-find') });
    const g9 = this.group(has ? { label: 'Properties', run: () => this.h.properties() } : null, { label: 'Options', run: () => this.h.ui('settings') });
    return this.join([g1, g3, g4, g5, g6, g7, g8, g9]);
  }

  running(): MenuEntry[] {
    const st = this.h.state();
    const g1 = this.group({ label: 'Enter', run: () => this.h.send('') }, { label: 'Cancel', run: () => this.h.cancel() });
    const input = this.h.recentInput();
    const g2 = this.group(input.length ? { label: 'Recent Input', sub: input.map((t): MenuEntry => ({ label: t, run: () => this.h.send(t) })) } : null);
    const g3: MenuEntry[] = st.options.map((o): MenuEntry => ({ label: o.label, run: () => this.h.send(o.key) }));
    const point = st.expect === 'point' || st.expect === 'distance' || st.expect === 'angle';
    const g4 = point ? this.group({ label: 'Snap Overrides', sub: this.snapItems() }) : [];
    const g5 = this.group(
      { label: 'Pan', sub: [{ label: 'Left', run: () => this.h.canvas.panBy(120, 0) }, { label: 'Right', run: () => this.h.canvas.panBy(-120, 0) }, { label: 'Up', run: () => this.h.canvas.panBy(0, 120) }, { label: 'Down', run: () => this.h.canvas.panBy(0, -120) }] },
      { label: 'Zoom', sub: [{ label: 'Extents', run: () => this.h.canvas.zoomExtents() }, { label: 'All', run: () => this.h.canvas.zoomExtents() }, { label: 'Previous', run: () => this.h.zoomPrevious() }, { label: 'In', run: () => this.h.zoomBy(2) }, { label: 'Out', run: () => this.h.zoomBy(0.5) }] },
    );
    return this.join([g1, g2, g3, g4, g5]);
  }

  snapItems(): MenuEntry[] {
    const st = this.h.state();
    const pt = st.active && (st.expect === 'point' || st.expect === 'distance' || st.expect === 'angle');
    const send = (t: string) => (): void => this.h.send(t);
    const out: MenuEntry[] = [
      { label: 'Temporary track point', disabled: !pt, run: send('tt') },
      { label: 'From', disabled: !pt, run: send('from') },
      { label: 'Mid Between 2 Points', disabled: !pt, run: send('m2p') },
      { label: 'Point Filters', disabled: !pt, sub: ['.x', '.y', '.z', '.xy', '.xz', '.yz'].map((f): MenuEntry => ({ label: f.toUpperCase(), run: send(f) })) },
      { sep: true },
    ];
    for (const [label, mode] of SNAP_ITEMS) out.push(label === '-' ? { sep: true } : { label, disabled: !pt, run: send(mode) });
    out.push({ sep: true }, { label: 'None', disabled: !pt, run: send('non') }, { sep: true }, { label: 'Osnap Settings...', run: () => this.h.ui('prefs-snaps') });
    return out;
  }

  grip(g: GripRef): MenuEntry[] {
    const id = String(g.id);
    const out: MenuEntry[] = [{ label: g.geom === 'poly' && id.startsWith('v') ? 'Stretch Vertex' : 'Stretch', run: () => this.h.gripMode(g) }];
    if (g.geom === 'poly') {
      if (id.startsWith('v')) out.push({ label: 'Add Vertex', run: () => this.h.gripOption(g, 'add_vertex') }, { label: 'Remove Vertex', run: () => this.h.gripOption(g, 'remove_vertex') });
      else {
        const curved = this.isArcSegment(g);
        out.push({ label: 'Add Vertex', run: () => this.h.gripOption(g, 'add_vertex') });
        out.push(curved ? { label: 'Convert to Line', run: () => this.h.gripOption(g, 'convert_line') } : { label: 'Convert to Arc', run: () => this.h.gripOption(g, 'convert_arc') });
      }
    } else if ((g.geom === 'line' || g.geom === 'arc') && (id === 'start' || id === 'end')) out.push({ label: 'Lengthen', run: () => this.h.gripOption(g, 'lengthen') });
    else if (g.geom === 'arc' && id === 'mid') out.push({ label: 'Radius', run: () => this.h.gripOption(g, 'radius') });
    return out;
  }

  private isArcSegment(g: GripRef): boolean {
    const geom = g.item.geom;
    if (geom?.type !== 'poly') return false;
    const i = Number(String(g.id).slice(1));
    return Math.abs(geom.verts[i]?.[2] ?? 0) > 1e-9;
  }
}

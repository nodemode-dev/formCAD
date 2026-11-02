import { el, q, setHidden, setText } from '../dom';
import { sysvars } from '../sysvar-store';
import { toast } from '../toast';
import { runEngineText } from './engine-run';
import { properties } from './property-store';
import type { PropRow } from './prop-rows';
import { KIND_BY_NAME, type RowDef } from './props-kinds';
import { buildRow } from './row-factory';
import { selection } from './selection-bus';

const SHAPE_NAMES: Record<string, string> = { rect: 'Rectangular', polar: 'Polar', path: 'Path' };
const digits = (): number => Math.min(8, Math.max(0, sysvars.num('LUPREC', 4)));

export class ArrayBar {
  private readonly root: HTMLElement;
  private readonly shape: HTMLElement;
  private readonly rows: Array<{ def: RowDef; row: PropRow }>;
  private shown = false;

  constructor(host: HTMLElement) {
    this.root = el<HTMLElement>('<div class="ab" role="group" aria-label="Array options" hidden><span class="ab-title">Array</span><span class="ab-shape"></span><div class="ab-fields"></div><button class="cv-btn ab-edit" type="button">Edit Array</button></div>');
    this.shape = q(this.root, '.ab-shape');
    const fields = q(this.root, '.ab-fields');
    const defs = (KIND_BY_NAME.get('assoc_array')?.rows ?? []).filter((d) => d.id !== 'shape');
    const edit = (def: RowDef) => (value: unknown): void => {
      const refusal = properties.editRow(properties.payload, 'assoc_array', def, value);
      if (refusal) { toast(refusal, 'info'); this.paint(); }
    };
    this.rows = defs.map((def) => ({ def, row: buildRow(def, edit(def), digits) }));
    for (const r of this.rows) { setHidden(r.row.el, true); fields.appendChild(r.row.el); }
    q<HTMLButtonElement>(this.root, '.ab-edit').addEventListener('click', () => { void runEngineText('arrayedit'); });
    host.appendChild(this.root);
    properties.onChange(() => this.paint());
    selection.onChange(() => this.paint());
    sysvars.onChange(() => { if (this.shown) this.paint(); });
  }

  paint(): void {
    const p = properties.payload;
    const now = new Set(selection.handles);
    const fresh = !!p && now.size === p.handles.length && p.handles.every((h) => now.has(h));
    const kinds = p ? Object.keys(p.kinds) : [];
    const array = fresh && kinds.length === 1 && kinds[0] === 'assoc_array' ? p?.kinds.assoc_array : undefined;
    if (!array) {
      if (this.shown) { setHidden(this.root, true); this.shown = false; }
      return;
    }
    const shape = array.props.shape;
    setText(this.shape, shape && !shape.varies ? SHAPE_NAMES[String(shape.value)] ?? String(shape.value) : 'Mixed');
    for (const r of this.rows) r.row.paint(r.def.show(array.props));
    if (!this.shown) { setHidden(this.root, false); this.shown = true; }
  }
}

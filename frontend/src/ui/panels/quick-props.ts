import type { PropertiesPayload } from '../../io/api';
import { el, q, setHidden, setText, setTitle } from '../dom';
import { icon } from '../icons';
import { sysvars } from '../sysvar-store';
import { toast } from '../toast';
import { properties } from './property-store';
import type { PropRow } from './prop-rows';
import { GENERAL, KIND_BY_NAME, kindTitle, QUICK, QUICK_GENERAL, QUICK_READONLY, type RowDef } from './props-kinds';
import { buildRow } from './row-factory';
import { selection } from './selection-bus';

const OFFSET = 28;
const GAP = 6;
const digits = (): number => Math.min(8, Math.max(0, sysvars.num('LUPREC', 4)));

export const quickPropsOn = (): boolean => sysvars.num('QPMODE', 0) > 0;
export const flipQuickProps = (): number => { const v = sysvars.num('QPMODE', 0); return v === 0 ? 1 : -v; };

interface QuickBlock { kind: string; rows: Array<{ def: RowDef; row: PropRow }> }

export class QuickProperties {
  private readonly root: HTMLElement;
  private readonly title: HTMLElement;
  private readonly general: Array<{ def: RowDef; row: PropRow }>;
  private readonly blocks: QuickBlock[] = [];
  private pointer = { x: 0, y: 0 };
  private placedFor = '';
  private shown = false;

  constructor(private readonly stage: HTMLElement, canvasHost: HTMLElement) {
    this.root = el<HTMLElement>(`<div class="qp" role="dialog" aria-label="Quick Properties" hidden><div class="qp-head"><span class="qp-title"></span><button class="cv-icon-btn qp-close" type="button" aria-label="Turn Quick Properties off">${icon('close', 12)}</button></div><div class="qp-body"></div></div>`);
    this.title = q(this.root, '.qp-title');
    setTitle(q(this.root, '.qp-close'), 'Turn Quick Properties off');
    const body = q(this.root, '.qp-body');
    const edit = (scope: string) => (def: RowDef) => (value: unknown): void => {
      const refusal = properties.editRow(properties.payload, scope, def, value);
      if (refusal) { toast(refusal, 'info'); this.paint(); }
    };
    this.general = GENERAL.filter((d) => QUICK_GENERAL.includes(d.id)).map((def) => ({ def, row: buildRow(def, edit('general')(def), digits) }));
    for (const r of this.general) body.appendChild(r.row.el);
    for (const [kind, ids] of Object.entries(QUICK)) {
      const spec = KIND_BY_NAME.get(kind);
      if (!spec) continue;
      const rows = ids.map((id) => spec.rows.find((r) => r.id === id)).filter((d): d is RowDef => !!d).map((def) => ({ def, row: buildRow(def, edit(kind)(def), digits) }));
      for (const r of rows) { setHidden(r.row.el, true); body.appendChild(r.row.el); }
      this.blocks.push({ kind, rows });
    }
    stage.appendChild(this.root);
    canvasHost.addEventListener('pointermove', (e) => { this.pointer = { x: e.clientX, y: e.clientY }; }, { passive: true });
    q(this.root, '.qp-close').addEventListener('click', () => { if (quickPropsOn()) void sysvars.set('QPMODE', flipQuickProps()); });
    this.root.addEventListener('keydown', (e) => { if (e.key === 'Escape') (document.activeElement as HTMLElement | null)?.blur(); });
    properties.onChange(() => this.paint());
    selection.onChange(() => this.paint());
    selection.onCommand(() => this.paint());
    sysvars.onChange(() => this.paint());
  }

  private visible(p: PropertiesPayload | null): boolean {
    if (!quickPropsOn() || !p || p.count === 0 || selection.commandActive || document.querySelector('.cv-home:not([hidden])')) return false;
    const now = new Set(selection.handles);
    return now.size === p.handles.length && p.handles.every((h) => now.has(h));
  }

  paint(): void {
    const p = properties.payload;
    const on = this.visible(p);
    if (!on || !p) {
      if (this.shown) { setHidden(this.root, true); this.shown = false; this.placedFor = ''; }
      return;
    }
    const kinds = Object.keys(p.kinds);
    const total = p.count;
    const single = kinds.length === 1 ? kinds[0] : null;
    setText(this.title, single ? `${kindTitle(single)}${total > 1 ? ` (${total})` : ''}` : `All (${total})`);
    for (const r of this.general) r.row.paint(r.def.show(p.general));
    for (const b of this.blocks) {
      const k = single === b.kind ? p.kinds[b.kind] : undefined;
      for (const r of b.rows) {
        if (!k) { setHidden(r.row.el, true); continue; }
        r.row.paint(r.def.show(k.props), QUICK_READONLY.has(`${b.kind}:${r.def.id}`) ? 'Read-only' : undefined);
      }
    }
    if (!this.shown) { setHidden(this.root, false); this.shown = true; }
    const key = `${selection.doc}|${selection.handles.join(',')}`;
    if (key !== this.placedFor) {
      this.placedFor = key;
      this.place();
    }
  }

  private place(): void {
    const s = this.stage.getBoundingClientRect();
    const w = this.root.offsetWidth, h = this.root.offsetHeight;
    let x = this.pointer.x + OFFSET - s.left;
    let y = this.pointer.y + OFFSET - s.top;
    if (this.pointer.x === 0 && this.pointer.y === 0) { x = s.width - w - OFFSET; y = OFFSET; }
    x = Math.max(GAP, Math.min(x, s.width - w - GAP));
    y = Math.max(GAP, Math.min(y, s.height - h - GAP));
    this.root.style.left = `${Math.round(x)}px`;
    this.root.style.top = `${Math.round(y)}px`;
  }
}

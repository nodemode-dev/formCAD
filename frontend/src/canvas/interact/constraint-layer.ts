import { param, Refusal } from '../../io/api-param';
import { docStore } from '../../ui/doc-store';
import { toast } from '../../ui/toast';
import { KIND_NAMES, shownValue } from '../cmarks';
import type { CanvasApi, MarkHit } from '../types';
import type { MenuEntry } from './menu';

type Reporter = (e: unknown) => void;

const failure = (e: unknown): string => (e instanceof Error ? e.message : 'The engine did not answer');

let explainer: ((e: Refusal) => void) | null = null;
export function onRefusal(fn: (e: Refusal) => void): void { explainer = fn; }

export function reportFailure(e: unknown): void {
  if (e instanceof Refusal && explainer) { explainer(e); return; }
  toast(failure(e), 'error');
}

export function markTitle(hit: MarkHit): string {
  if (hit.glyph) return `${KIND_NAMES[hit.glyph.k] ?? hit.glyph.k} (${hit.glyph.id})${hit.glyph.dangling ? ' · objects missing' : ''}`;
  const d = hit.dim;
  if (!d) return '';
  return `${d.kind} ${d.driving ? 'constraint' : 'reference'} ${d.name} = ${d.expr || shownValue(d.value)} (double-click to edit)`;
}

export class ConstraintLayer {
  private readonly tip: HTMLElement;
  private readonly edit: HTMLInputElement;
  private editing: { hit: MarkHit; name: string } | null = null;
  private last: MarkHit | null = null;

  constructor(private readonly canvas: CanvasApi, private readonly host: HTMLElement, private readonly report: Reporter = reportFailure) {
    this.tip = document.createElement('div');
    this.tip.className = 'cv-cmark-tip';
    this.tip.hidden = true;
    this.edit = document.createElement('input');
    this.edit.className = 'cv-cmark-edit';
    this.edit.type = 'text';
    this.edit.spellcheck = false;
    this.edit.autocomplete = 'off';
    this.edit.hidden = true;
    this.edit.setAttribute('aria-label', 'Dimension expression');
    host.append(this.tip, this.edit);
    host.addEventListener('pointermove', (e) => this.move(e), { passive: true });
    host.addEventListener('pointerleave', () => this.hover(null));
    canvas.on('dblclick', (e) => this.dbl(e.px, e.py));
    this.edit.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); void this.commit(); }
      else if (e.key === 'Escape') { e.preventDefault(); this.close(); }
    });
    this.edit.addEventListener('blur', () => this.close());
  }

  private move(e: PointerEvent): void {
    if (e.buttons !== 0) return;
    const r = this.host.getBoundingClientRect();
    this.hover(this.canvas.markAt(e.clientX - r.left, e.clientY - r.top));
  }

  private hover(hit: MarkHit | null): void {
    const same = !!hit && !!this.last && hit.id === this.last.id && hit.kind === this.last.kind;
    this.last = hit;
    this.canvas.setMarkHover(hit);
    if (!hit || this.editing) { if (!this.tip.hidden) this.tip.hidden = true; return; }
    if (!same) this.tip.textContent = markTitle(hit);
    this.tip.style.left = `${Math.round(hit.px)}px`;
    this.tip.style.top = `${Math.round(hit.py + 24)}px`;
    if (this.tip.hidden) this.tip.hidden = false;
  }

  private dbl(px: number, py: number): void {
    const hit = this.canvas.markAt(px, py);
    if (!hit || hit.kind !== 'dim' || !hit.dim) return;
    this.open(hit);
  }

  open(hit: MarkHit): void {
    if (!hit.dim) return;
    this.editing = { hit, name: hit.dim.name };
    this.tip.hidden = true;
    this.edit.value = hit.dim.expr || shownValue(hit.dim.value);
    this.edit.style.left = `${Math.round(hit.px)}px`;
    this.edit.style.top = `${Math.round(hit.py)}px`;
    this.edit.hidden = false;
    this.edit.focus();
    this.edit.select();
  }

  private close(): void {
    if (!this.editing) return;
    this.editing = null;
    this.edit.hidden = true;
  }

  private async commit(): Promise<void> {
    const cur = this.editing;
    const id = docStore.activeId;
    if (!cur || !id) return;
    const expr = this.edit.value.trim();
    this.editing = null;
    this.edit.hidden = true;
    if (!expr) return;
    try {
      await param.edit(id, cur.name, { expr });
    } catch (e) {
      this.report(e);
    }
  }
}

export function markMenu(canvas: CanvasApi, hit: MarkHit, layer: ConstraintLayer | null): MenuEntry[] {
  const id = docStore.activeId;
  const out: MenuEntry[] = [{ label: markTitle(hit).replace(' (double-click to edit)', ''), disabled: true }, { sep: true }];
  if (hit.kind === 'dim' && hit.dim) {
    const d = hit.dim;
    out.push({ label: 'Edit Expression', run: () => layer?.open(hit) });
    out.push({ label: d.driving ? 'Make Reference Only' : 'Make Driving', run: () => { if (id) param.edit(id, d.name, { driving: !d.driving }).catch(reportFailure); } });
  }
  out.push({
    label: 'Select Constrained Objects',
    run: () => {
      const handles = canvas.markHandles(hit.id);
      document.dispatchEvent(new CustomEvent('formcad:set-selection', { detail: { handles, mode: 'set' } }));
    },
  });
  out.push({ label: hit.kind === 'dim' ? 'Delete Dimension' : 'Delete Constraint', run: () => { if (id) param.deleteConstraint(id, hit.id).catch(reportFailure); } });
  return out;
}

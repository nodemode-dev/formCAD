import { el, patchList, q, setClass, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import type { Feature, RefRecord, RefSchema } from './api';

export interface RefItem { send: unknown; text: string; pid?: number }

export interface RefDeps {
  change: () => void;
  togglePick: (view: RefSlotView) => void;
  candidates: (slot: RefSchema) => Feature[];
}

const KIND_WORD: Record<string, string> = { face: 'Faces', edge: 'Edges', vertex: 'Vertices', sketch: 'Sketch', feature: 'Feature', plane: 'Plane' };

export function describeRef(r: RefRecord, byId: (id: string) => Feature | undefined): RefItem {
  if (r.kind === 'feature' && r.id) return { send: r, text: byId(r.id)?.label ?? r.id };
  const key = typeof r.key === 'string' ? r.key : '';
  const pid = typeof r.pid === 'number' ? r.pid : undefined;
  return { send: r, text: key || (pid !== undefined ? `${r.kind} ${pid}` : r.kind), pid };
}

export class RefSlotView {
  readonly row: HTMLElement;
  items: RefItem[] = [];
  dirty = false;
  private readonly list: HTMLElement;
  private readonly pick: HTMLButtonElement | null;
  private readonly select: HTMLSelectElement | null;
  private readonly boxes: HTMLElement | null;
  private readonly hint: HTMLElement;
  private order: string[] = [];

  constructor(readonly slot: RefSchema, private readonly deps: RefDeps) {
    const picks = slot.kind === 'face' || slot.kind === 'edge';
    this.row = el<HTMLElement>(
      `<div class="pp-ref" data-slot="${slot.name}"><div class="pp-ref-head"><span class="pp-lab"></span><span class="pp-hint"></span></div><div class="pp-ref-body"></div></div>`);
    const body = q(this.row, '.pp-ref-body');
    const word = t(slot.label && slot.label !== slot.name ? slot.label : KIND_WORD[slot.kind] ?? slot.kind);
    setText(q(this.row, '.pp-lab'), slot.required ? `${word} *` : word);
    this.hint = q(this.row, '.pp-hint');
    this.list = el<HTMLElement>('<div class="pp-chips"></div>');
    this.pick = null;
    this.select = null;
    this.boxes = null;
    if (picks) {
      this.pick = el<HTMLButtonElement>(`<button class="pp-pick" type="button" aria-pressed="false">${icon('ftPick', 14)}<span class="pp-pick-t"></span></button>`);
      setText(q(this.pick, '.pp-pick-t'), t('Pick in view'));
      this.pick.addEventListener('click', () => deps.togglePick(this));
      body.append(this.pick, this.list);
    } else if (slot.kind === 'sketch' || slot.kind === 'feature') {
      if (slot.multi) {
        this.boxes = el<HTMLElement>('<div class="pp-checks"></div>');
        body.appendChild(this.boxes);
        this.boxes.addEventListener('change', (e) => {
          const box = e.target as HTMLInputElement;
          const id = box.dataset.id ?? '';
          this.order = this.order.filter((x) => x !== id);
          if (box.checked) this.order.push(id);
          this.fromOrder();
        });
      } else {
        this.select = el<HTMLSelectElement>('<select class="cv-input pp-in"></select>');
        body.appendChild(this.select);
        this.select.addEventListener('change', () => { this.order = this.select?.value ? [this.select.value] : []; this.fromOrder(); });
      }
    } else {
      body.appendChild(el('<span class="pp-hint"></span>'));
    }
  }

  get picking(): boolean { return this.pick?.getAttribute('aria-pressed') === 'true'; }
  get kind(): string { return this.slot.kind; }

  setPicking(on: boolean): void {
    if (!this.pick) return;
    this.pick.setAttribute('aria-pressed', String(on));
    setClass(this.pick, 'is-on', on);
  }

  show(on: boolean): void { setHidden(this.row, !on); }

  has(): boolean { return this.items.length > 0; }

  value(): unknown {
    if (this.slot.multi) return this.items.map((i) => i.send);
    return this.items.length ? this.items[0].send : null;
  }

  load(value: RefRecord | RefRecord[] | undefined, byId: (id: string) => Feature | undefined): void {
    const arr = value === undefined ? [] : Array.isArray(value) ? value : [value];
    this.items = arr.map((r) => describeRef(r, byId));
    this.order = arr.filter((r) => r.kind === 'feature' && r.id).map((r) => r.id as string);
    this.dirty = false;
    this.paint();
  }

  options(): void {
    const cands = this.deps.candidates(this.slot);
    if (this.select) {
      const sel = this.select;
      const want = ['', ...cands.map((c) => c.id)];
      const have = Array.from(sel.options).map((o) => o.value);
      if (want.join('|') !== have.join('|') || cands.some((c, i) => sel.options[i + 1]?.textContent !== c.label)) {
        sel.replaceChildren(...want.map((v, i) => { const o = document.createElement('option'); o.value = v; o.textContent = i === 0 ? t('Choose...') : cands[i - 1].label; return o; }));
      }
      sel.value = this.order[0] ?? '';
    }
    if (this.boxes) {
      patchList<Feature>(this.boxes, cands, {
        key: (c) => c.id,
        create: (c) => el<HTMLElement>(`<label class="pp-check pp-chk"><input type="checkbox" data-id="${c.id}"><span></span></label>`),
        update: (n, c) => { setText(q(n, 'span'), c.label); const b = q<HTMLInputElement>(n, 'input'); const on = this.order.includes(c.id); if (b.checked !== on) b.checked = on; },
      });
    }
  }

  private fromOrder(): void {
    this.items = this.order.map((id) => ({ send: { kind: 'feature', id }, text: id }));
    this.dirty = true;
    this.deps.change();
  }

  add(item: RefItem): void {
    const same = (a: RefItem, b: RefItem): boolean => a.pid !== undefined && a.pid === b.pid;
    if (!this.slot.multi) this.items = [item];
    else if (this.items.some((i) => same(i, item))) this.items = this.items.filter((i) => !same(i, item));
    else this.items = [...this.items, item];
    this.dirty = true;
    this.paint();
    this.deps.change();
  }

  private paint(): void {
    setText(this.hint, this.items.length && this.slot.multi ? String(this.items.length) : '');
    patchList<RefItem>(this.list, this.items, {
      key: (i) => `${i.pid ?? i.text}`,
      create: (i) => {
        const n = el<HTMLElement>(`<span class="pp-chip"><span class="pp-chip-t"></span><button class="pp-chip-x" type="button" aria-label="Remove">${icon('close', 10)}</button></span>`);
        q(n, '.pp-chip-x').addEventListener('click', () => {
          const key = n.dataset.key ?? '';
          this.items = this.items.filter((x) => `${x.pid ?? x.text}` !== key);
          this.dirty = true;
          this.paint();
          this.deps.change();
        });
        setText(q(n, '.pp-chip-t'), i.text);
        return n;
      },
      update: (n, i) => setText(q(n, '.pp-chip-t'), i.text),
    });
    if (this.select) this.select.value = this.order[0] ?? '';
  }
}

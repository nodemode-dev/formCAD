import { el, q, setClass, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import type { CatalogueEntry } from './types';

const POOL = 60;

interface Indexed { entry: CatalogueEntry; hay: string; name: string; nick: string; place: string }

export class SearchPopup {
  readonly root: HTMLElement;
  private readonly input: HTMLInputElement;
  private readonly hits: HTMLElement;
  private readonly rows: HTMLElement[] = [];
  private readonly empty: HTMLElement;
  private index: Indexed[] = [];
  private source: readonly CatalogueEntry[] = [];
  private shown: Indexed[] = [];
  private active = 0;
  private pick: ((e: CatalogueEntry) => void) | null = null;
  private accept: ((e: CatalogueEntry) => boolean) | null = null;
  onClose: (() => void) | null = null;

  constructor(parent: HTMLElement) {
    this.root = el('<div class="gx-pop gx-search" role="dialog" aria-label="Add node"><input type="text" spellcheck="false" autocomplete="off"><div class="gx-hits" role="listbox"></div></div>');
    this.input = q<HTMLInputElement>(this.root, 'input');
    this.hits = q(this.root, '.gx-hits');
    this.input.placeholder = t('Search nodes');
    this.empty = el('<div class="gx-empty" hidden></div>');
    this.hits.appendChild(this.empty);
    for (let i = 0; i < POOL; i++) {
      const r = el('<div class="gx-hit" role="option" hidden><span class="gx-hit-name"></span><span class="gx-hit-sub"></span></div>');
      r.dataset.i = String(i);
      this.hits.appendChild(r);
      this.rows.push(r);
    }
    this.input.addEventListener('input', () => this.refresh());
    this.input.addEventListener('keydown', (e) => this.key(e));
    this.hits.addEventListener('pointermove', (e) => {
      const r = (e.target as Element).closest<HTMLElement>('.gx-hit');
      if (r && r.dataset.i !== undefined) this.setActive(Number(r.dataset.i), false);
    });
    this.hits.addEventListener('click', (e) => {
      const r = (e.target as Element).closest<HTMLElement>('.gx-hit');
      if (r && r.dataset.i !== undefined) { this.setActive(Number(r.dataset.i), false); this.choose(); }
    });
    this.root.addEventListener('pointerdown', (e) => e.stopPropagation());
    parent.appendChild(this.root);
  }

  get isOpen(): boolean { return this.root.classList.contains('is-open'); }

  private reindex(entries: readonly CatalogueEntry[]): void {
    if (entries === this.source) return;
    this.source = entries;
    this.index = entries.filter((e) => !e.obsolete).map((e) => ({
      entry: e,
      name: e.name.toLowerCase(),
      nick: (e.nick ?? '').toLowerCase(),
      place: `${e.category} ${e.group ?? ''}`.toLowerCase(),
      hay: `${e.name} ${e.nick ?? ''} ${e.category} ${e.group ?? ''} ${e.id} ${e.description ?? ''}`.toLowerCase(),
    }));
  }

  open(x: number, y: number, bounds: { w: number; h: number }, entries: readonly CatalogueEntry[], pick: (e: CatalogueEntry) => void, accept?: (e: CatalogueEntry) => boolean): void {
    this.reindex(entries);
    this.pick = pick;
    this.accept = accept ?? null;
    this.input.value = '';
    this.root.classList.add('is-open');
    const w = this.root.offsetWidth, h = this.root.offsetHeight;
    this.root.style.transform = `translate(${Math.max(4, Math.min(x, bounds.w - w - 4))}px,${Math.max(4, Math.min(y, bounds.h - h - 4))}px)`;
    this.refresh();
    this.input.focus();
  }

  close(): void {
    if (!this.isOpen) return;
    this.root.classList.remove('is-open');
    this.pick = null;
    this.onClose?.();
  }

  private refresh(): void {
    const terms = this.input.value.toLowerCase().split(/\s+/).filter(Boolean);
    const scored: Array<{ it: Indexed; s: number }> = [];
    for (const it of this.index) {
      if (this.accept && !this.accept(it.entry)) continue;
      let s = 0;
      let ok = true;
      for (const term of terms) {
        if (!it.hay.includes(term)) { ok = false; break; }
        s += it.name.startsWith(term) ? 0 : it.name.includes(term) ? 1 : it.nick.includes(term) ? 2 : it.place.includes(term) ? 3 : 4;
      }
      if (ok) scored.push({ it, s });
      if (terms.length === 0 && scored.length >= POOL) break;
    }
    if (terms.length) scored.sort((a, b) => a.s - b.s || a.it.name.localeCompare(b.it.name));
    this.shown = scored.slice(0, POOL).map((x) => x.it);
    for (let i = 0; i < POOL; i++) {
      const r = this.rows[i];
      const it = this.shown[i];
      setHidden(r, !it);
      if (it) {
        setText(r.children[0], it.entry.name);
        const ins = it.entry.inputs.length, outs = it.entry.outputs.length;
        setText(r.children[1], `${it.entry.category}${it.entry.group ? ` · ${it.entry.group}` : ''} · ${ins} ${t('in')}, ${outs} ${t('out')}`);
      }
    }
    setHidden(this.empty, this.shown.length !== 0);
    setText(this.empty, this.shown.length ? '' : t('No matching nodes'));
    this.setActive(0, true);
    this.hits.scrollTop = 0;
  }

  private setActive(i: number, scroll: boolean): void {
    this.active = Math.max(0, Math.min(this.shown.length - 1, i));
    for (let k = 0; k < POOL; k++) setClass(this.rows[k], 'is-active', k === this.active && k < this.shown.length);
    if (scroll) this.rows[this.active]?.scrollIntoView({ block: 'nearest' });
  }

  private choose(): void {
    const it = this.shown[this.active];
    const fn = this.pick;
    if (!it || !fn) return;
    this.close();
    fn(it.entry);
  }

  private key(e: KeyboardEvent): void {
    if (e.key === 'ArrowDown') { e.preventDefault(); this.setActive(this.active + 1, true); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.setActive(this.active - 1, true); }
    else if (e.key === 'PageDown') { e.preventDefault(); this.setActive(this.active + 6, true); }
    else if (e.key === 'PageUp') { e.preventDefault(); this.setActive(this.active - 6, true); }
    else if (e.key === 'Enter') { e.preventDefault(); this.choose(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); }
    else e.stopPropagation();
  }
}

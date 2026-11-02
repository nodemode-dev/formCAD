import { api, type FileItem } from '../io/api';
import { filterRecent, readHome, toMillis, writeHome } from './doc-store';
import { el, patchList, q, setClass, setHidden, setText, setTitle } from './dom';
import { icon } from './icons';

export interface HomeFilesDeps {
  openPath: (path: string) => void;
}

export type FilesTab = 'recent' | 'projects' | 'outputs';
type Sort = 'opened' | 'name' | 'size' | 'kind';
type View = 'grid' | 'list';

interface Row { key: string; name: string; kind: string; size: number; when: number; where: string }

function readPrefs(): { sort: Sort; view: View } {
  const out = { sort: 'opened' as Sort, view: 'grid' as View };
  const v = readHome();
  if (v.sort === 'opened' || v.sort === 'name' || v.sort === 'size' || v.sort === 'kind') out.sort = v.sort;
  if (v.view === 'grid' || v.view === 'list') out.view = v.view;
  return out;
}

const sizeText = (n: number): string => (n <= 0 ? '' : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function whenText(ms: number): string {
  if (!ms) return '';
  const s = (Date.now() - ms) / 1000;
  if (s < 60) return 'Just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return new Date(ms).toLocaleDateString(undefined, { dateStyle: 'medium' });
}

const kindOf = (item: FileItem): string => (item.kind || /\.([A-Za-z0-9]+)$/.exec(item.name)?.[1] || 'fcad').toUpperCase();

const EMPTY: Record<FilesTab, string> = {
  recent: 'Drawings and models you open or save appear here.',
  projects: 'No projects in the library yet. Save a document to add it.',
  outputs: 'Exports appear here once you export a drawing or a model.',
};

export class HomeFiles {
  readonly root = el(`<div class="cv-hf">
    <div class="cv-hf-bar">
      <label class="cv-hf-filter">${icon('search', 14)}<input class="cv-hf-input" type="search" placeholder="Filter files" aria-label="Filter files" spellcheck="false"></label>
      <label class="cv-hf-sortbox"><span>Sort</span><select class="cv-hf-sort" aria-label="Sort by"><option value="opened">Most recent</option><option value="name">Name</option><option value="size">Size</option><option value="kind">Kind</option></select></label>
      <div class="cv-hf-views" role="group" aria-label="View">
        <button class="cv-hf-view" type="button" data-view="grid" title="Tiles" aria-label="Tiles">${icon('viewGrid', 16)}</button>
        <button class="cv-hf-view" type="button" data-view="list" title="List" aria-label="List">${icon('viewList', 16)}</button>
      </div>
    </div>
    <div class="cv-hf-head" aria-hidden="true"><span></span><span>Name</span><span>Kind</span><span>Size</span><span>Modified</span></div>
    <div class="cv-hf-items" role="list"></div>
    <p class="cv-hf-empty" hidden></p>
  </div>`);
  private readonly items = q(this.root, '.cv-hf-items');
  private readonly empty = q(this.root, '.cv-hf-empty');
  private readonly filter = q<HTMLInputElement>(this.root, '.cv-hf-input');
  private readonly sort = q<HTMLSelectElement>(this.root, '.cv-hf-sort');
  private prefs = readPrefs();
  private all: Row[] = [];
  private run = 0;

  constructor(private readonly d: HomeFilesDeps, private readonly tab: FilesTab, private readonly opts: { limit?: number; compact?: boolean; onCount?: (n: number) => void } = {}) {
    setClass(this.root, 'is-compact', !!opts.compact);
    if (opts.compact) this.prefs.view = 'grid';
    this.sort.value = this.prefs.sort;
    for (const b of Array.from(this.root.querySelectorAll<HTMLButtonElement>('.cv-hf-view'))) {
      b.addEventListener('click', () => {
        this.prefs.view = b.dataset.view as View;
        writeHome({ view: this.prefs.view });
        this.chrome();
      });
    }
    this.sort.addEventListener('change', () => {
      this.prefs.sort = this.sort.value as Sort;
      writeHome({ sort: this.prefs.sort });
      this.render();
    });
    this.filter.addEventListener('input', () => this.render());
    this.items.addEventListener('click', (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>('.cv-hf-item');
      const item = row ? this.all.find((i) => i.key === row.dataset.key) : undefined;
      if (item) this.d.openPath(item.where);
    });
    this.chrome();
  }

  private chrome(): void {
    for (const b of Array.from(this.root.querySelectorAll<HTMLElement>('.cv-hf-view'))) {
      const on = b.dataset.view === this.prefs.view;
      setClass(b, 'is-active', on);
      if (b.getAttribute('aria-pressed') !== String(on)) b.setAttribute('aria-pressed', String(on));
    }
    setClass(this.root, 'is-list', this.prefs.view === 'list' && !this.opts.compact);
  }

  async refresh(): Promise<void> {
    const run = ++this.run;
    let list: FileItem[] = [];
    try {
      const res = this.tab === 'projects' ? await api.library() : this.tab === 'outputs' ? await api.outputs() : await api.recent();
      list = this.tab === 'recent' ? filterRecent(res.items) : res.items;
    } catch {
      list = [];
    }
    if (run !== this.run) return;
    this.all = list.map((i) => ({ key: i.path || i.name, name: i.name, kind: kindOf(i), size: i.size, when: toMillis(i.modified), where: i.path }));
    this.opts.onCount?.(this.all.length);
    this.render();
  }

  private render(): void {
    const f = this.filter.value.trim().toLowerCase(), sort = this.prefs.sort;
    const shown = this.all.filter((i) => !f || i.name.toLowerCase().includes(f) || i.kind.toLowerCase() === f);
    if (sort === 'name') shown.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    else if (sort === 'size') shown.sort((a, b) => b.size - a.size);
    else if (sort === 'kind') shown.sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name));
    else shown.sort((a, b) => b.when - a.when);
    if (this.opts.limit) shown.splice(this.opts.limit);
    patchList(this.items, shown, { key: (i) => i.key, create: (i) => this.row(i), update: (n, i) => this.fillRow(n, i) });
    setText(this.empty, this.all.length === 0 ? EMPTY[this.tab] : 'No files match the filter.');
    setHidden(this.empty, shown.length > 0);
  }

  private row(i: Row): HTMLElement {
    const n = el(`<div class="cv-hf-item" role="listitem"><button class="cv-hf-open" type="button"><span class="cv-hf-thumb"><span class="cv-hf-glyph">${icon('fileImage', 22)}</span></span><span class="cv-hf-name"></span><span class="cv-hf-kind"></span><span class="cv-hf-size"></span><span class="cv-hf-when"></span></button></div>`);
    this.fillRow(n, i);
    return n;
  }

  private fillRow(n: HTMLElement, i: Row): void {
    setText(q(n, '.cv-hf-name'), i.name);
    setText(q(n, '.cv-hf-kind'), i.kind);
    setText(q(n, '.cv-hf-size'), sizeText(i.size));
    setText(q(n, '.cv-hf-when'), whenText(i.when));
    setTitle(q(n, '.cv-hf-open'), i.where);
  }
}

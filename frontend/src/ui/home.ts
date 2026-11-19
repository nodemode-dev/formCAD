import type { DocSummary } from '../io/api';
import { commands } from './commands';
import { DEMOS, isDemo, openDemo, type DemoId } from './demos';
import type { DocStore } from './doc-store';
import { el, escapeHtml, isMac, patchList, pendingClass, q, setClass, setHidden, setText, setTitle } from './dom';
import { HomeFiles, type FilesTab } from './home-files';
import { icon } from './icons';
import { toast } from './toast';

export interface HomeDeps {
  docs: DocStore;
  autoShow: () => boolean;
  afterClose: () => boolean;
  newFromTemplate: (template: string, name: string) => void;
  openPath: (path: string) => void;
}

type Page = 'start' | 'templates' | FilesTab;

type Category = 'Drawing' | 'Model' | 'Graph';

interface Template { id: string; name: string; meta: string; cat: Category; icon?: string; sheet?: [number, number] }

export const TEMPLATES: readonly Template[] = [
  { id: 'drawing-mm-a3', name: '2D drawing, mm', meta: 'A3 sheet · 420 x 297 mm', cat: 'Drawing', sheet: [420, 297] },
  { id: 'drawing-inch-ansi-b', name: '2D drawing, inch', meta: 'ANSI B · 17 x 11 in', cat: 'Drawing', sheet: [17, 11] },
  { id: 'part', name: 'Part', meta: 'Solid part model', cat: 'Model', icon: 'part' },
  { id: 'assembly', name: 'Assembly', meta: 'Components and joints', cat: 'Model', icon: 'assembly' },
  { id: 'drawing-sheet', name: 'Drawing sheet', meta: 'Title block and views', cat: 'Drawing', icon: 'drawing' },
  { id: 'surface', name: 'Surface model', meta: 'Free-form surfaces', cat: 'Model', icon: 'surface' },
  { id: 'form', name: 'Form model', meta: 'Direct form modeling', cat: 'Model', icon: 'cube' },
  { id: 'graph', name: 'Graph', meta: 'Parametric node graph', cat: 'Graph', icon: 'graph' },
];

const CATEGORIES: readonly ('All' | Category)[] = ['All', 'Drawing', 'Model', 'Graph'];

const FORMATS = ['FCAD', 'DXF', 'DWG', 'STEP', 'IGES', '3DM', 'STL', '3MF', 'OBJ', 'SVG'];

const PAGE_TEXT: Record<FilesTab, { title: string; sub: string }> = {
  recent: { title: 'Recent', sub: 'Drawings and models you opened or saved, newest first.' },
  projects: { title: 'Projects', sub: 'Everything in the project library folder.' },
  outputs: { title: 'Outputs', sub: 'Drawings and files you exported, newest first.' },
};

export class HomeScreen {
  readonly root = el('<section class="cv-home" aria-label="Home" hidden></section>');
  private readonly pages = new Map<Page, HomeFiles>();
  private page: Page = 'start';
  private forced = false;
  private lastCount = 0;
  private hadDocument = false;
  private readonly back: HTMLElement;
  private readonly openWrap: HTMLElement;
  private readonly openList: HTMLElement;
  private demoBusy = false;
  private cat: 'All' | Category = 'All';
  private query = '';
  private onShown: Array<(shown: boolean) => void> = [];

  constructor(host: HTMLElement, private readonly d: HomeDeps) {
    const mod = isMac ? '⌘' : 'Ctrl';
    const navItem = (v: Page, ic: string, label: string): string => `<button class="cv-home-nav-item" type="button" data-v="${v}">${icon(ic, 16)}<span>${label}</span>${v === 'start' ? '' : '<span class="cv-home-count">0</span>'}</button>`;
    const cmdItem = (cmd: string, ic: string, label: string): string => `<button class="cv-home-nav-item" type="button" data-cmd="${cmd}">${icon(ic, 16)}<span>${label}</span></button>`;
    const key = (k: string): string => `<kbd class="cv-key">${mod}</kbd><kbd class="cv-key">${k}</kbd>`;
    const formats = FORMATS.map((f) => `<span class="cv-home-format">${f}</span>`).join('');
    const tiles = TEMPLATES.map((p, i) => {
      const art = p.sheet ? `<span class="cv-home-sheet" style="aspect-ratio: ${p.sheet[0]} / ${p.sheet[1]}"></span>` : icon(p.icon ?? 'file', 28);
      return `<button class="cv-card" type="button" data-template="${i}"><span class="cv-card-preview is-art" aria-hidden="true">${art}</span><span class="cv-card-body"><span class="cv-card-name">${p.name}</span><span class="cv-card-meta">${p.cat} · ${p.meta}</span></span></button>`;
    }).join('');
    const chips = CATEGORIES.map((c) => `<button class="cv-chip" type="button" data-cat="${c}">${c}<span class="cv-chip-count">${c === 'All' ? TEMPLATES.length : TEMPLATES.filter((t) => t.cat === c).length}</span></button>`).join('');
    const filters = `<div class="cv-home-filters">${chips}</div><label class="cv-home-search">${icon('search', 14)}<input class="cv-home-search-input" type="search" placeholder="Search templates" aria-label="Search templates" spellcheck="false"></label>`;
    const tplGrid = `<div class="cv-card-grid cv-tpl-grid">${tiles}</div><p class="cv-home-none" hidden>No templates match.</p>`;
    const demos = DEMOS.map((m) => `<button class="cv-card" type="button" data-demo="${m.id}"><span class="cv-card-preview" aria-hidden="true"><img alt="" decoding="async" draggable="false" width="640" height="400" src="${m.picture}"></span><span class="cv-card-body"><span class="cv-card-name">${escapeHtml(m.title)}</span><span class="cv-card-meta" title="${escapeHtml(m.line)}">${escapeHtml(m.line)}</span></span></button>`).join('');
    const nav = `${navItem('start', 'home', 'Start')}${navItem('recent', 'history', 'Recent')}${navItem('templates', 'sheet', 'Templates')}${navItem('projects', 'folder', 'Projects')}${navItem('outputs', 'download', 'Outputs')}`;
    const narrowItem = (v: Page, ic: string, label: string): string => `<button class="cv-home-nav-item" type="button" data-v="${v}">${icon(ic, 16)}<span>${label}</span></button>`;
    const narrow = `${narrowItem('start', 'home', 'Start')}${narrowItem('recent', 'history', 'Recent')}${narrowItem('templates', 'sheet', 'Templates')}${narrowItem('projects', 'folder', 'Projects')}${narrowItem('outputs', 'download', 'Outputs')}`;
    const blank = (cls: string, ic: string, name: string, meta: string): string => `<button class="cv-card ${cls}" type="button" tabindex="-1" aria-hidden="true"${ic ? ' hidden' : ''}><span class="cv-card-preview${ic ? ' is-blank' : ''}">${ic ? icon(ic, 28) : ''}</span><span class="cv-card-body"><span class="cv-card-name">${name}</span><span class="cv-card-meta">${meta}</span></span></button>`;
    const recentAux = `<div class="cv-card-grid cv-home-recent-aux">${blank('is-skeleton', '', '&nbsp;', '&nbsp;')}${blank('is-empty', 'drawing', 'No drawings yet', 'Open a file or start from a template')}</div>`;
    const filesPage = (p: FilesTab, extra = ''): string => `<div class="cv-home-page" data-page="${p}" hidden><div class="cv-home-head"><div><h1 class="cv-home-title">${PAGE_TEXT[p].title}</h1><p class="cv-home-sub">${PAGE_TEXT[p].sub}</p></div>${extra}</div><div class="cv-home-slot" data-slot="${p}"></div></div>`;
    const mark = `<img class="cv-home-mark" src="${import.meta.env.BASE_URL}favicon.png" width="26" height="26" alt="" draggable="false">`;
    this.root.innerHTML = `<nav class="cv-home-nav" aria-label="Home">
      <div class="cv-home-brand" translate="no">${mark}formCAD <span>by nodemode.ai</span></div>
      ${nav}
      <div class="cv-home-open" hidden><div class="cv-home-nav-sep"></div><div class="cv-home-nav-title">Open drawings</div><div class="cv-home-open-list"></div></div>
      <div class="cv-home-nav-sep"></div>
      <div class="cv-home-nav-title">Create</div>
      ${cmdItem('new', 'newFile', 'New drawing')}${cmdItem('open', 'folderOpen', 'Open')}${cmdItem('x:import', 'importFile', 'Import')}
      <div class="cv-home-nav-foot"><button class="cv-home-nav-item cv-home-back" type="button" data-back hidden>${icon('chevronLeft', 16)}<span>Back to drawing</span></button>${cmdItem('settings', 'settings', 'Preferences')}${cmdItem('help', 'info', 'Help')}</div>
    </nav>
    <div class="cv-home-resizer" role="separator" aria-orientation="vertical" aria-label="Resize the side panel"></div>
    <button class="cv-home-nav-hide" type="button" title="Hide the side panel" aria-label="Hide the side panel">${icon('chevronLeft', 14)}</button>
    <button class="cv-home-nav-show" type="button" title="Show the side panel" aria-label="Show the side panel">${icon('chevronRight', 14)}</button>
    <div class="cv-home-main">
      <div class="cv-home-narrow">${narrow}</div>
      <div class="cv-home-page" data-page="start">
        <div class="cv-home-head"><div><h1 class="cv-home-title"></h1><p class="cv-home-sub">Open a drawing or a model, or start from a template.</p></div><div class="cv-home-head-actions"><button class="cv-btn" type="button" data-cmd="open">${icon('folderOpen', 14)}Open file</button><button class="cv-btn" type="button" data-cmd="new">${icon('newFile', 14)}Blank drawing</button></div></div>
        <div class="cv-home-hero">
          <span class="cv-home-hero-icon">${icon('drawing', 26)}</span>
          <div class="cv-home-hero-text"><div class="cv-home-hero-title">Start a drawing or open a model</div>
            <div class="cv-home-hero-sub">Drop a .fcad or .dxf file anywhere in the window to open it. Other formats come in through Import.</div>
            <div class="cv-home-formats">${formats}</div></div>
          <div class="cv-home-hero-actions">
            <button class="cv-home-action is-primary" type="button" data-cmd="new">${icon('newFile', 14)}<span class="cv-home-label">New drawing...</span>${key('N')}</button>
            <button class="cv-home-action" type="button" data-cmd="open">${icon('folderOpen', 14)}<span class="cv-home-label">Open...</span>${key('O')}</button>
            <button class="cv-home-action is-ghost" type="button" data-cmd="x:import">${icon('importFile', 14)}<span class="cv-home-label">Import...</span></button>
          </div>
        </div>
        <section class="cv-home-section"><div class="cv-home-section-head"><h2 class="cv-home-section-title">Recent</h2><button class="cv-btn cv-btn-ghost" type="button" data-v="recent">See all</button></div><div class="cv-home-slot" data-slot="start"></div>${recentAux}</section>
        <section class="cv-home-section" data-section="demos"><div class="cv-home-section-head"><h2 class="cv-home-section-title">Demos</h2><span class="cv-home-section-note">Each opens as a new untitled copy</span></div><div class="cv-card-grid cv-demo-grid">${demos}</div></section>
        <section class="cv-home-section"><div class="cv-home-section-head"><h2 class="cv-home-section-title">New from template</h2><button class="cv-btn cv-btn-ghost" type="button" data-v="templates">See all</button>${filters}</div>${tplGrid}</section>
      </div>
      ${filesPage('recent')}
      <div class="cv-home-page" data-page="templates" hidden><div class="cv-home-head"><div><h1 class="cv-home-title">Templates</h1><p class="cv-home-sub">Start a new drawing or model from one of ${TEMPLATES.length} templates.</p></div><div class="cv-home-head-actions"><button class="cv-btn" type="button" data-cmd="new">${icon('newFile', 14)}Blank drawing</button></div></div><div class="cv-home-section-head">${filters}</div>${tplGrid}</div>${filesPage('projects', `<div class="cv-home-head-actions"><button class="cv-btn" type="button" data-cmd="settings">${icon('folder', 14)}Library folder...</button></div>`)}${filesPage('outputs')}
    </div>`;
    this.back = q(this.root, '[data-back]');
    const files = { openPath: d.openPath };
    const count = (v: FilesTab) => (n: number): void => {
      for (const c of Array.from(this.root.querySelectorAll(`[data-v="${v}"] .cv-home-count`))) setText(c, String(n));
    };
    const mount = (slot: Page, f: HomeFiles): void => {
      q(this.root, `[data-slot="${slot}"]`).appendChild(f.root);
      this.pages.set(slot, f);
    };
    const recentCount = count('recent');
    mount('start', new HomeFiles(files, 'recent', { limit: 8, compact: true, onCount: (n) => { recentCount(n); this.recentAux(n); } }));
    mount('recent', new HomeFiles(files, 'recent', { onCount: count('recent') }));
    mount('projects', new HomeFiles(files, 'projects', { onCount: count('projects') }));
    mount('outputs', new HomeFiles(files, 'outputs', { onCount: count('outputs') }));
    for (const c of Array.from(this.root.querySelectorAll('[data-v="templates"] .cv-home-count'))) setText(c, String(TEMPLATES.length));
    for (const img of Array.from(this.root.querySelectorAll<HTMLImageElement>('.cv-card-preview img'))) img.addEventListener('error', () => setHidden(img, true), { once: true });
    this.openWrap = q(this.root, '.cv-home-open');
    this.openList = q(this.root, '.cv-home-open-list');
    this.sidePanel();
    for (const input of Array.from(this.root.querySelectorAll<HTMLInputElement>('.cv-home-search-input'))) input.addEventListener('input', () => { this.query = input.value; this.filterTemplates(); });
    this.filterTemplates();
    this.root.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      if (target.closest('[data-back]')) { this.forced = false; this.sync(); return; }
      const v = (target.closest('[data-v]') as HTMLElement | null)?.dataset.v as Page | undefined;
      if (v) { this.show(v); return; }
      const chip = (target.closest('.cv-chip') as HTMLElement | null)?.dataset.cat;
      if (chip) { this.cat = chip as 'All' | Category; this.filterTemplates(); return; }
      if (target.closest('[data-cmd]')) return;
      const docId = (target.closest('[data-doc]') as HTMLElement | null)?.dataset.doc;
      if (docId) { d.docs.switchTo(docId); this.forced = false; this.sync(); return; }
      const card = target.closest<HTMLElement>('[data-demo]');
      if (card && isDemo(card.dataset.demo)) { void this.demo(card.dataset.demo, card); return; }
      const at = (target.closest('[data-template]') as HTMLElement | null)?.dataset.template;
      const tpl = at !== undefined ? TEMPLATES[Number(at)] : undefined;
      if (tpl) d.newFromTemplate(tpl.id, tpl.name);
    });
    host.appendChild(this.root);
    d.docs.onChange(() => this.sync());
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.forced && d.docs.docs.length && !e.defaultPrevented) { this.forced = false; this.sync(); }
    });
    this.paint();
    this.sync();
  }

  onVisibility(fn: (shown: boolean) => void): void { this.onShown.push(fn); }

  private sidePanel(): void {
    const root = this.root;
    const bar = q(root, '.cv-home-resizer');
    const save = (): void => {
      try {
        localStorage.setItem('formCAD.homeNav', root.style.getPropertyValue('--cv-home-nav-w'));
        localStorage.setItem('formCAD.homeNavHidden', root.classList.contains('is-nav-hidden') ? '1' : '0');
      } catch { return; }
    };
    const hide = (on: boolean): void => { setClass(root, 'is-nav-hidden', on); save(); };
    try {
      const w = localStorage.getItem('formCAD.homeNav');
      if (w) root.style.setProperty('--cv-home-nav-w', w.trim());
      if (localStorage.getItem('formCAD.homeNavHidden') === '1') root.classList.add('is-nav-hidden');
    } catch { void 0; }
    q(root, '.cv-home-nav-hide').addEventListener('click', () => hide(true));
    q(root, '.cv-home-nav-show').addEventListener('click', () => hide(false));
    bar.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      const x0 = e.clientX;
      const start = q(root, '.cv-home-nav').getBoundingClientRect().width || 232;
      bar.classList.add('is-dragging');
      const mv = (ev: PointerEvent): void => {
        const raw = start + ev.clientX - x0;
        const collapse = raw < 120;
        if (root.classList.contains('is-nav-hidden') !== collapse) setClass(root, 'is-nav-hidden', collapse);
        if (!collapse) root.style.setProperty('--cv-home-nav-w', `${Math.round(Math.max(180, Math.min(420, raw)))}px`);
      };
      const up = (): void => {
        bar.classList.remove('is-dragging');
        window.removeEventListener('pointermove', mv);
        window.removeEventListener('pointerup', up);
        save();
      };
      window.addEventListener('pointermove', mv);
      window.addEventListener('pointerup', up);
    });
  }

  private filterTemplates(): void {
    const term = this.query.trim().toLowerCase();
    for (const chip of Array.from(this.root.querySelectorAll<HTMLElement>('.cv-chip'))) setClass(chip, 'is-active', chip.dataset.cat === this.cat);
    for (const input of Array.from(this.root.querySelectorAll<HTMLInputElement>('.cv-home-search-input'))) if (input.value !== this.query) input.value = this.query;
    for (const grid of Array.from(this.root.querySelectorAll<HTMLElement>('.cv-tpl-grid'))) {
      let shown = 0;
      for (const card of Array.from(grid.querySelectorAll<HTMLElement>('[data-template]'))) {
        const t = TEMPLATES[Number(card.dataset.template)];
        const on = !!t && (this.cat === 'All' || t.cat === this.cat) && (!term || `${t.name} ${t.cat} ${t.meta}`.toLowerCase().includes(term));
        setHidden(card, !on);
        if (on) shown++;
      }
      const none = grid.nextElementSibling;
      if (none instanceof HTMLElement && none.classList.contains('cv-home-none')) setHidden(none, shown > 0);
    }
  }

  private recentAux(n: number): void {
    const aux = q(this.root, '.cv-home-recent-aux');
    setHidden(q(aux, '.is-skeleton'), true);
    setHidden(q(aux, '.is-empty'), n > 0);
    setHidden(aux, n > 0);
  }

  private async demo(id: DemoId, card: HTMLElement): Promise<void> {
    if (this.demoBusy) return;
    this.demoBusy = true;
    card.setAttribute('aria-busy', 'true');
    const done = pendingClass(card);
    try {
      const doc = await openDemo(id);
      await this.d.docs.refresh();
      this.d.docs.switchTo(doc.id);
      const graph = id === 'graph' ? commands.get('gr-open') : undefined;
      if (graph && !graph.checked?.()) void graph.run();
    } catch (e) {
      toast(`Could not open the demo: ${e instanceof Error ? e.message : String(e)}`, 'error');
    } finally {
      done();
      card.removeAttribute('aria-busy');
      this.demoBusy = false;
    }
  }

  private paintOpen(): void {
    const list = this.d.docs.docs;
    setHidden(this.openWrap, list.length === 0);
    patchList(this.openList, list, {
      key: (doc) => doc.id,
      create: () => el(`<button class="cv-home-nav-item" type="button">${icon('drawing', 16)}<span class="cv-home-open-name"></span></button>`),
      update: (n, doc: DocSummary) => {
        n.dataset.doc = doc.id;
        setText(q(n, '.cv-home-open-name'), doc.dirty ? `${doc.name} *` : doc.name);
        setTitle(n, doc.path ?? doc.name);
        setClass(n, 'is-current', doc.id === this.d.docs.activeId);
      },
    });
  }

  private paint(): void {
    for (const n of Array.from(this.root.querySelectorAll<HTMLElement>('.cv-home-page'))) setHidden(n, n.dataset.page !== this.page);
    for (const n of Array.from(this.root.querySelectorAll<HTMLElement>('.cv-home-nav-item[data-v]'))) setClass(n, 'is-active', n.dataset.v === this.page);
    const h = new Date().getHours();
    setText(this.root.querySelector('[data-page="start"] .cv-home-title'), h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening');
  }

  private fill(): void {
    void this.pages.get(this.page)?.refresh();
    for (const [p, f] of this.pages) {
      if (p !== this.page && p !== 'start' && !(p === 'recent' && this.page === 'start')) void f.refresh();
    }
    if (this.page !== 'start') void this.pages.get('start')?.refresh();
  }

  get isShown(): boolean { return !this.root.hidden; }

  show(page?: Page): void {
    if (page && page !== this.page) {
      this.page = page;
      this.paint();
      if (!this.root.hidden) this.fill();
    }
    this.forced = true;
    this.sync();
  }

  hide(): void {
    this.forced = false;
    this.sync();
  }

  sync(): void {
    const n = this.d.docs.docs.length;
    if (n > this.lastCount) this.forced = false;
    this.lastCount = n;
    if (n > 0) this.hadDocument = true;
    const on = this.forced || (n === 0 && (this.hadDocument ? this.d.afterClose() : this.d.autoShow()));
    const was = !this.root.hidden;
    if (on && !was) { this.paint(); this.fill(); }
    if (on) this.paintOpen();
    setHidden(this.root, !on);
    setHidden(this.back, n === 0);
    if (on !== was) for (const fn of this.onShown) fn(on);
  }
}

const OPENABLE = /\.(fcad|dxf)$/i;

export class DropOverlay {
  private readonly node = el(`<div class="cv-drop" hidden><div class="cv-drop-card">${icon('upload', 28)}<span>Drop a .fcad or .dxf file to open it</span></div></div>`);
  private depth = 0;

  constructor(host: HTMLElement, private readonly openPath: (path: string) => void) {
    host.appendChild(this.node);
    const hasFiles = (e: DragEvent): boolean => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files');
    window.addEventListener('dragenter', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      this.depth++;
      setHidden(this.node, false);
    });
    window.addEventListener('dragover', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    });
    window.addEventListener('dragleave', (e) => {
      if (!hasFiles(e)) return;
      this.depth = Math.max(0, this.depth - 1);
      if (!this.depth) setHidden(this.node, true);
    });
    window.addEventListener('drop', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      this.depth = 0;
      setHidden(this.node, true);
      this.take(Array.from(e.dataTransfer?.files ?? []));
    });
  }

  private take(files: File[]): void {
    for (const f of files) {
      if (!OPENABLE.test(f.name)) {
        toast(`${f.name}: only .fcad and .dxf open by drop. Use Import for other formats.`, 'error');
        continue;
      }
      const path = (f as File & { path?: string }).path;
      if (path) this.openPath(path);
      else toast(`${f.name}: this window does not share the file location. Use Open and type the path.`, 'error');
    }
  }
}

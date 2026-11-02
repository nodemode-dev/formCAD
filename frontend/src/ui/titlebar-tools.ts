import type { Commands } from './commands';
import { el, q, setClass, setHidden, setText, stored, store } from './dom';
import { enhanceSelect } from './dropdown';
import { t } from './i18n';
import { icon } from './icons';
import { readChoice, setTheme } from './themes';

export interface Workspace { id: string; label: string }

export const WORKSPACES: readonly Workspace[] = [
  { id: 'drafting', label: 'Drafting' },
  { id: 'part', label: 'Part' },
  { id: 'assembly', label: 'Assembly' },
  { id: 'surface', label: 'Surface' },
  { id: 'form', label: 'Form' },
  { id: 'drawing', label: 'Drawing' },
  { id: 'graph', label: 'Graph' },
  { id: 'manufacture', label: 'Manufacture' },
  { id: 'simulate', label: 'Simulate' },
  { id: 'render', label: 'Render' },
  { id: 'electronics', label: 'Electronics' },
];

const SEARCH_SLOTS = 8;

export const WORKSPACE_KEY = 'formCAD.workspace';
export const WORKSPACE_LOCK_KEY = 'formCAD.workspaceLock';

export interface TitleToolsDeps {
  commands: Commands;
  arrange: (w: Workspace) => void;
  locked: () => boolean;
  setLocked: (on: boolean) => void;
}

export function savedWorkspace(): Workspace {
  const id = stored(WORKSPACE_KEY);
  return WORKSPACES.find((w) => w.id === id) ?? WORKSPACES[0];
}

export class TitleTools {
  readonly root = el('<div class="cv-title-tools"></div>');
  private readonly ws: HTMLSelectElement;
  private readonly lock: HTMLButtonElement;
  private readonly results = el('<div class="cv-search-results" role="listbox"></div>');
  private readonly pop = el('<div class="cv-search-pop" hidden><input class="cv-search-input" type="search" placeholder="Search commands" aria-label="Search commands"></div>');
  private picked = 0;
  private readonly slots: HTMLButtonElement[] = [];
  private readonly slotIds: (string | null)[] = [];

  constructor(host: HTMLElement, private readonly d: TitleToolsDeps) {
    const theme = el<HTMLButtonElement>(`<button class="cv-tt-btn" type="button" title="Light or dark" aria-label="Light or dark"><span class="cv-tt-sun">${icon('sun', 16)}</span><span class="cv-tt-moon">${icon('moon', 16)}</span></button>`);
    const search = el<HTMLButtonElement>(`<button class="cv-tt-btn" type="button" title="Search commands" aria-label="Search commands">${icon('search', 16)}</button>`);
    const ws = el<HTMLSelectElement>(`<select class="cv-tt-select" aria-label="Workspace">${WORKSPACES.map((w) => `<option value="${w.id}">${w.label}</option>`).join('')}</select>`);
    this.lock = el<HTMLButtonElement>('<button class="cv-tt-btn" type="button"></button>');
    this.ws = ws;

    const syncTheme = (): void => {
      const light = readChoice().theme === 'light';
      setHidden(q(theme, '.cv-tt-sun'), light);
      setHidden(q(theme, '.cv-tt-moon'), !light);
      theme.setAttribute('aria-pressed', String(light));
    };
    theme.addEventListener('click', () => { setTheme(readChoice().theme === 'light' ? 'studio' : 'light'); syncTheme(); });
    document.addEventListener('nm:ui-settings-changed', syncTheme);
    syncTheme();

    ws.value = savedWorkspace().id;
    ws.addEventListener('change', () => this.choose(ws.value));
    this.lock.addEventListener('click', () => { d.setLocked(!d.locked()); this.syncLock(); });
    this.syncLock();

    for (let i = 0; i < SEARCH_SLOTS; i++) {
      const b = el<HTMLButtonElement>('<button class="cv-search-item" type="button" role="option" hidden><span class="cv-search-label"></span><span class="cv-search-keys"></span></button>');
      b.addEventListener('click', () => { const id = this.slotIds[i]; if (id) { this.close(); d.commands.run(id); } });
      this.slots.push(b);
      this.slotIds.push(null);
      this.results.appendChild(b);
    }
    this.pop.appendChild(this.results);
    const input = q<HTMLInputElement>(this.pop, 'input');
    search.addEventListener('click', () => this.open());
    input.addEventListener('input', () => { this.picked = 0; this.fill(input.value); });
    input.addEventListener('keydown', (e) => {
      const n = this.shownCount();
      if (e.key === 'Escape') { e.stopPropagation(); this.close(); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (n) { this.picked = (this.picked + (e.key === 'ArrowDown' ? 1 : n - 1)) % n; this.mark(); }
        return;
      }
      if (e.key === 'Enter' && this.slotIds[this.picked]) this.slots[this.picked].click();
    });
    document.addEventListener('pointerdown', (e) => {
      if (!this.pop.hidden && !this.pop.contains(e.target as Node) && !search.contains(e.target as Node)) this.close();
    });
    this.root.append(theme, search, ws, this.lock, this.pop);
    enhanceSelect(ws);
    host.appendChild(this.root);
  }

  currentId(): string { return this.ws.value; }

  choose(id: string): void {
    const w = WORKSPACES.find((x) => x.id === id);
    if (!w) return;
    if (this.ws.value !== id) this.ws.value = id;
    store(WORKSPACE_KEY, id);
    this.d.arrange(w);
  }

  syncLock(): void {
    const on = this.d.locked();
    const label = on ? 'Unlock the workspace' : 'Lock the workspace';
    if (this.lock.dataset.on !== String(on)) {
      this.lock.dataset.on = String(on);
      this.lock.innerHTML = icon(on ? 'lock' : 'unlock', 16);
    }
    setClass(this.lock, 'is-on', on);
    this.lock.setAttribute('aria-pressed', String(on));
    this.lock.title = t(label);
    this.lock.setAttribute('aria-label', t(label));
  }

  open(): void {
    setHidden(this.pop, false);
    const input = q<HTMLInputElement>(this.pop, 'input');
    input.value = '';
    this.picked = 0;
    this.fill('');
    input.focus();
  }

  close(): void { setHidden(this.pop, true); }

  private fill(needle: string): void {
    const c = this.d.commands, text = needle.trim().toLowerCase();
    const found = c.all().filter((cmd) => c.enabled(cmd) && c.label(cmd) && (!text || t(c.label(cmd)).toLowerCase().includes(text))).slice(0, this.slots.length);
    this.slots.forEach((b, i) => {
      const cmd = found[i];
      this.slotIds[i] = cmd ? cmd.id : null;
      setHidden(b, !cmd);
      if (!cmd) return;
      setText(q(b, '.cv-search-label'), t(c.label(cmd)).replace(/\.\.\.$/, '…'));
      setText(q(b, '.cv-search-keys'), c.keyLabel(cmd));
    });
    this.mark();
  }

  private shownCount(): number { return this.slotIds.filter((id) => id !== null).length; }

  private mark(): void {
    this.slots.forEach((b, i) => {
      setClass(b, 'is-picked', i === this.picked);
      b.setAttribute('aria-selected', String(i === this.picked));
    });
  }
}

export interface MenuEntry {
  label?: string;
  sep?: boolean;
  disabled?: boolean;
  checked?: boolean;
  run?: () => void;
  sub?: MenuEntry[];
  hover?: () => void;
}

const SLOTS = 44;
const SEPS = 14;
const SUB_SLOTS = 28;

class Panel {
  readonly root: HTMLElement;
  private readonly rows: HTMLButtonElement[] = [];
  private readonly labels: HTMLElement[] = [];
  private readonly arrows: HTMLElement[] = [];
  private readonly seps: HTMLElement[] = [];
  private entries: MenuEntry[] = [];

  constructor(slots: number, seps: number, readonly onPick: (e: MenuEntry, row: HTMLButtonElement) => void, readonly onEnter: (e: MenuEntry, row: HTMLButtonElement) => void) {
    this.root = document.createElement('div');
    this.root.className = 'cv-menu cv-canvas-menu';
    this.root.setAttribute('role', 'menu');
    this.root.hidden = true;
    for (let i = 0; i < slots; i++) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'cv-menu-item';
      b.setAttribute('role', 'menuitem');
      b.hidden = true;
      const check = document.createElement('span');
      check.className = 'cv-menu-check';
      check.textContent = '•';
      const label = document.createElement('span');
      label.className = 'cv-menu-label';
      const keys = document.createElement('span');
      keys.className = 'cv-menu-keys';
      b.append(check, label, keys);
      b.dataset.i = String(i);
      b.addEventListener('click', () => { const e = this.entries[i]; if (e && !e.disabled) this.onPick(e, b); });
      b.addEventListener('pointerenter', () => { const e = this.entries[i]; if (e) this.onEnter(e, b); });
      this.rows.push(b);
      this.labels.push(label);
      this.arrows.push(keys);
    }
    for (let i = 0; i < seps; i++) {
      const s = document.createElement('div');
      s.className = 'cv-menu-sep';
      this.seps.push(s);
    }
  }

  set(entries: MenuEntry[]): void {
    this.entries = entries.slice(0, this.rows.length);
    const used: HTMLElement[] = [];
    let si = 0;
    this.rows.forEach((row, i) => {
      const e = this.entries[i];
      if (!e || e.sep) { row.hidden = true; return; }
      row.hidden = false;
      row.disabled = !!e.disabled;
      row.classList.toggle('is-checked', !!e.checked);
      row.classList.toggle('cv-menu-sub', !!e.sub);
      if (this.labels[i].textContent !== e.label) this.labels[i].textContent = e.label ?? '';
      const arrow = e.sub ? '›' : '';
      if (this.arrows[i].textContent !== arrow) this.arrows[i].textContent = arrow;
    });
    this.entries.forEach((e, i) => {
      if (e.sep) {
        const s = this.seps[si++];
        if (s) used.push(s);
      } else used.push(this.rows[i]);
    });
    this.root.replaceChildren(...used);
  }

  rowFor(entry: MenuEntry): HTMLButtonElement | null {
    const i = this.entries.indexOf(entry);
    return i >= 0 ? this.rows[i] : null;
  }

  place(x: number, y: number): void {
    this.root.style.visibility = 'hidden';
    this.root.hidden = false;
    const w = this.root.offsetWidth;
    const h = this.root.offsetHeight;
    const left = Math.max(4, Math.min(x + w <= window.innerWidth - 4 ? x : x - w, window.innerWidth - w - 4));
    const top = Math.max(4, Math.min(y + h <= window.innerHeight - 4 ? y : y - h, window.innerHeight - h - 4));
    this.root.style.left = `${Math.round(left)}px`;
    this.root.style.top = `${Math.round(top)}px`;
    this.root.style.visibility = '';
  }

  hide(): void {
    this.root.hidden = true;
  }
}

export class ContextMenu {
  private readonly main: Panel;
  private readonly side: Panel;
  private subFor: MenuEntry | null = null;
  onClose: (() => void) | null = null;

  constructor() {
    this.main = new Panel(SLOTS, SEPS, (e, row) => this.pick(e, row, this.main), (e, row) => this.enter(e, row));
    this.side = new Panel(SUB_SLOTS, 6, (e) => this.pick(e, null, this.side), (e) => e.hover?.());
    const host = document.getElementById('overlay-root') ?? document.body;
    host.append(this.main.root, this.side.root);
    document.addEventListener('pointerdown', (ev) => {
      if (!this.isOpen) return;
      const t = ev.target as Node;
      if (this.main.root.contains(t) || this.side.root.contains(t)) return;
      this.close();
    }, true);
    for (const p of [this.main.root, this.side.root]) p.addEventListener('contextmenu', (ev) => ev.preventDefault());
  }

  get isOpen(): boolean {
    return !this.main.root.hidden;
  }

  contains(n: Node): boolean {
    return this.main.root.contains(n) || this.side.root.contains(n);
  }

  open(x: number, y: number, entries: MenuEntry[]): void {
    this.subFor = null;
    this.side.hide();
    this.main.set(entries);
    this.main.place(x, y);
  }

  close(): void {
    if (!this.isOpen) return;
    this.main.hide();
    this.side.hide();
    this.subFor = null;
    this.onClose?.();
  }

  private enter(e: MenuEntry, row: HTMLButtonElement): void {
    e.hover?.();
    if (e.sub && !e.disabled) {
      if (this.subFor === e) return;
      this.subFor = e;
      this.side.set(e.sub);
      const r = row.getBoundingClientRect();
      this.side.place(r.right - 2, r.top - 4);
    } else if (this.subFor) {
      this.subFor = null;
      this.side.hide();
    }
  }

  private pick(e: MenuEntry, row: HTMLButtonElement | null, from: Panel): void {
    if (e.sub) {
      if (row) this.enter(e, row);
      return;
    }
    void from;
    this.close();
    e.run?.();
  }
}

import { el, q, setClass, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { groupColours } from './ops';
import type { ModKey, PortMods } from './types';

const MOD_ROWS: Array<[ModKey, string]> = [
  ['reverse', 'Reverse'], ['flatten', 'Flatten'], ['graft', 'Graft'], ['simplify', 'Simplify'], ['principal', 'Principal'], ['invert', 'Invert'],
];

const place = (root: HTMLElement, x: number, y: number, bounds: { w: number; h: number }): void => {
  const w = root.offsetWidth, h = root.offsetHeight;
  root.style.transform = `translate(${Math.max(4, Math.min(x, bounds.w - w - 4))}px,${Math.max(4, Math.min(y, bounds.h - h - 4))}px)`;
};

export class ModsPopover {
  readonly root: HTMLElement;
  private readonly title: HTMLElement;
  private readonly chips = new Map<ModKey, HTMLButtonElement>();
  private readonly expr: HTMLInputElement;
  private target: { node: string; port: string } | null = null;
  onToggle: ((node: string, port: string, key: ModKey, value: boolean) => void) | null = null;
  onExpression: ((node: string, port: string, text: string) => void) | null = null;

  constructor(parent: HTMLElement) {
    this.root = el('<div class="gx-pop gx-mods" role="dialog"><div class="gx-mods-title"></div><div class="gx-mods-grid"></div><input type="text" spellcheck="false" autocomplete="off"></div>');
    this.title = q(this.root, '.gx-mods-title');
    const grid = q(this.root, '.gx-mods-grid');
    for (const [key, label] of MOD_ROWS) {
      const b = el<HTMLButtonElement>('<button class="gx-chip" type="button"></button>');
      b.textContent = t(label);
      b.addEventListener('click', () => {
        if (!this.target) return;
        const on = !b.classList.contains('is-on');
        setClass(b, 'is-on', on);
        this.onToggle?.(this.target.node, this.target.port, key, on);
      });
      grid.appendChild(b);
      this.chips.set(key, b);
    }
    this.expr = q<HTMLInputElement>(this.root, 'input');
    this.expr.placeholder = t('Expression, for example x * 2');
    this.expr.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Enter') { this.commit(); this.close(); }
      if (e.key === 'Escape') this.close();
    });
    this.expr.addEventListener('change', () => this.commit());
    this.root.addEventListener('pointerdown', (e) => e.stopPropagation());
    parent.appendChild(this.root);
  }

  get isOpen(): boolean { return this.root.classList.contains('is-open'); }

  private commit(): void {
    if (this.target) this.onExpression?.(this.target.node, this.target.port, this.expr.value);
  }

  open(node: string, port: string, label: string, mods: PortMods | undefined, x: number, y: number, bounds: { w: number; h: number }): void {
    this.target = { node, port };
    setText(this.title, label);
    for (const [k, b] of this.chips) setClass(b, 'is-on', !!mods?.[k]);
    this.expr.value = mods?.expression ?? '';
    this.root.classList.add('is-open');
    place(this.root, x, y, bounds);
  }

  close(): void {
    if (!this.isOpen) return;
    this.root.classList.remove('is-open');
    this.target = null;
  }

  sync(mods: PortMods | undefined): void {
    if (!this.isOpen) return;
    for (const [k, b] of this.chips) setClass(b, 'is-on', !!mods?.[k]);
    if (document.activeElement !== this.expr) this.expr.value = mods?.expression ?? '';
  }
}

export interface MenuItem { id: string; label: string; swatches?: boolean }

export class ContextMenu {
  readonly root: HTMLElement;
  private readonly buttons: HTMLButtonElement[] = [];
  private readonly sw: HTMLElement;
  private readonly swButtons: HTMLButtonElement[] = [];
  private handler: ((id: string) => void) | null = null;
  private colourHandler: ((colour: string) => void) | null = null;

  constructor(parent: HTMLElement, slots = 12) {
    this.root = el('<div class="gx-pop gx-menu" role="menu"></div>');
    for (let i = 0; i < slots; i++) {
      const b = el<HTMLButtonElement>('<button class="gx-mi" type="button" role="menuitem" hidden></button>');
      b.addEventListener('click', () => { const id = b.dataset.id ?? ''; const fn = this.handler; this.close(); fn?.(id); });
      this.root.appendChild(b);
      this.buttons.push(b);
    }
    this.sw = el('<div class="gx-swatches" hidden></div>');
    for (const c of groupColours()) {
      const b = el<HTMLButtonElement>('<button class="gx-sw" type="button"></button>');
      b.style.background = c;
      b.dataset.colour = c;
      b.addEventListener('click', () => { const fn = this.colourHandler; this.close(); fn?.(c); });
      this.sw.appendChild(b);
      this.swButtons.push(b);
    }
    this.root.appendChild(this.sw);
    this.root.addEventListener('pointerdown', (e) => e.stopPropagation());
    this.root.addEventListener('contextmenu', (e) => e.preventDefault());
    parent.appendChild(this.root);
  }

  get isOpen(): boolean { return this.root.classList.contains('is-open'); }

  open(items: MenuItem[], x: number, y: number, bounds: { w: number; h: number }, run: (id: string) => void, colours?: { current: string; pick: (c: string) => void }): void {
    this.handler = run;
    this.colourHandler = colours?.pick ?? null;
    for (let i = 0; i < this.buttons.length; i++) {
      const b = this.buttons[i];
      const it = items[i];
      setHidden(b, !it);
      if (it) { b.dataset.id = it.id; setText(b, it.label); }
    }
    setHidden(this.sw, !colours);
    if (colours) for (const b of this.swButtons) setClass(b, 'is-on', b.dataset.colour === colours.current);
    this.root.classList.add('is-open');
    place(this.root, x, y, bounds);
  }

  close(): void {
    this.root.classList.remove('is-open');
  }
}

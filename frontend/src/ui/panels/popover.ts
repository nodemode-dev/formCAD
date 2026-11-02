import { el } from '../dom';

const open = new Set<Popover>();
let wired = false;

function wire(): void {
  if (wired) return;
  wired = true;
  document.addEventListener('pointerdown', (e) => {
    for (const p of open) if (!p.root.contains(e.target as Node) && !p.anchor?.contains(e.target as Node)) p.hide();
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !open.size) return;
    for (const p of Array.from(open)) p.hide();
    e.stopPropagation();
  }, true);
}

export class Popover {
  readonly root: HTMLElement;
  anchor: HTMLElement | null = null;
  onHide: (() => void) | null = null;

  constructor(cls: string, width: number) {
    this.root = el<HTMLElement>(`<div class="lm-pop ${cls}" hidden></div>`);
    this.root.style.setProperty('--lm-pop-w', `${width}px`);
    (document.getElementById('overlay-root') ?? document.body).appendChild(this.root);
    wire();
  }

  get isOpen(): boolean { return !this.root.hidden; }

  show(anchor: HTMLElement): void {
    this.anchor = anchor;
    this.root.style.visibility = 'hidden';
    this.root.hidden = false;
    const r = anchor.getBoundingClientRect();
    const w = this.root.offsetWidth, h = this.root.offsetHeight;
    const left = Math.max(4, Math.min(r.left, window.innerWidth - w - 4));
    const below = r.bottom + 2 + h <= window.innerHeight - 4;
    const top = below ? r.bottom + 2 : Math.max(4, r.top - h - 2);
    this.root.style.left = `${left}px`;
    this.root.style.top = `${top}px`;
    this.root.style.visibility = '';
    open.add(this);
  }

  hide(): void {
    if (this.root.hidden) return;
    this.root.hidden = true;
    open.delete(this);
    this.onHide?.();
  }
}

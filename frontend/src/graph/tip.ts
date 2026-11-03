import { el, q, setClass, setDisabled, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import type { MessageLevel } from './types';

const ROWS = 24;
const MSGS = 6;

export interface TipRow { path: string; value: string }
export interface TipMessage { level: MessageLevel; text: string }
export interface TipContent {
  title: string;
  sub: string;
  messages: TipMessage[];
  rows: TipRow[];
  page: number;
  pages: number;
  empty: string;
}

export class TipPopup {
  readonly root: HTMLElement;
  private readonly title: HTMLElement;
  private readonly sub: HTMLElement;
  private readonly rowsHost: HTMLElement;
  private readonly rows: HTMLElement[] = [];
  private readonly msgs: HTMLElement[] = [];
  private readonly prev: HTMLButtonElement;
  private readonly next: HTMLButtonElement;
  private readonly pager: HTMLElement;
  private readonly pageText: HTMLElement;
  private readonly emptyNote: HTMLElement;
  private hideTimer = 0;
  private overTip = false;
  onPage: ((delta: number) => void) | null = null;

  constructor(parent: HTMLElement) {
    this.root = el(
      '<div class="gx-pop gx-tip" role="tooltip"><div class="gx-tip-title"></div><div class="gx-tip-sub"></div><div class="gx-tip-msgs"></div>' +
      '<div class="gx-tip-rows"></div><div class="gx-tip-empty gx-tip-sub"></div>' +
      '<div class="gx-tip-pager"><button class="gx-btn" type="button" data-d="-1"></button><span class="gx-tip-page gx-tip-sub"></span><button class="gx-btn" type="button" data-d="1"></button></div></div>',
    );
    this.title = q(this.root, '.gx-tip-title');
    this.sub = q(this.root, '.gx-tip-sub');
    this.rowsHost = q(this.root, '.gx-tip-rows');
    this.emptyNote = q(this.root, '.gx-tip-empty');
    this.pager = q(this.root, '.gx-tip-pager');
    this.pageText = q(this.root, '.gx-tip-page');
    const buttons = this.root.querySelectorAll<HTMLButtonElement>('.gx-tip-pager button');
    this.prev = buttons[0];
    this.next = buttons[1];
    this.prev.textContent = t('Previous');
    this.next.textContent = t('Next');
    const msgHost = q(this.root, '.gx-tip-msgs');
    for (let i = 0; i < MSGS; i++) {
      const m = el('<div class="gx-tip-msg" hidden></div>');
      msgHost.appendChild(m);
      this.msgs.push(m);
    }
    for (let i = 0; i < ROWS; i++) {
      const r = el('<div class="gx-tip-row" hidden><span class="gx-tip-path"></span><span class="gx-tip-val"></span></div>');
      this.rowsHost.appendChild(r);
      this.rows.push(r);
    }
    this.prev.addEventListener('click', () => this.onPage?.(-1));
    this.next.addEventListener('click', () => this.onPage?.(1));
    this.root.addEventListener('pointerenter', () => { this.overTip = true; window.clearTimeout(this.hideTimer); });
    this.root.addEventListener('pointerleave', () => { this.overTip = false; this.hideSoon(); });
    parent.appendChild(this.root);
  }

  get isOpen(): boolean { return this.root.classList.contains('is-open'); }

  show(c: TipContent, x: number, y: number, bounds: { w: number; h: number }, side: 'left' | 'right' = 'right'): void {
    window.clearTimeout(this.hideTimer);
    setClass(this.root, 'is-live', c.pages > 1 || c.rows.length > 4);
    setText(this.title, c.title);
    setText(this.sub, c.sub);
    for (let i = 0; i < MSGS; i++) {
      const m = this.msgs[i];
      const msg = c.messages[i];
      setHidden(m, !msg);
      if (msg) {
        setText(m, msg.text);
        setClass(m, 'is-error', msg.level === 'error');
        setClass(m, 'is-warning', msg.level === 'warning');
      }
    }
    for (let i = 0; i < ROWS; i++) {
      const r = this.rows[i];
      const row = c.rows[i];
      setHidden(r, !row);
      if (row) {
        setText(r.children[0], row.path);
        setText(r.children[1], row.value);
      }
    }
    setText(this.emptyNote, c.rows.length === 0 ? c.empty : '');
    setHidden(this.emptyNote, c.rows.length !== 0 || c.empty === '');
    const plain = c.rows.length === 0 && c.empty === '';
    setHidden(this.rowsHost, plain);
    const paged = c.pages > 1;
    setHidden(this.pager, !paged);
    setText(this.pageText, `${c.page + 1} / ${c.pages}`);
    setDisabled(this.prev, c.page <= 0);
    setDisabled(this.next, c.page >= c.pages - 1);
    this.root.classList.add('is-open');
    const w = this.root.offsetWidth, h = this.root.offsetHeight;
    const px = Math.max(4, Math.min(side === 'left' ? x - w : x, bounds.w - w - 4));
    const py = Math.max(4, Math.min(y, bounds.h - h - 4));
    this.root.style.transform = `translate(${px}px,${py}px)`;
  }

  hideSoon(delay = 180): void {
    window.clearTimeout(this.hideTimer);
    this.hideTimer = window.setTimeout(() => { if (!this.overTip) this.hide(); }, delay);
  }

  hide(): void {
    window.clearTimeout(this.hideTimer);
    this.overTip = false;
    this.root.classList.remove('is-open');
  }
}

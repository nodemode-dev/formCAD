export interface InputField { label: string; text: string; live: boolean; active: boolean; locked: boolean }

export interface DynView {
  visible: boolean;
  x: number;
  y: number;
  msg: string;
  at: boolean;
  boxes: InputField[];
  arrow: boolean;
  list: { rows: string[]; idx: number } | null;
  badge: boolean;
  badgeX: number;
  badgeY: number;
}

const BOXES = 3;
const ROWS = 16;

export const EMPTY_DYN: DynView = { visible: false, x: 0, y: 0, msg: '', at: false, boxes: [], arrow: false, list: null, badge: false, badgeX: 0, badgeY: 0 };

interface BoxNodes { root: HTMLElement; label: HTMLElement; value: HTMLElement; lock: HTMLElement }

export class DynamicInput {
  private readonly layer: HTMLElement;
  private readonly tip: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly at: HTMLElement;
  private readonly arrow: HTMLElement;
  private readonly boxes: BoxNodes[] = [];
  private readonly list: HTMLElement;
  private readonly rows: HTMLElement[] = [];
  private readonly badge: HTMLElement;
  private readonly host: HTMLElement;
  private w = 0;
  private h = 0;
  private lastKey = '';
  private listKey = '';
  private pos = '';
  private badgePos = '';
  onRow: ((i: number) => void) | null = null;
  onRowHover: ((i: number) => void) | null = null;

  constructor(host: HTMLElement) {
    this.host = host;
    this.layer = document.createElement('div');
    this.layer.className = 'cv-dyn';
    this.layer.setAttribute('aria-hidden', 'true');
    this.tip = document.createElement('div');
    this.tip.className = 'cv-dyn-tip';
    this.tip.hidden = true;
    this.msg = document.createElement('span');
    this.msg.className = 'cv-dyn-msg';
    this.at = document.createElement('span');
    this.at.className = 'cv-dyn-at';
    this.at.textContent = '@';
    this.at.hidden = true;
    this.tip.append(this.msg, this.at);
    for (let i = 0; i < BOXES; i++) {
      const root = document.createElement('span');
      root.className = 'cv-dyn-box';
      root.hidden = true;
      const label = document.createElement('span');
      label.className = 'cv-dyn-label';
      const value = document.createElement('span');
      value.className = 'cv-dyn-value';
      const lock = document.createElement('span');
      lock.className = 'cv-dyn-lock';
      lock.hidden = true;
      lock.textContent = '■';
      root.append(label, value, lock);
      this.tip.append(root);
      this.boxes.push({ root, label, value, lock });
    }
    this.arrow = document.createElement('span');
    this.arrow.className = 'cv-dyn-arrow';
    this.arrow.textContent = '▾';
    this.arrow.hidden = true;
    this.tip.append(this.arrow);
    this.list = document.createElement('div');
    this.list.className = 'cv-dyn-list';
    this.list.hidden = true;
    for (let i = 0; i < ROWS; i++) {
      const r = document.createElement('button');
      r.type = 'button';
      r.className = 'cv-dyn-row';
      r.hidden = true;
      r.addEventListener('click', () => this.onRow?.(i));
      r.addEventListener('pointerenter', () => this.onRowHover?.(i));
      this.rows.push(r);
      this.list.append(r);
    }
    this.badge = document.createElement('span');
    this.badge.className = 'cv-dyn-badge';
    this.badge.hidden = true;
    this.badge.innerHTML = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><rect x="1.5" y="5.5" width="9" height="9" fill="none" stroke="currentColor"/><rect x="5.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor"/></svg>';
    this.layer.append(this.tip, this.list, this.badge);
    host.append(this.layer);
  }

  private setText(n: HTMLElement, t: string): void {
    if (n.textContent !== t) n.textContent = t;
  }

  private place(node: HTMLElement, key: 'pos' | 'badgePos', x: number, y: number): void {
    const v = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
    if (this[key] !== v) {
      this[key] = v;
      node.style.transform = v;
    }
  }

  patch(v: DynView): void {
    const showTip = v.visible && (v.msg !== '' || v.boxes.length > 0);
    if (this.tip.hidden === showTip) this.tip.hidden = !showTip;
    if (showTip) {
      const key = `${v.msg}|${v.at}|${v.arrow}|${v.boxes.map((b) => `${b.label}:${b.text}:${b.live}:${b.active}:${b.locked}`).join(',')}`;
      if (key !== this.lastKey) {
        this.lastKey = key;
        this.setText(this.msg, v.msg);
        if (this.msg.hidden !== (v.msg === '')) this.msg.hidden = v.msg === '';
        if (this.at.hidden === v.at) this.at.hidden = !v.at;
        if (this.arrow.hidden === v.arrow) this.arrow.hidden = !v.arrow;
        this.boxes.forEach((n, i) => {
          const b = v.boxes[i];
          if (n.root.hidden !== !b) n.root.hidden = !b;
          if (!b) return;
          this.setText(n.label, b.label);
          if (n.label.hidden !== (b.label === '')) n.label.hidden = b.label === '';
          this.setText(n.value, b.text);
          n.value.classList.toggle('is-live', b.live);
          n.root.classList.toggle('is-active', b.active);
          if (n.lock.hidden === b.locked) n.lock.hidden = !b.locked;
        });
        this.w = this.tip.offsetWidth;
        this.h = this.tip.offsetHeight;
      }
      const hostW = this.host.clientWidth;
      const hostH = this.host.clientHeight;
      let x = v.x + 18;
      let y = v.y + 14 - this.h;
      if (x + this.w > hostW - 2) x = Math.max(2, v.x - 18 - this.w);
      if (y < 2) y = 2;
      if (y + this.h > hostH - 2) y = hostH - this.h - 2;
      this.place(this.tip, 'pos', x, y);
      this.patchList(v, x, y + this.h);
    } else if (!this.list.hidden) this.list.hidden = true;
    const showBadge = v.visible && v.badge;
    if (this.badge.hidden === showBadge) this.badge.hidden = !showBadge;
    if (showBadge) this.place(this.badge, 'badgePos', v.badgeX + 12, v.badgeY - 22);
  }

  private patchList(v: DynView, x: number, y: number): void {
    const l = v.list;
    if (!l) {
      if (!this.list.hidden) this.list.hidden = true;
      this.listKey = '';
      return;
    }
    if (this.list.hidden) this.list.hidden = false;
    const key = `${l.rows.join('|')}#${l.idx}`;
    if (key !== this.listKey) {
      this.listKey = key;
      this.rows.forEach((r, i) => {
        const t = l.rows[i];
        if (r.hidden !== (t === undefined)) r.hidden = t === undefined;
        if (t !== undefined) this.setText(r, t);
        r.classList.toggle('is-active', i === l.idx);
      });
    }
    this.list.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }

  get listEl(): HTMLElement {
    return this.list;
  }
}

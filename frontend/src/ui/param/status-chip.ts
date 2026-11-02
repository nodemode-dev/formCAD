import { param, type ConstraintStatus } from '../../io/api-param';
import type { CanvasApi } from '../../canvas/types';
import { docStore } from '../doc-store';
import { el, setClass, setHidden, setText, setTitle } from '../dom';
import { t } from '../i18n';

export class ConstraintChip {
  readonly root: HTMLButtonElement;
  private timer = 0;
  private seq = 0;
  private last = '';

  constructor(status: HTMLElement, private readonly canvas: CanvasApi, open: () => void) {
    this.root = el<HTMLButtonElement>('<button class="cv-st-cons" type="button" aria-live="polite"><i class="cv-st-cons-dot"></i><span class="cv-st-cons-text"></span></button>');
    const hint = status.querySelector('.cv-st-hint');
    status.insertBefore(this.root, hint);
    this.root.addEventListener('click', open);
    canvas.on('display', () => this.later());
    docStore.onChange(() => this.later());
    this.paint(null);
  }

  private later(): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => { void this.pull(); }, 140);
  }

  private async pull(): Promise<void> {
    const id = docStore.activeId;
    if (!id || this.canvas.marked() === 0) { this.paint(null); return; }
    const mine = ++this.seq;
    try {
      const s = await param.status(id);
      if (mine === this.seq) this.paint(s);
    } catch {
      if (mine === this.seq) this.paint(null);
    }
  }

  private paint(s: ConstraintStatus | null): void {
    const key = s ? `${s.status}:${s.dof}:${s.dangling.length}` : '';
    if (key === this.last) return;
    this.last = key;
    setClass(this.root, 'is-off', !s);
    this.root.disabled = !s;
    const state = s?.status ?? 'none';
    for (const k of ['fully', 'under', 'over']) setClass(this.root, `is-${k}`, state === k);
    let text = '';
    let title = '';
    if (s) {
      if (s.status === 'over') {
        text = t('Over-constrained');
        title = t('Some constraints repeat or contradict each other. Open the Parameters Manager.');
      } else {
        text = `${t('Degrees of freedom')}: ${s.dof}`;
        title = s.status === 'fully' ? t('Fully constrained') : t('Under-constrained: the shape can still move');
      }
      if (s.dangling.length) title += ` · ${s.dangling.length} ${t('constraints lost their objects')}`;
    }
    setText(this.root.querySelector('.cv-st-cons-text'), text);
    setTitle(this.root, title);
    setHidden(this.root, false);
  }
}

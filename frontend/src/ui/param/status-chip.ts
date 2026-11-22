import { param, type ConstraintStatus } from '../../io/api-param';
import type { CanvasApi, ConstraintState } from '../../canvas/types';
import { docStore } from '../doc-store';
import { el, setClass, setHidden, setText, setTitle } from '../dom';
import { t } from '../i18n';
import { selection as selectionBus } from '../panels/selection-bus';

const RANK: Record<ConstraintState, number> = { none: 0, fully: 1, under: 2, over: 3 };

export class ConstraintChip {
  readonly root: HTMLButtonElement;
  private timer = 0;
  private seq = 0;
  private last = '';
  private status: ConstraintStatus | null = null;

  constructor(status: HTMLElement, private readonly canvas: CanvasApi, open: () => void) {
    this.root = el<HTMLButtonElement>('<button class="cv-st-cons" type="button" aria-live="polite"><i class="cv-st-cons-dot"></i><span class="cv-st-cons-text"></span></button>');
    const hint = status.querySelector('.cv-st-hint');
    status.insertBefore(this.root, hint);
    this.root.addEventListener('click', open);
    canvas.on('display', () => { this.paint(this.status); this.later(); });
    selectionBus.onChange(() => this.paint(this.status));
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

  private picked(): { state: ConstraintState; dof: number } | null {
    if (selectionBus.doc !== docStore.activeId || selectionBus.handles.length === 0) return null;
    let state: ConstraintState = 'none';
    let dof = 0;
    for (const h of selectionBus.handles) {
      const bar = this.canvas.barFor(h);
      if (!bar || bar.state === 'none') continue;
      if (RANK[bar.state] > RANK[state]) state = bar.state;
      dof += bar.dof;
    }
    return state === 'none' ? null : { state, dof };
  }

  private paint(s: ConstraintStatus | null): void {
    this.status = s;
    const sel = s ? this.picked() : null;
    const key = s ? `${s.status}:${s.dof}:${s.dangling.length}:${sel ? `${sel.state}:${sel.dof}` : ''}` : '';
    if (key === this.last) return;
    this.last = key;
    setClass(this.root, 'is-off', !s);
    this.root.disabled = !s;
    const state = sel?.state ?? s?.status ?? 'none';
    for (const k of ['fully', 'under', 'over']) setClass(this.root, `is-${k}`, state === k);
    let text = '';
    let title = '';
    if (s && sel) {
      text = sel.state === 'over' ? `${t('Selection')}: ${t('Over-constrained')}` : `${t('Selection')} · ${t('DOF')}: ${sel.dof}`;
      title = `${t('Selection')}: ${sel.state === 'over' ? t('Over-constrained') : sel.state === 'fully' ? t('Fully constrained') : t('Under-constrained: the shape can still move')}`;
    } else if (s) {
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

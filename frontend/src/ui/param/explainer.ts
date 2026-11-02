import { param, type Explanation, type ExplainItem } from '../../io/api-param';
import { zoomToHandles } from '../panels/engine-run';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setHidden, setText } from '../dom';
import { icon } from '../icons';
import { t } from '../i18n';
import { toast } from '../toast';

const ROWS = 6;

export class ConflictExplainer extends Dialog {
  private readonly lead: HTMLElement;
  private readonly list: HTMLElement;
  private readonly note: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly show: HTMLButtonElement;
  private items: ExplainItem[] = [];

  constructor() {
    super('Constraint Conflict', 520);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="pm-ex"><p class="pm-ex-lead"></p><div class="pm-ex-list" role="list"></div><p class="cv-note pm-ex-note"></p><p class="pm-ex-msg" role="alert"></p></div>'));
    this.lead = q(this.body, '.pm-ex-lead');
    this.list = q(this.body, '.pm-ex-list');
    this.note = q(this.body, '.pm-ex-note');
    this.msg = q(this.body, '.pm-ex-msg');
    this.show = this.button('Show Objects', 'ghost', () => this.reveal());
    this.button('Close', 'primary', () => this.close());
    this.list.style.setProperty('--pm-ex-rows', String(ROWS));
  }

  explain(e: Explanation, message: string): void {
    this.items = e.constraints;
    setText(this.lead, e.kind === 'conflict' ? t('These constraints cannot all hold at once, so the new one was refused.') : t('The new constraint repeats what the others already fix, so it was refused.'));
    setText(this.note, `${message.includes('not changed') ? '' : t('The drawing was not changed.')}${e.minimal ? '' : ` ${t('The list may include extra constraints.')}`}`.trim());
    setText(this.msg, '');
    this.paint();
    setHidden(this.show, !e.constraints.some((c) => c.handles.length > 0));
    this.open(this.scrim.querySelector<HTMLElement>('.cv-btn-primary'));
  }

  private paint(): void {
    patchList(this.list, this.items, {
      key: (c) => String(c.id),
      create: (c) => {
        const n = el<HTMLElement>(`<div class="pm-ex-row" role="listitem"><span class="pm-ex-text"></span><span class="pm-ex-tag"></span><button class="cv-icon-btn pm-ex-del" type="button">${icon('delete', 14)}</button></div>`);
        q(n, '.pm-ex-del').addEventListener('click', () => { void this.drop(Number(n.dataset.key)); });
        this.fill(n, c);
        return n;
      },
      update: (n, c) => this.fill(n, c),
    });
  }

  private fill(n: HTMLElement, c: ExplainItem): void {
    setText(q(n, '.pm-ex-text'), c.text);
    setText(q(n, '.pm-ex-tag'), c.new ? t('new, not added') : '');
    setClass(n, 'is-new', !!c.new);
    const del = q<HTMLButtonElement>(n, '.pm-ex-del');
    del.hidden = !!c.new;
    del.title = t('Delete this constraint');
    del.setAttribute('aria-label', t('Delete this constraint'));
  }

  private reveal(): void {
    const handles = [...new Set(this.items.flatMap((c) => c.handles))];
    if (!handles.length) return;
    document.dispatchEvent(new CustomEvent('formcad:set-selection', { detail: { handles, mode: 'set' } }));
    zoomToHandles(handles);
  }

  private async drop(id: number): Promise<void> {
    const doc = docStore.activeId;
    if (!doc) return;
    try {
      await param.deleteConstraint(doc, id);
      this.items = this.items.filter((c) => c.id !== id);
      this.paint();
      setText(this.msg, t('Constraint removed. Try the new one again.'));
      toast(t('Constraint removed.'));
    } catch (e) {
      setText(this.msg, e instanceof Error ? e.message : 'The engine did not answer');
    }
  }
}

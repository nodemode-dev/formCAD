import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setHidden, setText } from '../dom';
import { t } from '../i18n';
import { failure, out } from './output-api';
import { PageForm } from './page-form';

export class PageSetupManager extends Dialog {
  private readonly form = new PageForm();
  private readonly list: HTMLElement;
  private readonly head: HTMLElement;
  private readonly size: HTMLElement;
  private readonly empty: HTMLElement;
  private readonly right: HTMLElement;
  private readonly note: HTMLElement;
  private names: string[] = [];
  private selected = '';
  private doc = '';
  private timer = 0;
  private seq = 0;

  constructor() {
    super('Page Setup Manager', 760);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="u2-sm op-psm"><div class="u2-sm-left"><div class="u2-sm-cur"></div><div class="cv-list u2-sm-list" role="listbox"></div></div>' +
      '<div class="u2-sm-right"><div class="u2-sm-ph"></div><div class="op-psm-form"></div><div class="cv-note op-psm-size"></div></div></div>'));
    this.body.appendChild(el('<p class="cv-note op-psm-empty" hidden></p>'));
    this.body.appendChild(el('<p class="u2-message op-note" hidden></p>'));
    this.list = q(this.body, '.u2-sm-list');
    this.head = q(this.body, '.u2-sm-ph');
    this.size = q(this.body, '.op-psm-size');
    this.empty = q(this.body, '.op-psm-empty');
    this.right = q(this.body, '.u2-sm-right');
    this.note = q(this.body, '.op-note');
    setText(q(this.body, '.u2-sm-cur'), t('Layouts'));
    q(this.body, '.op-psm-form').appendChild(this.form.el);
    this.form.onChange = () => this.queueSave();
    this.form.onPickWindow = () => undefined;
    this.button('Close', 'primary', () => this.close());
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.doc) this.close(); });
  }

  async show(layout?: string): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.doc = id;
    this.say('');
    try {
      const [devs, papers, styles, lays] = await Promise.all([out.devices(), out.papers(), out.styles(id), out.layouts(id)]);
      this.form.setLists(devs.devices, papers.papers, styles.tables);
      this.form.setDeviceOutputs(Object.fromEntries(devs.devices.map((d) => [d.name, d.output])));
      this.names = lays.layouts.map((l) => l.name);
      setText(this.empty, t('This drawing has no layouts.'));
      setHidden(this.empty, this.names.length > 0);
      setClass(this.right, 'is-off', this.names.length === 0);
      this.paint();
      const pick = layout && this.names.includes(layout) ? layout : this.names.includes(lays.current) ? lays.current : this.names[0] ?? '';
      if (pick) await this.choose(pick);
    } catch (e) {
      this.say(failure(e));
    }
    this.open();
  }

  private say(text: string): void {
    const n = this.note;
    setText(n, text);
    setHidden(n, !text);
  }

  private paint(): void {
    patchList<string>(this.list, this.names, {
      key: (n) => n,
      create: (n) => {
        const row = el<HTMLButtonElement>('<button class="cv-list-row u2-sm-row" type="button" role="option"><span></span><span class="cv-list-name"></span><span class="cv-list-meta"></span></button>');
        setText(q(row, '.cv-list-name'), n);
        row.addEventListener('click', () => void this.choose(n));
        return row;
      },
      update: (row, n) => {
        setClass(row, 'is-selected', n === this.selected);
        row.setAttribute('aria-selected', String(n === this.selected));
      },
    });
  }

  private async choose(name: string): Promise<void> {
    window.clearTimeout(this.timer);
    this.selected = name;
    this.paint();
    setText(this.head, `${t('Page setup of')} ${name}`);
    const mine = ++this.seq;
    try {
      const ps = await out.pageSetup(this.doc, name);
      if (mine !== this.seq) return;
      this.form.setMode({ model: false, scale: true });
      this.form.fillSetup(ps);
      setText(this.size, `${t('Sheet')} ${Number((ps.sheet?.[0] ?? ps.width).toFixed(2))} x ${Number((ps.sheet?.[1] ?? ps.height).toFixed(2))} mm`);
      this.say('');
    } catch (e) {
      this.say(failure(e));
    }
  }

  private queueSave(): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => void this.save(), 300);
  }

  private async save(): Promise<void> {
    const name = this.selected;
    if (!name) return;
    try {
      const ps = await out.setPageSetup(this.doc, name, this.form.toSetup());
      setText(this.size, `${t('Sheet')} ${Number(ps.width.toFixed(2))} x ${Number(ps.height.toFixed(2))} mm`);
      this.say('');
    } catch (e) {
      this.say(failure(e));
    }
  }
}

import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setChecked, setDisabled, setHidden, setText } from '../dom';
import { pickPlotPath } from '../file-dialogs';
import { t } from '../i18n';
import { toast } from '../toast';
import { followJob } from './job-feed';
import { failure, out, type LayoutList } from './output-api';

interface Sheet { name: string; meta: string }

export class PublishDialog extends Dialog {
  private readonly list: HTMLElement;
  private readonly count: HTMLElement;
  private readonly err: HTMLElement;
  private readonly go: HTMLButtonElement;
  private sheets: Sheet[] = [];
  private on = new Set<string>();
  private doc = '';
  private busy = false;

  constructor() {
    super('Batch Publish', 520);
    this.body.appendChild(el('<p class="cv-note op-pub-note"></p>'));
    this.body.appendChild(el('<div class="op-pub-tools"><button class="cv-btn" type="button" data-all></button><button class="cv-btn" type="button" data-none></button><span class="cv-note op-pub-count"></span></div>'));
    this.body.appendChild(el('<div class="cv-list op-pub-list" role="listbox"></div>'));
    this.body.appendChild(el('<p class="u2-message op-note" hidden></p>'));
    setText(q(this.body, '.op-pub-note'), t('Each checked sheet becomes one page of a single PDF file, in the order listed.'));
    this.list = q(this.body, '.op-pub-list');
    this.count = q(this.body, '.op-pub-count');
    this.err = q(this.body, '.op-note');
    setText(q(this.body, '[data-all]'), t('Select All'));
    setText(q(this.body, '[data-none]'), t('Select None'));
    q(this.body, '[data-all]').addEventListener('click', () => { this.on = new Set(this.sheets.map((s) => s.name)); this.paint(); });
    q(this.body, '[data-none]').addEventListener('click', () => { this.on.clear(); this.paint(); });
    this.button('Cancel', 'ghost', () => this.close());
    this.go = this.button('Publish to PDF...', 'primary', () => void this.publish());
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.doc) this.close(); });
  }

  async showFor(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.doc = id;
    this.say('');
    try {
      const lays: LayoutList = await out.layouts(id);
      this.sheets = [{ name: 'Model', meta: t('Model space') }, ...lays.layouts.map((l) => ({ name: l.name, meta: `${l.paper.replace(/ \(.*$/, '')}` }))];
      const keep = [...this.on].filter((n) => this.sheets.some((s) => s.name === n));
      this.on = new Set(keep.length ? keep : this.sheets.filter((s) => s.name !== 'Model').map((s) => s.name));
      this.paint();
    } catch (e) {
      this.say(failure(e));
    }
    this.open(this.go);
  }

  private say(text: string): void {
    setText(this.err, text);
    setHidden(this.err, !text);
  }

  private paint(): void {
    patchList<Sheet>(this.list, this.sheets, {
      key: (s) => s.name,
      create: (s) => {
        const row = el<HTMLElement>('<label class="cv-list-row op-pub-row"><input type="checkbox"><span class="cv-list-name"></span><span class="cv-list-meta"></span></label>');
        setText(q(row, '.cv-list-name'), s.name);
        setText(q(row, '.cv-list-meta'), s.meta);
        setChecked(q<HTMLInputElement>(row, 'input'), this.on.has(s.name));
        q<HTMLInputElement>(row, 'input').addEventListener('change', (e) => {
          if ((e.target as HTMLInputElement).checked) this.on.add(s.name); else this.on.delete(s.name);
          this.sync();
        });
        return row;
      },
      update: (row, s) => setChecked(q<HTMLInputElement>(row, 'input'), this.on.has(s.name)),
    });
    this.sync();
  }

  private sync(): void {
    setText(this.count, `${this.on.size} / ${this.sheets.length}`);
    setDisabled(this.go, this.on.size === 0 || this.busy);
  }

  private async publish(): Promise<void> {
    const names = this.sheets.map((s) => s.name).filter((n) => this.on.has(n));
    if (!names.length || this.busy) return;
    const doc = docStore.current();
    const path = await pickPlotPath(`${(doc?.name ?? 'Drawing').replace(/\.[^.]+$/, '')}.pdf`, 'pdf');
    if (!path) return;
    this.busy = true;
    this.sync();
    this.say('');
    try {
      const job = await out.plot(this.doc, { layouts: names, path }, 'pdf');
      const done = await followJob(job, `${t('Publish')} ${names.length}`);
      if (done.state === 'done') {
        toast(`${t('Published')} ${names.length} ${t('sheets to')} ${done.path || path}`);
        this.close();
      } else {
        this.say(done.message);
      }
    } catch (e) {
      this.say(failure(e));
    } finally {
      this.busy = false;
      this.sync();
    }
  }
}

import { Dialog } from '../dialogs';
import { selectField, textField, numField } from '../dialogs/fields';
import { el, patchList, q, setHidden, setText } from '../dom';
import { t } from '../i18n';
import { toast } from '../toast';
import { failure, out, type PlotDevice } from './output-api';

export class PlotterDialog extends Dialog {
  private readonly list: HTMLElement;
  private readonly err: HTMLElement;
  private readonly name = textField('Name');
  private readonly output = selectField('Output', [['pdf', 'PDF'], ['png', 'PNG'], ['svg', 'SVG']]);
  private readonly dpi = numField('Resolution (dpi)', { min: 50, max: 2400, int: true });
  private readonly add: HTMLButtonElement;
  private devices: PlotDevice[] = [];

  constructor() {
    super('Plotter Manager', 560);
    this.body.appendChild(el('<div class="cv-list op-dev-list" role="list"></div>'));
    this.body.appendChild(el('<fieldset class="u2-group op-dev-add"><legend></legend></fieldset>'));
    this.body.appendChild(el('<p class="u2-message op-note" hidden></p>'));
    this.list = q(this.body, '.op-dev-list');
    this.err = q(this.body, '.op-note');
    const box = q(this.body, '.op-dev-add');
    setText(q(box, 'legend'), t('Add a plotter'));
    this.dpi.set(300);
    this.add = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
    setText(this.add, t('Add Plotter'));
    this.add.addEventListener('click', () => void this.create());
    box.append(this.name.el, this.output.el, this.dpi.el, this.add);
    this.button('Close', 'primary', () => this.close());
  }

  async showFor(): Promise<void> {
    this.say('');
    await this.load();
    this.open(this.name.input);
  }

  private say(text: string): void {
    setText(this.err, text);
    setHidden(this.err, !text);
  }

  private async load(): Promise<void> {
    try {
      this.devices = (await out.devices()).devices;
      patchList<PlotDevice>(this.list, this.devices, {
        key: (d) => d.name,
        create: (d) => {
          const row = el('<div class="cv-list-row op-dev-row" role="listitem"><span></span><span class="cv-list-name"></span><span class="cv-list-meta"></span></div>');
          this.fill(row, d);
          return row;
        },
        update: (row, d) => this.fill(row, d),
      });
    } catch (e) {
      this.say(failure(e));
    }
  }

  private fill(row: HTMLElement, d: PlotDevice): void {
    setText(q(row, '.cv-list-name'), d.name);
    setText(q(row, '.cv-list-meta'), `${d.output.toUpperCase()} · ${d.resolution} dpi · ${d.papers} ${t('papers')}`);
    row.title = d.description;
  }

  private async create(): Promise<void> {
    const name = String(this.name.get()).trim();
    if (!name) { this.say(t('Give the plotter a name.')); return; }
    try {
      const base = this.devices[0];
      const full = await out.deviceDetail(base?.name ?? 'FormCAD PDF');
      await out.addDevice({ name, description: '', output: this.output.get(), resolution: this.dpi.get(), orientation: 'landscape', papers: full.paperList });
      this.name.set('');
      this.say('');
      toast(`${t('Added')} ${name}.`);
      await this.load();
    } catch (e) {
      this.say(failure(e));
    }
  }
}

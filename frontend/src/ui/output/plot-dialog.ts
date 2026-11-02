import { drawingCanvas } from '../../canvas/mount';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { selectField, setOptions } from '../dialogs/fields';
import { el, q, setDisabled, setHidden, setText } from '../dom';
import { pickPlotPath } from '../file-dialogs';
import { t } from '../i18n';
import { toast } from '../toast';
import { followJob } from './job-feed';
import { failure, out, type PlotDefaults, type PlotDevice } from './output-api';
import { PageForm } from './page-form';
import { PlotPreview, previews } from './plot-preview';
import { SheetSketch } from './sheet-sketch';

const MODEL = 'Model';
let shared: PlotPreview | null = null;
export const previewWindow = (): PlotPreview => (shared ??= new PlotPreview());

export class PlotDialog extends Dialog {
  private readonly layout = selectField('Layout', [[MODEL, MODEL]]);
  private readonly form = new PageForm();
  private readonly sketch = new SheetSketch();
  private readonly note: HTMLElement;
  private readonly apply: HTMLButtonElement;
  private readonly previewBtn: HTMLButtonElement;
  private readonly ok: HTMLButtonElement;
  private devices: PlotDevice[] = [];
  private doc = '';
  private defaults: PlotDefaults | null = null;
  private timer = 0;
  private busy = false;
  private pickOff: (() => void) | null = null;

  constructor() {
    super('Plot', 700);
    this.body.appendChild(this.layout.el);
    const cols = el('<div class="op-plot"></div>');
    const side = el('<div class="op-plot-side"></div>');
    side.appendChild(this.sketch.el);
    cols.append(this.form.el, side);
    this.body.appendChild(cols);
    this.body.appendChild(el('<p class="u2-message op-note" hidden></p>'));
    this.note = q(this.body, '.op-note');
    this.apply = this.button('Apply to Layout', 'ghost', () => void this.applyToLayout());
    this.apply.classList.add('cv-btn-apart');
    this.previewBtn = this.button('Preview', 'ghost', () => void this.preview());
    this.button('Cancel', 'ghost', () => this.close());
    this.ok = this.button('OK', 'primary', () => void this.plot());
    this.layout.change = () => void this.loadLayout(String(this.layout.get()));
    this.form.onChange = () => this.queueSketch();
    this.form.onPickWindow = () => this.pickWindow();
    this.onClose = () => { window.clearTimeout(this.timer); this.stopPick(); };
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.doc) this.close(); });
  }

  async show(layout?: string): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.doc = id;
    this.say('');
    try {
      const [devs, papers, styles, lays] = await Promise.all([out.devices(), out.papers(), out.styles(id), out.layouts(id)]);
      this.devices = devs.devices;
      this.form.setLists(devs.devices, papers.papers, styles.tables);
      this.form.setDeviceOutputs(Object.fromEntries(devs.devices.map((d) => [d.name, d.output])));
      setOptions(this.layout, [[MODEL, MODEL], ...lays.layouts.map((l) => [l.name, l.name] as const)]);
      await this.loadLayout(layout ?? lays.current ?? MODEL);
    } catch (e) {
      this.say(failure(e));
    }
    this.open(this.ok);
  }

  private say(text: string): void {
    setText(this.note, text);
    setHidden(this.note, !text);
  }

  private async loadLayout(name: string): Promise<void> {
    try {
      const d = await out.defaults(this.doc, name);
      this.defaults = d;
      this.layout.set(d.layout);
      this.form.setMode({ model: d.model, scale: false });
      this.form.fillDefaults(d);
      this.form.setDeviceOutputs(Object.fromEntries(this.devices.map((x) => [x.name, x.output])));
      setDisabled(this.apply, d.model);
      this.say('');
      this.queueSketch();
    } catch (e) {
      this.say(failure(e));
    }
  }

  private request(): Record<string, unknown> {
    const name = String(this.layout.get());
    return { layout: name, ...this.form.toRequest() };
  }

  private queueSketch(): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => void this.refreshSketch(), 350);
  }

  private async refreshSketch(): Promise<void> {
    if (!this.isOpen) return;
    try {
      const shot = await previews.get(this.doc, this.request());
      this.sketch.showing(shot);
      this.say('');
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      this.say(failure(e));
    }
  }

  private async preview(): Promise<void> {
    const request = this.request();
    const name = String(this.layout.get());
    const win = previewWindow();
    this.scrim.hidden = true;
    win.onClose = () => { this.scrim.hidden = false; };
    await win.show(this.doc, request, name, () => { void this.plot(); });
  }

  private async applyToLayout(): Promise<void> {
    const name = String(this.layout.get());
    if (this.defaults?.model) return;
    const s = this.form.toSetup();
    const keep: Record<string, unknown> = {};
    for (const k of ['device', 'paper', 'width', 'height', 'landscape', 'plot_lineweights', 'transparency', 'display_styles', 'style_table']) if (k in s) keep[k] = s[k];
    try {
      await out.setPageSetup(this.doc, name, keep);
      toast(`${t('Page setup saved to')} ${name}.`);
    } catch (e) {
      this.say(failure(e));
    }
  }

  private async plot(): Promise<void> {
    if (this.busy) return;
    const request = this.request();
    const name = String(this.layout.get());
    const doc = docStore.current();
    const output = this.outputOf();
    const base = (doc?.name ?? 'Drawing').replace(/\.[^.]+$/, '');
    const path = await pickPlotPath(`${base}${name === MODEL ? '' : `-${name}`}.${output}`, output);
    if (!path) { if (!this.isOpen) this.scrim.hidden = false; return; }
    if (!this.isOpen) this.scrim.hidden = false;
    this.busy = true;
    setDisabled(this.ok, true);
    this.say('');
    try {
      const job = await out.plot(this.doc, { ...request, path }, 'plot');
      const done = await followJob(job, `${t('Plot')} ${name}`);
      if (done.state === 'done') {
        toast(`${t('Plotted')} ${name} ${t('to')} ${done.path || path}`);
        this.close();
      } else {
        this.say(done.message);
      }
    } catch (e) {
      this.say(failure(e));
    } finally {
      this.busy = false;
      setDisabled(this.ok, false);
    }
  }

  private outputOf(): string {
    const dev = this.devices.find((d) => d.name === this.form.selectedDevice());
    return dev?.output ?? this.defaults?.output ?? 'pdf';
  }

  private pickWindow(): void {
    const canvas = drawingCanvas();
    if (!canvas) return;
    const pts: number[] = [];
    this.scrim.hidden = true;
    toast(t('Click the first corner of the plot window.'));
    const off = canvas.on('click', (p) => {
      pts.push(p.x, p.y);
      if (pts.length === 2) { toast(t('Click the opposite corner.')); return; }
      this.stopPick();
      this.scrim.hidden = false;
      this.form.setArea('window');
      this.form.setWindow(pts);
    });
    const esc = (e: KeyboardEvent): void => { if (e.key === 'Escape') { this.stopPick(); this.scrim.hidden = false; } };
    document.addEventListener('keydown', esc, true);
    this.pickOff = () => { off(); document.removeEventListener('keydown', esc, true); };
  }

  private stopPick(): void {
    this.pickOff?.();
    this.pickOff = null;
  }
}

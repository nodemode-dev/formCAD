import { el, q, setClass, setHidden, setText } from '../dom';
import { checkField, numField, selectField, setOptions, textField, type Field } from '../dialogs/fields';
import { t } from '../i18n';
import { segRow } from '../panels/pref-rows';
import type { PageSetupRecord, PaperSize, PlotDefaults, PlotDevice, StyleTableInfo } from './output-api';

export interface FormState {
  device: string; paper: string; custom: boolean; width: number; height: number; landscape: boolean;
  area: string; window: number[]; fit: boolean; scale: string; center: boolean; offset: number[];
  lineweights: boolean; transparency: boolean; displayStyles: boolean; styleTable: string;
}

export interface FormMode { model: boolean; scale: boolean }

const AREAS: ReadonlyArray<readonly [string, string]> = [['extents', 'Extents'], ['display', 'Display'], ['limits', 'Limits'], ['window', 'Window']];
const CUSTOM = '::custom';
const NONE = '';

export class PageForm {
  readonly el: HTMLElement;
  onChange: (() => void) | null = null;
  onPickWindow: (() => void) | null = null;
  private readonly device = selectField('Printer/plotter', [[NONE, 'None (PDF)']]);
  private readonly paper = selectField('Paper size', []);
  private readonly cw = numField('Width (mm)', { min: 1, max: 5080 });
  private readonly ch = numField('Height (mm)', { min: 1, max: 5080 });
  private readonly orient = segRow('Orientation', [['portrait', t('Portrait')], ['landscape', t('Landscape')]], (v) => { this.landscape = v === 'landscape'; this.changed(); });
  private readonly area = selectField('Plot area', AREAS);
  private readonly wx0 = numField('First corner X');
  private readonly wy0 = numField('First corner Y');
  private readonly wx1 = numField('Opposite corner X');
  private readonly wy1 = numField('Opposite corner Y');
  private readonly fit = checkField('Fit to paper');
  private readonly scale = textField('Scale', '1:50');
  private readonly center = checkField('Center the plot');
  private readonly ox = numField('Offset X (mm)', { min: -100000, max: 100000 });
  private readonly oy = numField('Offset Y (mm)', { min: -100000, max: 100000 });
  private readonly lw = checkField('Plot object lineweights');
  private readonly tr = checkField('Plot transparency');
  private readonly ds = checkField('Plot with plot styles');
  private readonly style = selectField('Plot style table', [[NONE, 'None']]);
  private readonly pick: HTMLElement;
  private readonly cust: HTMLElement;
  private readonly win: HTMLElement;
  private readonly off: HTMLElement;
  private landscape = true;
  private papers: PaperSize[] = [];
  private mode: FormMode = { model: true, scale: true };

  constructor() {
    this.el = el('<div class="op-form"></div>');
    this.cust = el('<div class="u2-pair"></div>');
    this.cust.append(this.cw.el, this.ch.el);
    this.win = el('<div class="op-win"></div>');
    const a = el('<div class="u2-pair"></div>');
    a.append(this.wx0.el, this.wy0.el);
    const b = el('<div class="u2-pair"></div>');
    b.append(this.wx1.el, this.wy1.el);
    this.pick = el('<button class="cv-btn" type="button"></button>');
    setText(this.pick, t('Window <'));
    this.pick.addEventListener('click', () => this.onPickWindow?.());
    this.win.append(a, b, this.pick);
    this.off = el('<div class="u2-pair"></div>');
    this.off.append(this.ox.el, this.oy.el);
    this.el.append(this.device.el, this.paper.el, this.cust, this.orient.el, this.area.el, this.win, this.fit.el, this.scale.el, this.center.el, this.off, this.lw.el, this.tr.el, this.ds.el, this.style.el);
    for (const f of [this.device, this.paper, this.cw, this.ch, this.area, this.wx0, this.wy0, this.wx1, this.wy1, this.fit, this.scale, this.center, this.ox, this.oy, this.lw, this.tr, this.ds, this.style]) {
      f.change = () => this.changed();
    }
    this.applyMode();
  }

  private changed(): void {
    this.applyMode();
    this.onChange?.();
  }

  setLists(devices: PlotDevice[], papers: PaperSize[], styles: StyleTableInfo[]): void {
    this.papers = papers;
    setOptions(this.device, [[NONE, t('None (PDF)')], ...devices.map((d) => [d.name, d.name] as const)]);
    setOptions(this.paper, [...papers.map((p) => [p.name, p.short] as const), [CUSTOM, t('Custom size')]]);
    setOptions(this.style, [[NONE, t('None')], ...styles.map((s) => [s.name, s.name] as const)]);
  }

  setMode(mode: FormMode): void {
    this.mode = mode;
    this.applyMode();
  }

  private applyMode(): void {
    const model = this.mode.model;
    setOptions(this.area, model ? AREAS : [['layout', t('Layout')]]);
    this.area.enable(model);
    setHidden(this.cust, this.paper.get() !== CUSTOM);
    setHidden(this.win, !(model && this.area.get() === 'window'));
    setClass(this.fit.el, 'op-hold', !model && !this.mode.scale);
    setClass(this.scale.el, 'op-hold', !model && !this.mode.scale);
    this.scale.enable(!this.fit.get());
    setClass(this.center.el, 'op-hold', !model && !this.mode.scale);
    setClass(this.off, 'op-hold', !model);
    const svgOut = this.deviceOutput === 'svg';
    this.ox.enable(!this.center.get() && !svgOut);
    this.oy.enable(!this.center.get() && !svgOut);
  }

  deviceOutput = 'pdf';

  setDeviceOutputs(outputs: Record<string, string>): void {
    this.deviceOutput = outputs[this.device.get() as string] ?? 'pdf';
    this.applyMode();
  }

  selectedDevice(): string { return this.device.get() as string; }

  fillDefaults(d: PlotDefaults): void {
    const ps = d.pageSetup;
    const dev = ps ? (ps.device === 'None' ? NONE : ps.device) : d.device;
    this.fill({
      device: dev, paper: d.paper, custom: false, width: d.width, height: d.height, landscape: d.landscape,
      area: d.area, window: d.window ?? [0, 0, 0, 0], fit: d.fit, scale: d.scaleText, center: d.center, offset: d.offset,
      lineweights: d.lineweights, transparency: d.transparency, displayStyles: d.displayStyles, styleTable: d.styleTable,
    });
  }

  fillSetup(ps: PageSetupRecord): void {
    this.fill({
      device: ps.device === 'None' ? NONE : ps.device, paper: ps.paper, custom: false, width: ps.width, height: ps.height, landscape: ps.landscape,
      area: ps.plot_area, window: ps.window, fit: ps.fit, scale: ps.scale_text, center: ps.center, offset: ps.offset,
      lineweights: ps.plot_lineweights, transparency: ps.transparency, displayStyles: ps.display_styles, styleTable: ps.style_table,
    });
  }

  fill(s: FormState): void {
    this.landscape = s.landscape;
    this.device.set(s.device);
    const known = this.papers.some((p) => p.name === s.paper);
    this.paper.set(known ? s.paper : CUSTOM);
    this.cw.set(Math.min(s.width, s.height));
    this.ch.set(Math.max(s.width, s.height));
    this.orient.set(s.landscape ? 'landscape' : 'portrait');
    this.area.set(s.area);
    const w = s.window.length === 4 ? s.window : [0, 0, 0, 0];
    this.wx0.set(w[0]); this.wy0.set(w[1]); this.wx1.set(w[2]); this.wy1.set(w[3]);
    this.fit.set(s.fit);
    this.scale.set(s.scale);
    this.center.set(s.center);
    this.ox.set(s.offset[0] ?? 0); this.oy.set(s.offset[1] ?? 0);
    this.lw.set(s.lineweights);
    this.tr.set(s.transparency);
    this.ds.set(s.displayStyles);
    this.style.set(s.styleTable);
    this.applyMode();
  }

  setWindow(w: number[]): void {
    this.wx0.set(w[0]); this.wy0.set(w[1]); this.wx1.set(w[2]); this.wy1.set(w[3]);
    this.changed();
  }

  setArea(a: string): void { this.area.set(a); this.applyMode(); }

  windowValues(): number[] { return [this.wx0.get(), this.wy0.get(), this.wx1.get(), this.wy1.get()].map(Number); }

  private paperPart(): Record<string, unknown> {
    if (this.paper.get() === CUSTOM) return { width: this.cw.get(), height: this.ch.get() };
    return { paper: this.paper.get() };
  }

  toRequest(): Record<string, unknown> {
    const r: Record<string, unknown> = {
      ...this.paperPart(), landscape: this.landscape, lineweights: this.lw.get(), transparency: this.tr.get(),
      display_styles: this.ds.get(), style_table: this.style.get(),
    };
    if (this.device.get()) r.device = this.device.get();
    if (this.mode.model) {
      r.area = this.area.get();
      if (r.area === 'window') r.window = this.windowValues();
      r.fit = this.fit.get();
      if (!r.fit) r.scale = this.scale.get();
      r.center = this.center.get();
      if (!r.center && this.deviceOutput !== 'svg') r.offset = [this.ox.get(), this.oy.get()];
    }
    return r;
  }

  toSetup(): Record<string, unknown> {
    const s: Record<string, unknown> = {
      device: this.device.get() || 'None', ...this.paperPart(), landscape: this.landscape, plot_lineweights: this.lw.get(),
      transparency: this.tr.get(), display_styles: this.ds.get(), style_table: this.style.get(), center: this.center.get(),
      fit: this.fit.get(), offset: [this.ox.get(), this.oy.get()], plot_area: this.area.get(),
    };
    if (!this.fit.get()) s.scale = this.scale.get();
    if (this.area.get() === 'window') s.window = this.windowValues();
    return s;
  }

  first(): HTMLElement { return q(this.el, 'select'); }
}

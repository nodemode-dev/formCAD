import { api } from '../../io/api';
import type { HatchFields, PatternSwatch } from '../../io/api';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setChecked, setClass, setDisabled, setHidden, setText } from '../dom';
import { t } from '../i18n';
import { sysvars } from '../sysvar-store';
import { toast } from '../toast';
import { exec, execError, failure, waitCommandEnd } from './engine';
import { checkField, numField, selectField } from './fields';

type Mode = 'hatch' | 'gradient' | 'edit';
type Pick = 'P' | 'O' | 'R' | 'H';

const ACI_HEX: Record<number, string> = { 1: '#ff0000', 2: '#ffff00', 3: '#00ff00', 4: '#00ffff', 5: '#0000ff', 6: '#ff00ff', 7: '#ffffff', 8: '#808080', 9: '#c0c0c0' };
const SHAPES: ReadonlyArray<readonly [string, string]> = [['LINEAR', 'Linear'], ['CYLINDER', 'Cylinder'], ['CURVED', 'Curved'], ['SPHERICAL', 'Spherical'], ['HEMISPHERICAL', 'Hemispherical']];
const ORIGINS: ReadonlyArray<readonly [string, string]> = [['bottom left', 'Bottom left'], ['bottom right', 'Bottom right'], ['top right', 'Top right'], ['top left', 'Top left'], ['center', 'Center']];
const ISLANDS = ['normal', 'outer', 'ignore'] as const;
const SVG = 'http://www.w3.org/2000/svg';

function hexOf(v: unknown, fallback: string): string {
  if (typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v)) return v.toLowerCase();
  const n = Number(v);
  return Number.isFinite(n) && ACI_HEX[n] ? ACI_HEX[n] : fallback;
}

function swatchSvg(p: PatternSwatch): SVGSVGElement {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 1 1');
  svg.setAttribute('preserveAspectRatio', 'none');
  if (p.solid) {
    const r = document.createElementNS(SVG, 'rect');
    r.setAttribute('width', '1');
    r.setAttribute('height', '1');
    r.setAttribute('fill', 'currentColor');
    svg.appendChild(r);
    return svg;
  }
  const path = document.createElementNS(SVG, 'path');
  let d = '';
  for (const s of p.segs) d += `M${s[0]} ${Math.round((1 - s[1]) * 10000) / 10000}L${s[2]} ${Math.round((1 - s[3]) * 10000) / 10000}`;
  path.setAttribute('d', d);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', 'currentColor');
  path.setAttribute('stroke-width', '1');
  path.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.appendChild(path);
  return svg;
}

export class HatchDialog extends Dialog {
  private mode: Mode = 'hatch';
  private tab: 'pattern' | 'gradient' = 'pattern';
  private pattern = 'ANSI31';
  private patterns: PatternSwatch[] = [];
  private patternsLoaded = false;
  private openedFor = '';
  private picking = false;
  private busy = false;
  private editHandles: number[] = [];
  private loaded: HatchFields | null = null;
  private picks = { points: 0, objects: 0, boundaries: 0 };
  private origin: [number, number] | null = null;
  private previewing = false;
  private readonly angle = numField('Angle', { min: -360, max: 360 });
  private readonly scale = numField('Scale', { min: 0.0001, max: 1000000 });
  private readonly gap = numField('Gap tolerance', { min: 0, max: 5000 });
  private readonly shape = selectField('Shape', SHAPES);
  private readonly inverted = checkField('Inverted');
  private readonly centered = checkField('Centered');
  private readonly gradAngle = numField('Gradient angle', { min: -360, max: 360 });
  private readonly one = checkField('One color');
  private readonly tint = numField('Shade and tint', { min: -1, max: 1, step: 0.05 });
  private readonly retain = selectField('Retain boundaries', [['none', 'No'], ['polyline', 'Polylines'], ['region', 'Regions']]);
  private readonly assoc = checkField('Associative');
  private readonly separate = checkField('Create separate hatches');
  private readonly defaultExtents = checkField('Default to boundary extents');
  private readonly originMode = selectField('Origin', ORIGINS);
  private readonly tabs: Record<'pattern' | 'gradient', HTMLButtonElement>;
  private readonly panes: Record<'pattern' | 'gradient', HTMLElement>;
  private readonly grid: HTMLElement;
  private readonly color1: HTMLInputElement;
  private readonly color2: HTMLInputElement;
  private readonly originRadios: HTMLInputElement[] = [];
  private readonly islandRadios: HTMLInputElement[] = [];
  private readonly originRead: HTMLElement;
  private readonly picked: HTMLElement;
  private readonly message: HTMLElement;
  private readonly loopBox: HTMLElement;
  private readonly loopList: HTMLElement;
  private readonly boundaryGroup: HTMLElement;
  private readonly ok: HTMLButtonElement;
  private readonly previewBtn: HTMLButtonElement;
  private readonly pill: HTMLElement;
  private removed = new Set<number>();

  constructor() {
    super('Hatch and Gradient', 640);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="u2-hatch">' +
      '<div class="u2-hatch-left">' +
      '<div class="u2-seg" role="tablist"><button class="u2-tab" type="button" data-tab="pattern"></button><button class="u2-tab" type="button" data-tab="gradient"></button></div>' +
      '<div class="u2-pane" data-pane="pattern"><div class="u2-swatches" role="listbox"></div><div class="u2-pair" data-slot="pa"></div></div>' +
      '<div class="u2-pane" data-pane="gradient" hidden>' +
      '<div class="u2-colors"><label class="cv-field"><span></span><input class="cv-input cv-color" type="color" data-c="1"></label><label class="cv-field"><span></span><input class="cv-input cv-color" type="color" data-c="2"></label></div>' +
      '<div data-slot="gr"></div></div>' +
      '<fieldset class="u2-group"><legend></legend><div class="u2-origin"></div></fieldset>' +
      '</div>' +
      '<div class="u2-hatch-right">' +
      '<fieldset class="u2-group" data-group="boundaries"><legend></legend>' +
      '<div class="u2-boundary-btns"><button class="cv-btn" type="button" data-add="P"></button><button class="cv-btn" type="button" data-add="O"></button></div>' +
      '<div class="u2-picked-row"><span class="u2-picked"></span><button class="cv-btn" type="button" data-clear></button></div>' +
      '<div class="u2-loops" hidden><p class="cv-note"></p><div class="cv-list u2-loop-list"></div></div></fieldset>' +
      '<fieldset class="u2-group" data-group="options"><legend></legend><div data-slot="opts"></div>' +
      '<div class="u2-radios" data-radios="island"></div><button class="cv-btn" type="button" data-inherit></button></fieldset>' +
      '</div></div>'));
    this.body.appendChild(el('<p class="u2-message" role="alert" hidden></p>'));
    const lab = (sel: string, text: string): void => setText(q(this.body, sel), t(text));
    lab('[data-tab="pattern"]', 'Pattern');
    lab('[data-tab="gradient"]', 'Gradient');
    lab('[data-add="P"]', 'Add: Pick points');
    lab('[data-add="O"]', 'Add: Select objects');
    lab('[data-clear]', 'Clear');
    lab('[data-inherit]', 'Inherit properties');
    lab('[data-group="boundaries"] legend', 'Boundaries');
    lab('[data-group="options"] legend', 'Options');
    this.tabs = { pattern: q(this.body, '[data-tab="pattern"]'), gradient: q(this.body, '[data-tab="gradient"]') };
    this.panes = { pattern: q(this.body, '[data-pane="pattern"]'), gradient: q(this.body, '[data-pane="gradient"]') };
    this.tabs.pattern.addEventListener('click', () => this.setTab('pattern'));
    this.tabs.gradient.addEventListener('click', () => this.setTab('gradient'));
    this.grid = q(this.body, '.u2-swatches');
    this.picked = q(this.body, '.u2-picked');
    this.message = q(this.body, '.u2-message');
    this.loopBox = q(this.body, '.u2-loops');
    this.loopList = q(this.body, '.u2-loop-list');
    this.boundaryGroup = q(this.body, '[data-group="boundaries"]');
    q(this.body, '[data-add="P"]').addEventListener('click', () => void this.pick('P'));
    q(this.body, '[data-add="O"]').addEventListener('click', () => void this.pick('O'));
    q(this.body, '[data-clear]').addEventListener('click', () => void this.clearPicks());
    q(this.body, '[data-inherit]').addEventListener('click', () => void this.inherit());
    const slot = (name: string): HTMLElement => q(this.body, `[data-slot="${name}"]`);
    slot('pa').append(this.angle.el, this.scale.el);
    const colors = this.body.querySelectorAll<HTMLElement>('.u2-colors .cv-field > span');
    setText(colors[0], t('Color 1'));
    setText(colors[1], t('Color 2'));
    this.color1 = q<HTMLInputElement>(this.body, '[data-c="1"]');
    this.color2 = q<HTMLInputElement>(this.body, '[data-c="2"]');
    this.color1.value = '#0000ff';
    this.color2.value = '#ffffff';
    slot('gr').append(this.one.el, this.tint.el, this.shape.el, this.inverted.el, this.centered.el, this.gradAngle.el);
    this.one.change = () => this.syncEnabled();
    const og = q(this.body, '.u2-origin');
    q(this.body, '.u2-hatch-left > .u2-group legend').textContent = t('Hatch origin');
    this.originRead = el('<span class="u2-origin-read"></span>');
    og.append(this.radio('origin', 'Use current origin', 'current', true), this.radio('origin', 'Specified origin', 'specified', false));
    const setBtn = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
    setText(setBtn, t('Click to set new origin'));
    setBtn.addEventListener('click', () => void this.pick('R'));
    og.append(setBtn, this.originRead, this.defaultExtents.el, this.originMode.el);
    this.defaultExtents.change = () => { if (this.defaultExtents.get()) this.origin = null; this.syncEnabled(); this.syncOrigin(); };
    this.originRadios.forEach((r) => r.addEventListener('change', () => this.syncEnabled()));
    const slotO = slot('opts');
    slotO.append(this.assoc.el, this.separate.el, this.gap.el, this.retain.el);
    const rad = q(this.body, '[data-radios="island"]');
    for (const [i, label] of [['normal', 'Normal'], ['outer', 'Outer'], ['ignore', 'Ignore']] as const) rad.appendChild(this.radio('island', label, i, i === 'normal'));
    this.pill = el(`<div class="u2-pill" hidden><span></span><button class="cv-btn cv-btn-primary" type="button" data-accept></button><button class="cv-btn" type="button" data-back></button></div>`);
    setText(q(this.pill, 'span'), t('Hatch preview'));
    setText(q(this.pill, '[data-accept]'), t('Accept'));
    setText(q(this.pill, '[data-back]'), t('Back'));
    q(this.pill, '[data-accept]').addEventListener('click', () => void this.acceptPreview());
    q(this.pill, '[data-back]').addEventListener('click', () => void this.backFromPreview());
    document.getElementById('overlay-root')?.appendChild(this.pill);
    this.button('Cancel', 'ghost', () => this.close());
    this.previewBtn = this.button('Preview', 'ghost', () => void this.run(true));
    this.ok = this.button('OK', 'primary', () => void this.run(false));
    this.onClose = () => { if (!this.picking && !this.previewing) void this.discard(); };
    docStore.onChange(() => { if ((this.isOpen || this.previewing) && docStore.activeId !== this.openedFor) this.abandon(); });
  }

  private radio(group: string, label: string, value: string, on: boolean): HTMLElement {
    const row = el(`<label class="u2-radio"><input type="radio" name="u2-${group}" value="${value}"><span></span></label>`);
    setText(q(row, 'span'), t(label));
    const input = q<HTMLInputElement>(row, 'input');
    input.checked = on;
    (group === 'origin' ? this.originRadios : this.islandRadios).push(input);
    return row;
  }

  private radioValue(list: HTMLInputElement[]): string {
    return list.find((r) => r.checked)?.value ?? '';
  }

  private setRadio(list: HTMLInputElement[], value: string): void {
    for (const r of list) setChecked(r, r.value === value);
  }

  private setTab(tab: 'pattern' | 'gradient'): void {
    this.tab = tab;
    for (const k of ['pattern', 'gradient'] as const) {
      setClass(this.tabs[k], 'is-on', k === tab);
      setHidden(this.panes[k], k !== tab);
    }
    this.syncEnabled();
  }

  private syncEnabled(): void {
    const specified = this.radioValue(this.originRadios) === 'specified';
    const extents = this.defaultExtents.get() === true || this.origin === null;
    this.defaultExtents.enable(specified && this.origin !== null);
    this.originMode.enable(specified && extents);
    const oneColor = this.one.get() === true;
    this.color2.disabled = oneColor;
    this.tint.enable(oneColor);
    setClass(this.color2.parentElement, 'is-off', oneColor);
    setHidden(this.separate.el, this.mode === 'edit');
    setHidden(this.retain.el, this.mode === 'edit');
    setHidden(this.boundaryGroup, this.mode === 'edit' && this.editHandles.length !== 1);
    setDisabled(this.ok, this.mode !== 'edit' && this.picks.points + this.picks.objects === 0);
  }

  private syncOrigin(): void {
    setText(this.originRead, this.origin ? `${t('Origin')}: ${Number(this.origin[0].toFixed(4))}, ${Number(this.origin[1].toFixed(4))}` : '');
  }

  private syncPicked(): void {
    setText(this.picked, `${t('Boundaries picked')}: ${this.picks.points + this.picks.objects}`);
    this.syncEnabled();
  }

  private say(text: string): void {
    setText(this.message, text);
    setHidden(this.message, !text);
  }

  private async ensurePatterns(): Promise<void> {
    if (this.patternsLoaded) return;
    try {
      this.patterns = (await api.patternSwatches()).patterns;
      this.patternsLoaded = true;
    } catch (e) {
      this.say(failure(e));
      return;
    }
    patchList(this.grid, this.patterns, {
      key: (p) => p.name,
      create: (p) => {
        const b = el<HTMLButtonElement>('<button class="u2-swatch" type="button" role="option"><span class="u2-swatch-art"></span><span class="u2-swatch-name"></span></button>');
        q(b, '.u2-swatch-art').appendChild(swatchSvg(p));
        setText(q(b, '.u2-swatch-name'), p.name);
        b.title = p.description ? `${p.name}: ${p.description}` : p.name;
        b.addEventListener('click', () => { this.pattern = p.name; this.markPattern(); });
        return b;
      },
      update: () => undefined,
    });
    this.markPattern();
  }

  private markPattern(): void {
    for (const b of Array.from(this.grid.children) as HTMLElement[]) {
      const on = b.dataset.key === this.pattern;
      setClass(b, 'is-on', on);
      b.setAttribute('aria-selected', String(on));
    }
  }

  private defaults(): void {
    this.pattern = sysvars.text('HPNAME', 'ANSI31').toUpperCase();
    this.angle.set(sysvars.num('HPANG', 0));
    this.scale.set(sysvars.num('HPSCALE', 1));
    this.gap.set(sysvars.num('HPGAPTOL', 0));
    this.assoc.set(sysvars.num('HPASSOC', 1) !== 0);
    this.separate.set(sysvars.num('HPSEPARATE', 0) !== 0);
    this.setRadio(this.islandRadios, ISLANDS[Math.min(2, Math.max(0, sysvars.num('HPISLAND', 0)))]);
    this.retain.set(['none', 'polyline', 'region'][Math.min(2, Math.max(0, sysvars.num('HPBOUND', 0)))]);
    const name = sysvars.text('GRADNAME', 'LINEAR').toUpperCase();
    const inv = name.startsWith('INV');
    this.shape.set(inv ? name.slice(3) : name);
    this.inverted.set(inv);
    this.centered.set(sysvars.num('GRADCENTERED', 1) !== 0);
    this.gradAngle.set(sysvars.num('GRADANGLE', 0));
    const tint = sysvars.num('GRADTINT', 0);
    this.one.set(tint !== 0);
    this.tint.set(tint !== 0 ? tint : 1);
    this.color1.value = hexOf(sysvars.get('GRADCOLOR1'), '#0000ff');
    this.color2.value = hexOf(sysvars.get('GRADCOLOR2'), '#ffffff');
    this.setRadio(this.originRadios, 'current');
    this.defaultExtents.set(true);
    this.originMode.set('bottom left');
    this.origin = null;
    this.removed.clear();
    this.picks = { points: 0, objects: 0, boundaries: 0 };
    this.loaded = null;
    this.say('');
  }

  async openCreate(gradient: boolean): Promise<void> {
    if (!docStore.activeId) return;
    this.openedFor = docStore.activeId;
    this.mode = gradient ? 'gradient' : 'hatch';
    this.editHandles = [];
    await this.exec0();
    this.defaults();
    await this.ensurePatterns();
    this.setTitle('Hatch and Gradient');
    setHidden(this.loopBox, true);
    setText(q(this.body, '[data-group="boundaries"] legend'), t('Boundaries'));
    this.setTab(gradient ? 'gradient' : 'pattern');
    this.syncOrigin();
    this.syncPicked();
    this.markPattern();
    this.open();
  }

  async openEdit(handles: number[]): Promise<void> {
    if (!docStore.activeId || !handles.length) return;
    this.openedFor = docStore.activeId;
    this.mode = 'edit';
    this.editHandles = handles;
    await this.exec0();
    this.defaults();
    await this.ensurePatterns();
    let f: HatchFields;
    try {
      f = await api.hatchFields(docStore.activeId, handles[0]);
    } catch (e) {
      toast(failure(e), 'error');
      return;
    }
    this.loaded = f;
    this.pattern = f.pattern.toUpperCase();
    this.angle.set(f.angle);
    this.scale.set(f.scale);
    this.gap.set(f.gap);
    this.assoc.set(f.associative);
    this.setRadio(this.islandRadios, ISLANDS[Math.min(2, Math.max(0, f.island))]);
    if (f.gradient) {
      const g = f.gradient;
      const inv = g.name.toUpperCase().startsWith('INV');
      this.shape.set(inv ? g.name.slice(3).toUpperCase() : g.name.toUpperCase());
      this.inverted.set(inv);
      this.centered.set(g.centered);
      this.gradAngle.set((g.angle * 180) / Math.PI);
      this.one.set(g.one);
      this.tint.set(g.tint);
      this.color1.value = hexOf(g.color1, '#0000ff');
      this.color2.value = hexOf(g.color2, '#ffffff');
    }
    this.setTitle('Hatch Edit');
    this.paintLoops(f.loops.length);
    this.setTab(f.gradient ? 'gradient' : 'pattern');
    this.syncOrigin();
    this.syncPicked();
    this.markPattern();
    this.open();
  }

  private async exec0(): Promise<void> {
    await exec('hatchpick', { clear: true }, true);
  }

  private paintLoops(count: number): void {
    setHidden(this.loopBox, this.editHandles.length !== 1);
    setText(q(this.loopBox, 'p'), t('Select boundaries to remove'));
    const rows = Array.from({ length: count }, (_v, i) => i);
    const paint = (node: HTMLElement, i: number): void => {
      const outer = this.loaded?.loops[i]?.outer !== false;
      setText(q(node, 'span'), `${t('Boundary')} ${i + 1} (${outer ? t('Outer') : t('Island')})`);
      setChecked(q<HTMLInputElement>(node, 'input'), this.removed.has(i));
    };
    patchList(this.loopList, rows, {
      key: (i) => String(i),
      create: (i) => {
        const row = el<HTMLLabelElement>('<label class="u2-loop"><input type="checkbox"><span></span></label>');
        q<HTMLInputElement>(row, 'input').addEventListener('change', (e) => {
          if ((e.target as HTMLInputElement).checked) this.removed.add(i); else this.removed.delete(i);
        });
        paint(row, i);
        return row;
      },
      update: paint,
    });
  }

  private async readPicks(): Promise<void> {
    const out = await exec('hatchpick', {}, true);
    const r = out?.result as { points?: unknown[]; handles?: unknown[]; origin?: [number, number] | null; hatch?: number | null; boundaries?: number } | undefined;
    if (!r) return;
    this.picks = { points: r.points?.length ?? 0, objects: r.handles?.length ?? 0, boundaries: r.boundaries ?? 0 };
    if (r.origin) {
      this.origin = [r.origin[0], r.origin[1]];
      this.setRadio(this.originRadios, 'specified');
      this.defaultExtents.set(false);
    }
    this.syncOrigin();
    this.syncPicked();
  }

  private async pick(kind: Pick): Promise<void> {
    const id = docStore.activeId;
    if (!id || this.picking) return;
    this.picking = true;
    this.close();
    const done = waitCommandEnd();
    try {
      await api.sendInput(id, 'hatchpick').then((s) => document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: s } })));
      const s = await api.sendInput(id, kind);
      document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: s } }));
      await done;
    } catch (e) {
      toast(failure(e), 'error');
    }
    this.picking = false;
    if (docStore.activeId !== this.openedFor) return;
    await this.readPicks();
    this.open();
  }

  private async clearPicks(): Promise<void> {
    await exec('hatchpick', { clear: true }, true);
    this.picks = { points: 0, objects: 0, boundaries: 0 };
    this.origin = null;
    this.syncOrigin();
    this.syncPicked();
  }

  private async inherit(): Promise<void> {
    const id = docStore.activeId;
    if (!id || this.picking) return;
    this.picking = true;
    this.close();
    const done = waitCommandEnd();
    try {
      for (const word of ['hatchpick', 'H']) {
        const s = await api.sendInput(id, word);
        document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: s } }));
      }
      await done;
      const out = await exec('hatchpick', {}, true);
      const handle = (out?.result as { hatch?: number | null } | undefined)?.hatch;
      if (handle) {
        const f = await api.hatchFields(id, handle);
        this.pattern = f.pattern.toUpperCase();
        this.angle.set(f.angle);
        this.scale.set(f.scale);
        this.assoc.set(f.associative);
        this.setRadio(this.islandRadios, ISLANDS[Math.min(2, Math.max(0, f.island))]);
        if (f.gradient) {
          const g = f.gradient;
          this.shape.set(g.name.toUpperCase().replace(/^INV/, ''));
          this.inverted.set(g.name.toUpperCase().startsWith('INV'));
          this.color1.value = hexOf(g.color1, '#0000ff');
          this.color2.value = hexOf(g.color2, '#ffffff');
          this.centered.set(g.centered);
          this.gradAngle.set((g.angle * 180) / Math.PI);
          this.one.set(g.one);
          this.tint.set(g.tint);
          this.setTab('gradient');
        } else {
          this.setTab('pattern');
        }
        this.markPattern();
      }
    } catch (e) {
      toast(failure(e), 'error');
    }
    this.picking = false;
    if (docStore.activeId === this.openedFor) { await this.readPicks(); this.open(); }
  }

  private gradientArgs(): Record<string, unknown> {
    const name = `${this.inverted.get() ? 'INV' : ''}${String(this.shape.get())}`;
    const g: Record<string, unknown> = { name, color1: this.color1.value, angle: Number(this.gradAngle.get()), centered: !!this.centered.get() };
    if (this.one.get()) g.tint = Number(this.tint.get()); else g.color2 = this.color2.value;
    return g;
  }

  private originArgs(): Record<string, unknown> {
    if (this.radioValue(this.originRadios) !== 'specified') return {};
    if (this.origin && !this.defaultExtents.get()) return { origin: this.origin };
    return { origin_mode: String(this.originMode.get()) };
  }

  private settingsArgs(): Record<string, unknown> {
    return {
      scale: Number(this.scale.get()),
      angle: Number(this.angle.get()),
      associative: !!this.assoc.get(),
      style: this.radioValue(this.islandRadios) || 'normal',
      gap: Number(this.gap.get()),
      ...this.originArgs(),
    };
  }

  private editArgs(): Record<string, unknown> | null {
    const f = this.loaded;
    if (!f) return null;
    const out: Record<string, unknown> = {};
    const isGrad = this.tab === 'gradient';
    if (isGrad) out.gradient = this.gradientArgs();
    else if (f.gradient || this.pattern !== f.pattern.toUpperCase()) out.pattern = this.pattern;
    if (!isGrad) {
      if (Math.abs(Number(this.scale.get()) - f.scale) > 1e-9) out.scale = Number(this.scale.get());
      if (Math.abs(Number(this.angle.get()) - f.angle) > 1e-9) out.angle = Number(this.angle.get());
    }
    if (!!this.assoc.get() !== f.associative) out.associative = !!this.assoc.get();
    const island = Math.max(0, ISLANDS.indexOf((this.radioValue(this.islandRadios) || 'normal') as typeof ISLANDS[number]));
    if (island !== f.island) out.style = ISLANDS[island];
    Object.assign(out, this.originArgs());
    if (this.removed.size) out.remove = Array.from(this.removed).sort((a, b) => b - a);
    return out;
  }

  private async run(preview: boolean): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.say('');
    try {
      const out = this.mode === 'edit' ? await this.runEdit() : await this.runCreate();
      if (!out) return;
      if (preview) {
        this.previewing = true;
        this.picking = false;
        this.close();
        setHidden(this.pill, false);
      } else {
        await this.finish();
      }
    } finally {
      this.busy = false;
    }
  }

  private async runCreate(): Promise<boolean> {
    const args: Record<string, unknown> = { picked: true, ...this.settingsArgs() };
    args.draw_order = sysvars.num('HPDRAWORDER', 3);
    if (this.tab === 'gradient') {
      Object.assign(args, this.gradientArgs());
      delete args.scale;
    } else {
      args.pattern = this.pattern;
    }
    args.separate = !!this.separate.get();
    args.retain = String(this.retain.get());
    const out = await exec(this.tab === 'gradient' ? 'gradient' : 'hatch', args, true);
    if (!out) {
      this.say(execError.text || 'The hatch could not be made.');
      return false;
    }
    return true;
  }

  private async runEdit(): Promise<boolean> {
    const args = this.editArgs();
    if (!args) return false;
    const mem = await exec('hatchpick', {}, true);
    const r = mem?.result as { points?: number[][]; handles?: number[] } | undefined;
    if (r?.points?.length) args.add_points = r.points;
    if (r?.handles?.length) args.add_handles = r.handles;
    args.handles = this.editHandles;
    const out = await exec('hatchedit', args, true);
    if (!out) {
      this.say(execError.text || 'The hatch could not be edited.');
      return false;
    }
    return true;
  }

  private async acceptPreview(): Promise<void> {
    setHidden(this.pill, true);
    this.previewing = false;
    await this.finish();
  }

  private async backFromPreview(): Promise<void> {
    setHidden(this.pill, true);
    this.previewing = false;
    const id = docStore.activeId;
    if (id) { try { await api.undo(id); } catch (e) { toast(failure(e), 'error'); } }
    if (docStore.activeId === this.openedFor) this.open();
  }

  private async finish(): Promise<void> {
    await exec('hatchpick', { clear: true }, true);
    this.picking = true;
    this.close();
    this.picking = false;
  }

  private async discard(): Promise<void> {
    await exec('hatchpick', { clear: true }, true);
  }

  private abandon(): void {
    setHidden(this.pill, true);
    this.previewing = false;
    this.picking = false;
    this.close();
  }
}

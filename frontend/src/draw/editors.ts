import { call } from '../io/api';
import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import { messageOf } from './api';
import { drawStore } from './store';
import { runAnnot } from './tools-annot';
import { checkCtl, numberCtl, selectCtl, textCtl, type Ctl } from './ui';

const url = (tail: string): string => `/api/docs/${encodeURIComponent(docStore.activeId ?? '')}/drawann/${tail}`;

interface Glyphs { characteristics: Array<{ key: string; name: string; category: string }>; categories: string[]; modifiers: string[]; zones: string[]; order: string[] }
interface FrameRec { handle: number; char: string; tolerance: string; zone: string; modifier: string; projected: boolean; datums: Array<{ ref: string; mod: string }>; order: string[] }

const CATEGORY: Record<string, string> = { form: 'Form', profile: 'Profile', orientation: 'Orientation', location: 'Location', runout: 'Runout' };
const ZONE: Array<[string, string]> = [['none', 'No sign'], ['dia', 'Diameter'], ['sdia', 'Spherical diameter']];
const MODS: Array<[string, string]> = [['', 'None'], ['M', 'Maximum material'], ['L', 'Least material']];

export interface Placement { point?: number[]; tip?: number[]; tip_link?: { h: number; e: string; t: string } }

let glyphCache: Glyphs | null = null;

export class FrameEditor extends Dialog {
  private readonly char: Ctl<string>;
  private readonly zone = selectCtl('Tolerance zone', ZONE);
  private readonly tol = textCtl('Tolerance', undefined, true);
  private readonly mod = selectCtl('Material condition', MODS);
  private readonly projected = checkCtl('Projected zone');
  private readonly datums: Array<{ ref: Ctl<string>; mod: Ctl<string> }> = [];
  private readonly above = textCtl('Note above');
  private readonly below = textCtl('Note below');
  private readonly arrow = checkCtl('Arrowhead on the leader');
  private readonly preview = el('<div class="dw-frame-prev" aria-live="polite"></div>');
  private readonly order = el('<p class="dw-note"></p>');
  private okBtn: HTMLButtonElement;
  private target: { handle: number } | { place: Placement } | null = null;
  private busy = false;

  constructor() {
    super('Geometric Tolerance Frame', 460);
    this.char = selectCtl('Characteristic', [['position', 'Position']], () => this.paint());
    this.body.append(this.char.el, this.zone.el, this.tol.el, this.mod.el, this.projected.el);
    for (let i = 0; i < 3; i++) {
      const ref = textCtl(`Datum ${i + 1}`, () => this.paint(), true);
      const mod = selectCtl(`Condition ${i + 1}`, MODS, () => this.paint());
      ref.input.setAttribute('maxlength', '1');
      const pair = el('<div class="dw-pair"></div>');
      pair.append(ref.el, mod.el);
      this.body.appendChild(pair);
      this.datums.push({ ref, mod });
    }
    this.body.append(this.above.el, this.below.el, this.arrow.el, this.preview, this.order);
    for (const c of [this.zone, this.tol, this.mod, this.projected, this.above, this.below, this.arrow]) c.input.addEventListener('input', () => this.paint());
    this.zone.input.addEventListener('change', () => this.paint());
    this.mod.input.addEventListener('change', () => this.paint());
    this.projected.input.addEventListener('change', () => this.paint());
    this.button('Cancel', 'ghost', () => this.close());
    this.okBtn = this.button('OK', 'primary', () => { void this.commit(); });
  }

  private async glyphs(): Promise<Glyphs> {
    if (glyphCache) return glyphCache;
    glyphCache = await call<Glyphs>('GET', url('glyphs'));
    return glyphCache;
  }

  private async fill(g: Glyphs): Promise<void> {
    const sel = this.char.input as HTMLSelectElement;
    if (sel.options.length > 1) return;
    sel.replaceChildren();
    for (const cat of g.categories) {
      const group = document.createElement('optgroup');
      group.label = t(CATEGORY[cat] ?? cat);
      for (const c of g.characteristics.filter((x) => x.category === cat)) {
        const o = document.createElement('option');
        o.value = c.key;
        o.textContent = t(c.name);
        group.appendChild(o);
      }
      sel.appendChild(group);
    }
  }

  async create(place: Placement): Promise<void> {
    const g = await this.glyphs();
    await this.fill(g);
    this.target = { place };
    this.char.set('position');
    this.zone.set('dia');
    this.tol.set('0.1');
    this.mod.set('');
    this.projected.set(false);
    for (const d of this.datums) { d.ref.set(''); d.mod.set(''); }
    this.above.set('');
    this.below.set('');
    this.arrow.set(true);
    this.setOrder(g.order);
    this.setTitle('Geometric Tolerance Frame');
    this.paint();
    this.open();
  }

  async edit(handle: number): Promise<boolean> {
    const g = await this.glyphs();
    await this.fill(g);
    let f: FrameRec;
    try { f = await call<FrameRec>('GET', url(`frame/${handle}`)); } catch { return false; }
    this.target = { handle };
    this.char.set(f.char);
    this.zone.set(f.zone || 'none');
    this.tol.set(f.tolerance);
    this.mod.set(f.modifier || '');
    this.projected.set(f.projected);
    this.datums.forEach((d, i) => { d.ref.set(f.datums[i]?.ref ?? ''); d.mod.set(f.datums[i]?.mod ?? ''); });
    this.setOrder(f.order);
    this.paint();
    this.open();
    return true;
  }

  private setOrder(order: string[]): void {
    setText(this.order, `${t('Compartment order')}: ${order.join(', ')}`);
  }

  private text(): string {
    const sel = this.char.input as HTMLSelectElement;
    const name = sel.selectedOptions[0]?.textContent ?? '';
    const z = this.zone.get();
    const mod = this.mod.get();
    const tol = `${z === 'dia' ? 'dia ' : z === 'sdia' ? 'sphere dia ' : ''}${this.tol.get()}${mod ? ` (${mod})` : ''}${this.projected.get() ? ' (projected)' : ''}`;
    const refs = this.datums.filter((d) => d.ref.get().trim()).map((d) => `${d.ref.get().trim().toUpperCase()}${d.mod.get() ? ` (${d.mod.get()})` : ''}`);
    return [name, tol.trim(), ...refs].join('  |  ');
  }

  private paint(): void {
    setText(this.preview, this.text());
  }

  private args(): Record<string, unknown> {
    return {
      char: this.char.get(), zone: this.zone.get(), tolerance: this.tol.get().trim(), modifier: this.mod.get(), projected: this.projected.get(),
      datums: this.datums.filter((d) => d.ref.get().trim()).map((d) => ({ ref: d.ref.get().trim(), mod: d.mod.get() })),
      note_above: this.above.get(), note_below: this.below.get(), arrow: this.arrow.get(),
    };
  }

  private async commit(): Promise<void> {
    if (this.busy || !this.target) return;
    this.busy = true;
    const tg = this.target;
    const a = this.args();
    const res = 'handle' in tg ? await runAnnot('gdtedit', { handle: tg.handle, ...a }) : await runAnnot('gdtframe', { ...a, ...tg.place });
    this.busy = false;
    if (!res) return;
    this.close();
    const h = 'handle' in tg ? tg.handle : Number(res.created);
    if (h) selection.select([h]);
  }

  disable(on: boolean): void {
    this.okBtn.disabled = on;
  }
}

export class DatumEditor extends Dialog {
  private readonly letter = textCtl('Datum letter', undefined, true);
  private readonly filled = checkCtl('Filled triangle');
  private place: Placement = {};
  private handle = 0;

  constructor() {
    super('Datum Feature Symbol', 360);
    this.letter.input.setAttribute('maxlength', '2');
    this.body.append(this.letter.el, this.filled.el);
    this.button('Cancel', 'ghost', () => this.close());
    this.button('OK', 'primary', () => { void this.commit(); });
  }

  show(place: Placement, next: string): void {
    this.place = place;
    this.handle = 0;
    this.letter.set(next);
    this.filled.set(true);
    this.open();
  }

  private async commit(): Promise<void> {
    const args: Record<string, unknown> = { letter: this.letter.get().trim().toUpperCase(), filled: this.filled.get() };
    const res = this.handle ? await runAnnot('datumsym', { ...args, handle: this.handle }) : await runAnnot('datumsym', { ...args, ...this.place });
    if (!res) return;
    this.close();
    if (res.created) selection.select([Number(res.created)]);
  }
}

export class BalloonEditor extends Dialog {
  private readonly text = textCtl('Balloon text', undefined, true);
  private readonly end = selectCtl('Leader end', [['arrow', 'Arrow'], ['dot', 'Dot']]);
  private readonly dia = numberCtl('Diameter (mm)');
  private place: Placement = {};

  constructor() {
    super('Balloon', 360);
    this.body.append(this.text.el, this.end.el, this.dia.el);
    this.button('Cancel', 'ghost', () => this.close());
    this.button('OK', 'primary', () => { void this.commit(); });
  }

  show(place: Placement, next: string): void {
    this.place = place;
    this.text.set(next);
    this.end.set('arrow');
    this.dia.set(null);
    this.open();
  }

  private async commit(): Promise<void> {
    const args: Record<string, unknown> = { text: this.text.get().trim(), end: this.end.get(), ...this.place };
    if (this.dia.get() !== null) args.diameter = this.dia.get();
    const res = await runAnnot('balloon', args);
    if (!res) return;
    this.close();
    if (res.created) selection.select([Number(res.created)]);
  }
}

interface PropsResp { properties: Record<string, string>; statusTerms: string[]; fields: Array<{ tag: string; property: string; label: string }> }

export class TitleBlockDialog extends Dialog {
  private readonly rows = new Map<string, Ctl<string>>();
  private readonly list = el('<div class="dw-form"></div>');
  private readonly note = el('<p class="dw-note"></p>');
  onPlace: (() => void) | null = null;

  constructor() {
    super('Title Block', 480);
    this.body.append(this.list, this.note);
    this.button('Close', 'ghost', () => this.close());
    this.button('Save Properties', '', () => { void this.save(false); });
    this.button('Place New...', '', () => { void this.save(false).then(() => { this.close(); this.onPlace?.(); }); });
    this.button('Fill Title Block', 'primary', () => { void this.save(true); });
  }

  async show(): Promise<void> {
    let r: PropsResp;
    try { r = await call<PropsResp>('GET', url('properties')); } catch (e) { toast(messageOf(e), 'error'); return; }
    if (!this.rows.size) {
      for (const f of r.fields) {
        if (!(f.property in r.properties)) continue;
        const c = f.property === 'status' ? selectCtl(f.label, [['', 'Not set'], ...r.statusTerms.map((s): [string, string] => [s, s])]) : textCtl(f.label);
        c.el.dataset.tag = f.tag;
        this.rows.set(f.property, c);
        this.list.appendChild(c.el);
      }
    }
    for (const [k, c] of this.rows) c.set(r.properties[k] ?? '');
    setText(this.note, t('Sheet number, sheet count, scale and paper size are filled from the layout.'));
    this.open();
  }

  private async save(fill: boolean): Promise<void> {
    const body: Record<string, string> = {};
    for (const [k, c] of this.rows) body[k] = c.get();
    try {
      await call('PUT', url('properties'), body);
    } catch (e) { toast(messageOf(e), 'error'); return; }
    if (!fill) { toast(t('Properties saved.')); return; }
    const res = await runAnnot('titleblock', { layout: drawStore.layout });
    if (res) { toast(res.updated ? t('Title block filled.') : t('Title block placed.')); this.close(); }
  }
}

export class SettingsDialog extends Dialog {
  private readonly nums = new Map<string, Ctl<number | null>>();
  private readonly pattern = textCtl('Section hatch pattern', undefined, true);
  private readonly order = textCtl('Frame compartment order', undefined, true);
  private readonly cols = textCtl('BOM columns', undefined, true);
  private readonly end = selectCtl('Balloon leader end', [['arrow', 'Arrow'], ['dot', 'Dot']]);

  constructor() {
    super('Annotation Settings', 460);
    for (const [k, label] of [['text_height', 'Text height (mm)'], ['balloon_diameter', 'Balloon diameter (mm)'], ['arrow_size', 'Arrow size (mm)'], ['center_extension', 'Centre mark extension (mm)'], ['bom_row_height', 'BOM row height (mm)'], ['hatch_scale', 'Section hatch scale']] as const) {
      const c = numberCtl(label);
      this.nums.set(k, c);
      this.body.appendChild(c.el);
    }
    this.body.append(this.end.el, this.pattern.el, this.order.el, this.cols.el);
    this.button('Cancel', 'ghost', () => this.close());
    this.button('Apply', 'primary', () => { void this.apply(); });
  }

  async show(): Promise<void> {
    let r: { settings: Record<string, unknown> };
    try { r = await call('GET', url('settings')); } catch (e) { toast(messageOf(e), 'error'); return; }
    const s = r.settings;
    for (const [k, c] of this.nums) c.set(typeof s[k] === 'number' ? (s[k] as number) : null);
    this.end.set(String(s.balloon_end ?? 'arrow'));
    this.pattern.set(String(s.hatch_pattern ?? ''));
    this.order.set((s.gdt_order as string[]).join(', '));
    this.cols.set((s.bom_columns as string[]).join(', '));
    this.open();
  }

  private async apply(): Promise<void> {
    const body: Record<string, unknown> = {};
    for (const [k, c] of this.nums) if (c.get() !== null) body[k] = c.get();
    body.balloon_end = this.end.get();
    body.hatch_pattern = this.pattern.get().trim();
    body.gdt_order = this.order.get().split(',').map((x) => x.trim()).filter(Boolean);
    body.bom_columns = this.cols.get().split(',').map((x) => x.trim()).filter(Boolean);
    try {
      await call('PUT', url('settings'), body);
      void docStore.refresh();
      this.close();
    } catch (e) { toast(messageOf(e), 'error'); }
  }
}

export const nextDatumLetter = (taken: string[]): string => {
  for (const c of 'ABCDEFGHJKLMNPRSTUVWXY') if (!taken.includes(c)) return c;
  return 'A';
};

import { Dialog } from '../ui/dialogs';
import { el, q, setStyleVar, setText, setTitle } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import type { NodeWidget, NodeWidgetContext } from '../graph';
import { firstOf, scalar, stopAll } from './wutil';

interface Range { lo: number; hi: number; step: number; decimals: number; integer: boolean }

const num = (v: unknown, d: number): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);

export function rangeOf(s: Record<string, unknown>): Range {
  const lo = num(s.min, 0);
  const hi = Math.max(lo, num(s.max, 10));
  return { lo, hi, step: Math.max(0, num(s.step, 0)), decimals: Math.min(12, Math.max(0, Math.round(num(s.decimals, 2)))), integer: s.integer === true };
}

export function snap(raw: number, r: Range): number {
  let v = Math.min(Math.max(raw, r.lo), r.hi);
  if (r.step > 0) v = Math.min(Math.max(r.lo + Math.round((v - r.lo) / r.step) * r.step, r.lo), r.hi);
  v = Number(v.toFixed(r.decimals));
  if (r.integer) v = Math.min(Math.max(Math.floor(v + 0.5), Math.ceil(r.lo)), Math.floor(r.hi));
  return v;
}

const show = (v: number, r: Range): string => (r.integer ? String(Math.round(v)) : v.toFixed(r.decimals));

class SliderSettings extends Dialog {
  private readonly fields: Record<'min' | 'max' | 'step' | 'decimals', HTMLInputElement>;
  private readonly integer: HTMLInputElement;
  private readonly note: HTMLElement;
  private owner: NodeWidgetContext | null = null;

  constructor() {
    super('Slider Settings', 360);
    const field = (label: string): HTMLInputElement => {
      const input = el<HTMLInputElement>('<input class="cv-input" type="text" inputmode="decimal" spellcheck="false" autocomplete="off">');
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.apply(); } });
      this.field(label, input);
      return input;
    };
    this.fields = { min: field('Minimum'), max: field('Maximum'), step: field('Step'), decimals: field('Decimals') };
    this.integer = el<HTMLInputElement>('<input type="checkbox">');
    this.field('Whole numbers', this.integer).classList.add('cv-check');
    this.note = el('<p class="cv-note"></p>');
    this.body.appendChild(this.note);
    this.button('Cancel', 'ghost', () => this.close());
    this.button('Apply', 'primary', () => this.apply());
  }

  open2(ctx: NodeWidgetContext): void {
    this.owner = ctx;
    const r = rangeOf(ctx.settings());
    this.fields.min.value = String(r.lo);
    this.fields.max.value = String(r.hi);
    this.fields.step.value = String(r.step);
    this.fields.decimals.value = String(r.decimals);
    this.integer.checked = r.integer;
    setText(this.note, '');
    this.open(this.fields.min);
  }

  private apply(): void {
    const ctx = this.owner;
    if (!ctx) return;
    const lo = Number(this.fields.min.value), hi = Number(this.fields.max.value), step = Number(this.fields.step.value), dec = Number(this.fields.decimals.value);
    if (![lo, hi, step, dec].every(Number.isFinite)) { setText(this.note, t('Each field needs a number.')); return; }
    if (lo > hi) { setText(this.note, t('The minimum is larger than the maximum.')); return; }
    if (step < 0) { setText(this.note, t('The step cannot be negative.')); return; }
    const settings = { min: lo, max: hi, step, decimals: Math.min(12, Math.max(0, Math.round(dec))), integer: this.integer.checked };
    const r = rangeOf(settings);
    const cur = firstOf(ctx.persistent('value'));
    ctx.edit({ settings, persistent: { port: 'value', tree: scalar('number', snap(typeof cur === 'number' ? cur : r.lo, r)) } });
    this.close();
  }
}

let dialog: SliderSettings | null = null;

export function sliderWidget(ctx: NodeWidgetContext): NodeWidget {
  const root = el(
    '<div class="gp-slider"><div class="gp-srow"><input class="gp-sval" type="text" inputmode="decimal" spellcheck="false" autocomplete="off" aria-label="Value">' +
    `<button class="gp-sbtn" type="button" aria-label="Slider settings">${icon('settings', 14)}</button></div>` +
    '<div class="gp-strack" role="slider" tabindex="0"><div class="gp-sfill"></div><div class="gp-sthumb"></div></div>' +
    '<div class="gp-sends"><span class="gp-smin"></span><span class="gp-smax"></span></div></div>');
  ctx.host.appendChild(root);
  stopAll(root);
  const input = q<HTMLInputElement>(root, '.gp-sval');
  const track = q<HTMLElement>(root, '.gp-strack');
  const gear = q<HTMLButtonElement>(root, '.gp-sbtn');
  const lo = q(root, '.gp-smin'), hi = q(root, '.gp-smax');
  setTitle(gear, t('Slider settings'));
  let cur = 0;
  let dragging = false;
  let range = rangeOf(ctx.settings());

  const paint = (): void => {
    const span = range.hi - range.lo;
    setStyleVar(track, '--gp-fill', `${span > 0 ? Math.min(1, Math.max(0, (cur - range.lo) / span)) * 100 : 0}%`);
    if (document.activeElement !== input) input.value = show(cur, range);
    setText(lo, show(range.lo, range));
    setText(hi, show(range.hi, range));
    track.setAttribute('aria-valuenow', String(cur));
    track.setAttribute('aria-valuemin', String(range.lo));
    track.setAttribute('aria-valuemax', String(range.hi));
  };

  const write = (v: number, live: boolean): void => {
    cur = v;
    paint();
    ctx.edit({ persistent: { port: 'value', tree: scalar('number', v) } }, { live });
  };

  const fromX = (x: number): number => {
    const r = track.getBoundingClientRect();
    const f = r.width > 0 ? Math.min(1, Math.max(0, (x - r.left) / r.width)) : 0;
    return snap(range.lo + f * (range.hi - range.lo), range);
  };

  track.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    track.setPointerCapture(e.pointerId);
    write(fromX(e.clientX), true);
  });
  track.addEventListener('pointermove', (e) => { if (dragging) write(fromX(e.clientX), true); });
  const release = (e: PointerEvent): void => {
    if (!dragging) return;
    dragging = false;
    if (track.hasPointerCapture(e.pointerId)) track.releasePointerCapture(e.pointerId);
    write(fromX(e.clientX), false);
  };
  track.addEventListener('pointerup', release);
  track.addEventListener('pointercancel', () => { dragging = false; });
  track.addEventListener('keydown', (e) => {
    const unit = range.step > 0 ? range.step : (range.hi - range.lo) / 100 || 1;
    const dir = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    write(snap(cur + dir * unit * (e.shiftKey ? 10 : 1), range), false);
  });

  input.addEventListener('focus', () => input.select());
  const commit = (): void => {
    const v = Number(input.value.replace(',', '.'));
    if (input.value.trim() === '' || !Number.isFinite(v)) { input.value = show(cur, range); return; }
    const next = snap(v, range);
    if (next !== cur) write(next, false);
    else input.value = show(cur, range);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commit(); input.blur(); }
    else if (e.key === 'Escape') { e.preventDefault(); input.value = show(cur, range); input.blur(); }
  });
  input.addEventListener('blur', commit);

  gear.addEventListener('click', () => { dialog ??= new SliderSettings(); dialog.open2(ctx); });

  return {
    size: { w: 168, h: 64 },
    update(node) {
      range = rangeOf(node.settings);
      if (!dragging) {
        const v = firstOf(node.inputs.find((p) => p.name === 'value')?.persistent);
        cur = snap(typeof v === 'number' ? v : range.lo, range);
      }
      paint();
    },
  };
}

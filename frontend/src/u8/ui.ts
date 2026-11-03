import { el, q, setChecked, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';

export interface Ctl<T> { el: HTMLElement; get(): T; set(v: T): void; input: HTMLInputElement | HTMLSelectElement | HTMLButtonElement }

export function section(title: string): { root: HTMLElement; body: HTMLElement; head: HTMLElement } {
  const root = el('<section class="u8-sec"><h4 class="u8-sec-title"></h4><div class="u8-sec-body"></div></section>');
  setText(q(root, 'h4'), t(title));
  return { root, body: q(root, '.u8-sec-body'), head: q(root, 'h4') };
}

export function numberCtl(label: string, value: number, onChange?: () => void, step = 'any'): Ctl<number | null> {
  const root = el('<label class="cv-field"><span></span><input class="cv-input u8-num" type="text" inputmode="decimal" spellcheck="false" autocomplete="off"></label>');
  setText(q(root, 'span'), t(label));
  const input = q<HTMLInputElement>(root, 'input');
  input.value = String(value);
  void step;
  input.addEventListener('change', () => onChange?.());
  input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  return {
    el: root, input,
    get() { const s = input.value.trim().replace(',', '.'); if (!s) return null; const n = Number(s); return Number.isFinite(n) ? n : null; },
    set(v) { setValue(input, v === null ? '' : String(v)); },
  };
}

export function selectCtl(label: string, options: ReadonlyArray<readonly [string, string]>, onChange?: () => void): Ctl<string> {
  const root = el('<label class="cv-field"><span></span><select class="cv-input"></select></label>');
  setText(q(root, 'span'), t(label));
  const sel = q<HTMLSelectElement>(root, 'select');
  for (const [v, text] of options) {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = t(text);
    sel.appendChild(o);
  }
  sel.addEventListener('change', () => onChange?.());
  return { el: root, input: sel, get: () => sel.value, set: (v) => setValue(sel, v) };
}

export function checkCtl(label: string, value = false, onChange?: () => void): Ctl<boolean> {
  const root = el('<label class="cv-field cv-check"><span></span><input type="checkbox"></label>');
  setText(q(root, 'span'), t(label));
  const box = q<HTMLInputElement>(root, 'input');
  box.checked = value;
  box.addEventListener('change', () => onChange?.());
  return { el: root, input: box, get: () => box.checked, set: (v) => setChecked(box, v) };
}

export function button(label: string, onClick: () => void, kind: '' | 'primary' | 'ghost' | 'danger' = 'ghost'): HTMLButtonElement {
  const b = el<HTMLButtonElement>(`<button class="u8-btn${kind ? ` is-${kind}` : ''}" type="button"></button>`);
  setText(b, t(label));
  b.addEventListener('click', onClick);
  return b;
}

export function buttons(...list: HTMLButtonElement[]): HTMLElement {
  const row = el('<div class="u8-btns"></div>');
  row.append(...list);
  return row;
}

export function readout(label: string): { el: HTMLElement; set(v: string): void } {
  const root = el('<div class="cv-field u8-read"><span></span><output></output></div>');
  setText(q(root, 'span'), t(label));
  const out = q(root, 'output');
  return { el: root, set(v) { setText(out, v); if (out.title !== v) out.title = v; } };
}

export const fmt = (v: number | null | undefined, digits = 4): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-';
  if (v === 0) return '0';
  return Math.abs(v) >= 1e5 || Math.abs(v) < 1e-3 ? v.toExponential(2) : String(Number(v.toPrecision(digits)));
};

export function note(): HTMLElement {
  return el('<p class="u8-note"></p>');
}

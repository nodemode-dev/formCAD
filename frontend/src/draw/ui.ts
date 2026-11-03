import { el, q, setChecked, setDisabled, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';

export interface Ctl<T> { el: HTMLElement; input: HTMLInputElement | HTMLSelectElement; get(): T; set(v: T): void; disable(on: boolean): void }

export function section(title: string): { root: HTMLElement; body: HTMLElement } {
  const root = el('<section class="dw-sec"><h4 class="dw-sec-title"></h4><div class="dw-sec-body"></div></section>');
  setText(q(root, 'h4'), t(title));
  return { root, body: q(root, '.dw-sec-body') };
}

export function textCtl(label: string, onChange?: (v: string) => void, mono = false): Ctl<string> {
  const root = el(`<label class="cv-field"><span></span><input class="cv-input${mono ? ' dw-mono' : ''}" type="text" spellcheck="false" autocomplete="off"></label>`);
  setText(q(root, 'span'), t(label));
  const input = q<HTMLInputElement>(root, 'input');
  input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  input.addEventListener('change', () => onChange?.(input.value));
  return { el: root, input, get: () => input.value, set: (v) => setValue(input, v), disable: (on) => setDisabled(input, on) };
}

export function numberCtl(label: string, onChange?: (v: number | null) => void): Ctl<number | null> {
  const root = el('<label class="cv-field"><span></span><input class="cv-input dw-mono dw-num" type="text" inputmode="decimal" spellcheck="false" autocomplete="off"></label>');
  setText(q(root, 'span'), t(label));
  const input = q<HTMLInputElement>(root, 'input');
  const read = (): number | null => {
    const s = input.value.trim().replace(',', '.');
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };
  input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  input.addEventListener('change', () => onChange?.(read()));
  return { el: root, input, get: read, set: (v) => setValue(input, v === null ? '' : String(Number(v.toFixed(4)))), disable: (on) => setDisabled(input, on) };
}

export function selectCtl(label: string, options: ReadonlyArray<readonly [string, string]>, onChange?: (v: string) => void): Ctl<string> {
  const root = el('<label class="cv-field"><span></span><select class="cv-input"></select></label>');
  setText(q(root, 'span'), t(label));
  const sel = q<HTMLSelectElement>(root, 'select');
  for (const [v, text] of options) {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = t(text);
    sel.appendChild(o);
  }
  sel.addEventListener('change', () => onChange?.(sel.value));
  return { el: root, input: sel, get: () => sel.value, set: (v) => setValue(sel, v), disable: (on) => setDisabled(sel, on) };
}

export function checkCtl(label: string, onChange?: (v: boolean) => void): Ctl<boolean> {
  const root = el('<label class="cv-field cv-check"><span></span><input type="checkbox"></label>');
  setText(q(root, 'span'), t(label));
  const box = q<HTMLInputElement>(root, 'input');
  box.addEventListener('change', () => onChange?.(box.checked));
  return { el: root, input: box, get: () => box.checked, set: (v) => setChecked(box, v), disable: (on) => setDisabled(box, on) };
}

export function readout(label: string): { el: HTMLElement; set(v: string): void } {
  const root = el('<div class="cv-field dw-read"><span></span><output></output></div>');
  setText(q(root, 'span'), t(label));
  const out = q(root, 'output');
  return { el: root, set(v) { setText(out, v); if (out.title !== v) out.title = v; } };
}

export function button(label: string, onClick: () => void, kind: '' | 'primary' | 'danger' = ''): HTMLButtonElement {
  const b = el<HTMLButtonElement>(`<button class="dw-btn${kind ? ` is-${kind}` : ''}" type="button"></button>`);
  setText(b, t(label));
  b.addEventListener('click', onClick);
  return b;
}

export function row(...nodes: HTMLElement[]): HTMLElement {
  const r = el('<div class="dw-btns"></div>');
  r.append(...nodes);
  return r;
}

export function note(): HTMLElement {
  return el('<p class="dw-note"></p>');
}

export const ratio = (s: number): string => {
  if (!Number.isFinite(s) || s <= 0) return '1:1';
  const clean = (n: number): string => String(Number(n.toFixed(4)));
  if (s >= 1) return `${clean(s)}:1`;
  return `1:${clean(1 / s)}`;
};

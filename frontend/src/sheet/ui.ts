import { el, q, setDisabled, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';

export interface Row<T> {
  root: HTMLElement;
  input: HTMLInputElement | HTMLSelectElement;
  get(): T;
  set(v: T): void;
  use(on: boolean): void;
}

export const fmt = (v: number | null | undefined, digits = 6): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-';
  return String(Number(v.toFixed(digits)));
};

const shell = (label: string, unit: string): { root: HTMLElement; slot: HTMLElement } => {
  const root = el(`<label class="sm-row"><span class="sm-lab"></span><span class="sm-slot"></span><span class="sm-unit"></span></label>`);
  setText(q(root, '.sm-lab'), t(label));
  setText(q(root, '.sm-unit'), unit);
  return { root, slot: q(root, '.sm-slot') };
};

export function valueRow(label: string, unit: string, onInput: () => void): Row<number | string | null> {
  const { root, slot } = shell(label, unit);
  const input = el<HTMLInputElement>('<input class="cv-input sm-in" type="text" inputmode="decimal" spellcheck="false" autocomplete="off">');
  slot.appendChild(input);
  input.addEventListener('input', onInput);
  input.addEventListener('keydown', (e) => { e.stopPropagation(); });
  return {
    root,
    input,
    get: () => {
      const s = input.value.trim().replace(',', '.');
      if (!s) return null;
      const n = Number(s);
      return Number.isFinite(n) ? n : s;
    },
    set: (v) => { setValue(input, v === null || v === undefined ? '' : String(v)); },
    use: (on) => { setDisabled(input, !on); root.classList.toggle('is-idle', !on); },
  };
}

export function choiceRow(label: string, options: ReadonlyArray<readonly [string, string]>, onChange: () => void): Row<string> {
  const { root, slot } = shell(label, '');
  const sel = el<HTMLSelectElement>('<select class="cv-input sm-in"></select>');
  for (const [v, text] of options) {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = t(text);
    sel.appendChild(o);
  }
  slot.appendChild(sel);
  sel.addEventListener('change', onChange);
  return {
    root,
    input: sel,
    get: () => sel.value,
    set: (v) => { setValue(sel, v); },
    use: (on) => { setDisabled(sel, !on); root.classList.toggle('is-idle', !on); },
  };
}

export function checkRow(label: string, onChange: () => void): Row<boolean> {
  const { root, slot } = shell(label, '');
  const box = el<HTMLInputElement>('<input type="checkbox" class="sm-box">');
  slot.appendChild(box);
  box.addEventListener('change', onChange);
  return {
    root,
    input: box,
    get: () => box.checked,
    set: (v) => { box.checked = v; },
    use: (on) => { setDisabled(box, !on); root.classList.toggle('is-idle', !on); },
  };
}

export function readoutRow(label: string, unit = ''): { root: HTMLElement; set(v: string): void } {
  const { root, slot } = shell(label, unit);
  root.classList.add('sm-read');
  const out = el<HTMLElement>('<output class="sm-out"></output>');
  slot.appendChild(out);
  return { root, set: (v) => { setText(out, v); } };
}

export function heading(text: string): HTMLElement {
  const h = el('<h4 class="sm-head"></h4>');
  setText(h, t(text));
  return h;
}

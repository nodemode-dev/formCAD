import { el, q, setChecked, setText } from '../dom';
import { t } from '../i18n';

export interface Field {
  el: HTMLElement;
  input: HTMLInputElement | HTMLSelectElement;
  get(): string | number | boolean;
  set(v: string | number | boolean): void;
  enable(on: boolean): void;
  change: ((f: Field) => void) | null;
  live?: boolean;
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
const show = (v: number): string => String(Number(v.toFixed(6)));

function build(label: string, control: string, extra = ''): { root: HTMLElement; box: HTMLInputElement | HTMLSelectElement } {
  const root = el(`<label class="cv-field${extra}"><span></span>${control}</label>`);
  setText(q(root, 'span'), t(label));
  const box = q<HTMLInputElement | HTMLSelectElement>(root, 'input, select');
  box.setAttribute('aria-label', label);
  return { root, box };
}

function wire(f: Field): Field {
  f.input.addEventListener('change', () => f.change?.(f));
  f.input.addEventListener('input', () => { if (f.live) f.change?.(f); });
  return f;
}

function enabler(root: HTMLElement, box: HTMLInputElement | HTMLSelectElement): (on: boolean) => void {
  return (on) => {
    if (box.disabled !== !on) box.disabled = !on;
    root.classList.toggle('is-off', !on);
  };
}

export function numField(label: string, limits: { min?: number; max?: number; step?: number; int?: boolean } = {}): Field {
  const attrs = [limits.min !== undefined ? ` min="${limits.min}"` : '', limits.max !== undefined ? ` max="${limits.max}"` : '', ` step="${limits.step ?? (limits.int ? 1 : 'any')}"`].join('');
  const { root, box } = build(label, `<input class="cv-input" type="number"${attrs}>`);
  const input = box as HTMLInputElement;
  const f: Field = {
    el: root,
    input,
    get: () => {
      const raw = Number(input.value);
      const v = Number.isFinite(raw) ? raw : 0;
      const c = clamp(v, limits.min ?? -Infinity, limits.max ?? Infinity);
      return limits.int ? Math.round(c) : c;
    },
    set: (v) => { const s = show(Number(v)); if (input.value !== s && document.activeElement !== input) input.value = s; },
    enable: enabler(root, input),
    change: null,
  };
  input.addEventListener('change', () => {
    const raw = Number(input.value);
    if (Number.isFinite(raw)) input.value = show(f.get() as number);
  });
  return wire(f);
}

export function textField(label: string, hint = ''): Field {
  const { root, box } = build(label, '<input class="cv-input" type="text" spellcheck="false" autocomplete="off">');
  const input = box as HTMLInputElement;
  if (hint) input.placeholder = hint;
  const f: Field = {
    el: root, input,
    get: () => input.value,
    set: (v) => { const s = String(v); if (input.value !== s && document.activeElement !== input) input.value = s; },
    enable: enabler(root, input),
    change: null,
  };
  return wire(f);
}

export function comboField(label: string, suggestions: string[]): Field {
  const id = `u2-dl-${Math.random().toString(36).slice(2, 8)}`;
  const { root, box } = build(label, `<input class="cv-input" type="text" list="${id}" spellcheck="false" autocomplete="off"><datalist id="${id}"></datalist>`);
  const input = box as HTMLInputElement;
  const list = q<HTMLDataListElement>(root, 'datalist');
  for (const s of suggestions) { const o = document.createElement('option'); o.value = s; list.appendChild(o); }
  const f: Field = {
    el: root, input,
    get: () => input.value,
    set: (v) => { const s = String(v); if (input.value !== s && document.activeElement !== input) input.value = s; },
    enable: enabler(root, input),
    change: null,
  };
  return wire(f);
}

export function checkField(label: string): Field {
  const { root, box } = build(label, '<input type="checkbox">', ' cv-check');
  const input = box as HTMLInputElement;
  const f: Field = {
    el: root, input,
    get: () => input.checked,
    set: (v) => setChecked(input, !!v),
    enable: enabler(root, input),
    change: null,
  };
  return wire(f);
}

export function selectField(label: string, options: ReadonlyArray<readonly [string, string]>): Field {
  const { root, box } = build(label, '<select class="cv-input"></select>');
  const select = box as HTMLSelectElement;
  for (const [value, text] of options) {
    const o = document.createElement('option');
    o.value = value;
    o.textContent = t(text);
    select.appendChild(o);
  }
  const f: Field = {
    el: root, input: select,
    get: () => select.value,
    set: (v) => { const s = String(v); if (select.value !== s) select.value = s; },
    enable: enabler(root, select),
    change: null,
  };
  return wire(f);
}

export function setOptions(f: Field, options: ReadonlyArray<readonly [string, string]>): void {
  const select = f.input as HTMLSelectElement;
  const keep = select.value;
  const have = Array.from(select.options);
  const same = have.length === options.length && have.every((o, i) => o.value === options[i][0] && o.textContent === options[i][1]);
  if (same) return;
  select.replaceChildren(...options.map(([value, text]) => { const o = document.createElement('option'); o.value = value; o.textContent = text; return o; }));
  select.value = keep;
}

export const ACI_CHOICES: ReadonlyArray<readonly [string, string]> = [
  ['256', 'ByLayer'], ['0', 'ByBlock'], ['1', 'Red'], ['2', 'Yellow'], ['3', 'Green'], ['4', 'Cyan'], ['5', 'Blue'], ['6', 'Magenta'], ['7', 'White'], ['-1', 'Index...'],
];

export function aciField(label: string): Field {
  const root = el('<div class="cv-field u2-aci"><span></span><select class="cv-input"></select><input class="cv-input" type="number" min="1" max="255" step="1"></div>');
  setText(q(root, 'span'), t(label));
  const select = q<HTMLSelectElement>(root, 'select');
  const idx = q<HTMLInputElement>(root, 'input');
  select.setAttribute('aria-label', label);
  idx.setAttribute('aria-label', `${label} index`);
  for (const [value, text] of ACI_CHOICES) {
    const o = document.createElement('option');
    o.value = value;
    o.textContent = t(text);
    select.appendChild(o);
  }
  const sync = (): void => { idx.hidden = select.value !== '-1'; };
  const f: Field = {
    el: root, input: select,
    get: () => (select.value === '-1' ? clamp(Math.round(Number(idx.value) || 8), 1, 255) : Number(select.value)),
    set: (v) => {
      const n = Number(v);
      const preset = ACI_CHOICES.some(([k]) => k === String(n) && k !== '-1');
      select.value = preset ? String(n) : '-1';
      if (!preset && document.activeElement !== idx) idx.value = String(n);
      sync();
    },
    enable: (on) => { select.disabled = !on; idx.disabled = !on; root.classList.toggle('is-off', !on); },
    change: null,
  };
  select.addEventListener('change', () => { sync(); f.change?.(f); });
  idx.addEventListener('change', () => f.change?.(f));
  sync();
  return f;
}

export function rowOf(...fields: Field[]): HTMLElement {
  const row = el('<div class="u2-pair"></div>');
  for (const f of fields) row.appendChild(f.el);
  return row;
}

export function group(title: string, ...children: Array<HTMLElement | Field>): HTMLElement {
  const box = el('<fieldset class="u2-group"><legend></legend></fieldset>');
  setText(q(box, 'legend'), t(title));
  for (const c of children) box.appendChild('el' in c ? c.el : c);
  return box;
}

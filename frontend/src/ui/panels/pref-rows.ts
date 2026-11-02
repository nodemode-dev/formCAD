import { el, q, setText, setValue } from '../dom';
import type { Row } from './controls';

const SWATCH_BASE: Record<number, string> = {
  1: '#ff0000', 2: '#ffff00', 3: '#00ff00', 4: '#00ffff', 5: '#0000ff', 6: '#ff00ff', 7: '#ffffff', 8: '#808080', 9: '#c0c0c0',
};
const LEVELS = [1, 0.741, 0.506, 0.408, 0.31];

function hsv(h: number, s: number, v: number): string {
  const f = (n: number): number => {
    const k = (n + h / 60) % 6;
    return v - v * s * Math.max(0, Math.min(k, 4 - k, 1));
  };
  return '#' + [f(5), f(3), f(1)].map((c) => Math.round(c * 255).toString(16).padStart(2, '0')).join('');
}

export function aciHex(n: number): string {
  const i = Math.round(n);
  if (SWATCH_BASE[i]) return SWATCH_BASE[i];
  if (i >= 250 && i <= 255) {
    const g = [51, 91, 132, 173, 214, 255][i - 250].toString(16).padStart(2, '0');
    return `#${g}${g}${g}`;
  }
  if (i >= 10 && i <= 249) {
    const k = i - 10, hue = Math.floor(k / 10) * 15, step = k % 10;
    return hsv(hue, step % 2 === 0 ? 1 : 0.333, LEVELS[step >> 1]);
  }
  return '#808080';
}

export function enable(node: HTMLElement, on: boolean): void {
  const off = !on;
  if (node.classList.contains('is-off') !== off) node.classList.toggle('is-off', off);
  for (const c of Array.from(node.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>('input, select, button'))) {
    if (c.disabled !== off) c.disabled = off;
  }
}

export function radioRow(label: string, options: ReadonlyArray<readonly [string, string]>, onChange: (v: string) => void): Row<string> {
  const root = el('<div class="cv-field cv-radio-row" role="radiogroup"><span></span><div class="cv-radios"></div></div>');
  setText(q(root, 'span'), label);
  const group = q(root, '.cv-radios');
  const name = `rr-${label.replace(/\W+/g, '-').toLowerCase()}-${Math.random().toString(36).slice(2, 7)}`;
  const inputs: HTMLInputElement[] = [];
  for (const [value, text] of options) {
    const item = el<HTMLLabelElement>('<label class="cv-radio"><input type="radio"><span></span></label>');
    const input = q<HTMLInputElement>(item, 'input');
    input.name = name;
    input.value = value;
    setText(q(item, 'span'), text);
    input.addEventListener('change', () => { if (input.checked) onChange(value); });
    inputs.push(input);
    group.appendChild(item);
  }
  return { el: root, set(v) { for (const i of inputs) if (i.checked !== (i.value === v)) i.checked = i.value === v; } };
}

export function textRow(label: string, onCommit: (v: string) => void, placeholder = ''): Row<string> {
  const root = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
  setText(q(root, 'span'), label);
  const box = q<HTMLInputElement>(root, 'input');
  box.placeholder = placeholder;
  box.setAttribute('aria-label', label);
  box.addEventListener('change', () => onCommit(box.value.trim()));
  box.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); box.blur(); } });
  return { el: root, set(v) { setValue(box, v); } };
}

export function colorDefaultRow(label: string, fallback: () => string, onChange: (hex: string) => void): Row<string> {
  const root = el('<div class="cv-field cv-color-row"><span></span><div class="cv-color-ctl"><input class="cv-input cv-color" type="color"><code class="cv-hex"></code><button class="cv-btn" type="button">Default</button></div></div>');
  setText(q(root, 'span'), label);
  const input = q<HTMLInputElement>(root, 'input');
  const readout = q(root, '.cv-hex');
  const reset = q<HTMLButtonElement>(root, 'button');
  input.setAttribute('aria-label', label);
  input.addEventListener('input', () => onChange(input.value));
  reset.addEventListener('click', () => onChange(''));
  return {
    el: root,
    set(v) {
      const shown = v || fallback();
      setValue(input, /^#[0-9a-f]{6}$/i.test(shown) ? shown.toLowerCase() : '#000000');
      setText(readout, (v || fallback()).replace('#', '').toLowerCase());
      if (reset.disabled !== !v) reset.disabled = !v;
    },
  };
}

export function aciRow(label: string, onChange: (n: number) => void): Row<number> {
  const root = el('<label class="cv-field cv-aci-row"><span></span><div class="cv-aci-ctl"><i class="cv-swatch"></i><input class="cv-input" type="number" min="1" max="255" step="1"></div></label>');
  setText(q(root, 'span'), label);
  const swatch = q<HTMLElement>(root, '.cv-swatch');
  const box = q<HTMLInputElement>(root, 'input');
  box.setAttribute('aria-label', label);
  const paint = (n: number): void => { const c = aciHex(n); if (swatch.style.background !== c) swatch.style.background = c; };
  box.addEventListener('change', () => {
    const raw = Math.round(box.valueAsNumber);
    if (!Number.isFinite(raw)) return;
    const n = Math.min(255, Math.max(1, raw));
    box.value = String(n);
    paint(n);
    onChange(n);
  });
  return { el: root, set(n) { setValue(box, String(n)); paint(n); } };
}

export function infoRow(label: string): Row<string> {
  const root = el('<div class="cv-field cv-info-row"><span></span><output class="cv-info-value"></output></div>');
  setText(q(root, 'span'), label);
  const out = q(root, 'output');
  return { el: root, set(v) { setText(out, v); out.title = v; } };
}

export function pathRow(label: string, onCopy: () => void): Row<string> & { button: HTMLButtonElement } {
  const root = el('<div class="cv-field cv-path-row"><span></span><div class="cv-path-ctl"><input class="cv-input" type="text" readonly spellcheck="false"><button class="cv-btn" type="button">Copy</button></div></div>');
  setText(q(root, 'span'), label);
  const input = q<HTMLInputElement>(root, 'input');
  input.setAttribute('aria-label', label);
  const button = q<HTMLButtonElement>(root, 'button');
  button.addEventListener('click', onCopy);
  return { el: root, button, set(v) { setValue(input, v); input.title = v; } };
}

export function buttonRow(label: string, button: string, onClick: () => void, kind: '' | 'danger' | 'ghost' = ''): { el: HTMLElement; button: HTMLButtonElement } {
  const root = el(`<div class="cv-field cv-button-row"><span></span><div class="cv-button-ctl"><button class="cv-btn${kind ? ` cv-btn-${kind}` : ''}" type="button"></button></div></div>`);
  setText(q(root, 'span'), label);
  const b = q<HTMLButtonElement>(root, 'button');
  setText(b, button);
  b.addEventListener('click', onClick);
  return { el: root, button: b };
}

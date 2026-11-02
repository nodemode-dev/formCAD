import type { PropertyField } from '../../io/api';
import { el, q, setClass, setHidden, setText, setTitle, setValue } from '../dom';
import { aciHex } from './pref-rows';

export interface PropRow {
  el: HTMLElement;
  paint(f: PropertyField | undefined, lock?: string): void;
}

export type Commit = (value: unknown) => void;

export const VARIES = '*VARIES*';
const READ_ONLY = 'Read-only';

export function fmtNumber(v: number, digits: number): string {
  if (!Number.isFinite(v)) return '';
  return String(Number(v.toFixed(Math.min(12, Math.max(0, digits)))));
}

export function setOptions(sel: HTMLSelectElement, items: ReadonlyArray<readonly [string, string]>): void {
  items.forEach(([value, text], i) => {
    let o = sel.options[i];
    if (!o) {
      o = document.createElement('option');
      sel.appendChild(o);
    }
    if (o.getAttribute('value') !== value) o.setAttribute('value', value);
    if (o.textContent !== text) o.textContent = text;
  });
  while (sel.options.length > items.length) sel.remove(sel.options.length - 1);
}

function choose(sel: HTMLSelectElement, current: string): void {
  if (current === '') {
    if (sel.selectedIndex === 0) return;
    sel.selectedIndex = 0;
    sel.dispatchEvent(new Event('change'));
    return;
  }
  if (sel.value !== current) sel.value = current;
}

function lock(root: HTMLElement, controls: HTMLInputElement[] | HTMLSelectElement[], ro: boolean, reason: string): void {
  setClass(root, 'is-readonly', ro);
  setTitle(root, ro ? reason : '');
  for (const c of controls) {
    if (c instanceof HTMLInputElement && (c.type === 'text' || c.type === 'number')) {
      if (c.readOnly !== ro) c.readOnly = ro;
    } else if (c.disabled !== ro) c.disabled = ro;
  }
}

function frame(label: string, control: string): { root: HTMLLabelElement } {
  const root = el<HTMLLabelElement>(`<label class="cv-prop-row"><span></span>${control}</label>`);
  setText(q(root, 'span'), label);
  return { root };
}

export function numberRow(label: string, commit: Commit, digits: () => number): PropRow {
  const { root } = frame(label, '<input class="cv-input pp-in" type="number" step="any">');
  const box = q<HTMLInputElement>(root, 'input');
  box.setAttribute('aria-label', label);
  box.addEventListener('change', () => {
    const v = box.valueAsNumber;
    if (Number.isFinite(v)) commit(v);
  });
  return {
    el: root,
    paint(f, why) {
      setHidden(root, !f);
      if (!f) return;
      const ro = f.readonly || !!why;
      lock(root, [box], ro, why || READ_ONLY);
      const none = f.varies || typeof f.value !== 'number';
      const hint = f.varies ? VARIES : '';
      if (box.placeholder !== hint) box.placeholder = hint;
      setValue(box, none ? '' : fmtNumber(f.value as number, digits()));
    },
  };
}

export function textRow(label: string, commit: Commit): PropRow {
  const { root } = frame(label, '<input class="cv-input pp-in" type="text" spellcheck="false" autocomplete="off">');
  const box = q<HTMLInputElement>(root, 'input');
  box.setAttribute('aria-label', label);
  box.addEventListener('change', () => commit(box.value));
  box.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); box.blur(); }
    else if (e.key === 'Escape') box.blur();
  });
  return {
    el: root,
    paint(f, why) {
      setHidden(root, !f);
      if (!f) return;
      const ro = f.readonly || !!why;
      lock(root, [box], ro, why || READ_ONLY);
      const hint = f.varies ? VARIES : '';
      if (box.placeholder !== hint) box.placeholder = hint;
      setValue(box, f.varies || f.value === null || f.value === undefined ? '' : String(f.value));
    },
  };
}

export function readRow(label: string, digits: () => number): PropRow {
  const root = el<HTMLDivElement>('<div class="cv-prop-row is-readonly"><span></span><output class="pp-out"></output></div>');
  setText(q(root, 'span'), label);
  const out = q(root, 'output');
  return {
    el: root,
    paint(f) {
      setHidden(root, !f);
      if (!f) return;
      let text = '';
      if (f.varies) text = VARIES;
      else if (typeof f.value === 'number') text = fmtNumber(f.value, digits());
      else if (typeof f.value === 'boolean') text = f.value ? 'Yes' : 'No';
      else if (f.value !== null && f.value !== undefined) text = String(f.value);
      setText(out, text);
      setTitle(root, READ_ONLY);
    },
  };
}

export function boolRow(label: string, commit: Commit): PropRow {
  const { root } = frame(label, '<input class="pp-check" type="checkbox">');
  const box = q<HTMLInputElement>(root, 'input');
  box.setAttribute('aria-label', label);
  box.addEventListener('change', () => commit(box.checked));
  return {
    el: root,
    paint(f, why) {
      setHidden(root, !f);
      if (!f) return;
      lock(root, [box], f.readonly || !!why, why || READ_ONLY);
      const on = f.value === true && !f.varies;
      if (box.checked !== on) box.checked = on;
      if (box.indeterminate !== f.varies) box.indeterminate = f.varies;
    },
  };
}

export interface ChoiceOptions {
  label?: (value: string) => string;
  extra?: boolean;
}

export function choiceRow(label: string, commit: Commit, opts: ChoiceOptions = {}): PropRow {
  const { root } = frame(label, '<select class="cv-input pp-in"></select>');
  const sel = q<HTMLSelectElement>(root, 'select');
  sel.setAttribute('aria-label', label);
  sel.addEventListener('change', () => { if (sel.value !== '') commit(sel.value); });
  const name = opts.label ?? ((v: string): string => v);
  return {
    el: root,
    paint(f, why) {
      setHidden(root, !f);
      if (!f) return;
      lock(root, [sel], f.readonly || !!why, why || READ_ONLY);
      const list = (f.options ?? []).map(String);
      const current = f.varies || f.value === null || f.value === undefined ? '' : String(f.value);
      const items: Array<[string, string]> = [['', f.varies ? VARIES : '']];
      for (const v of list) items.push([v, name(v)]);
      if (current !== '' && !list.includes(current)) items.push([current, name(current)]);
      setOptions(sel, items);
      if (sel.options[0] && !sel.options[0].hidden) sel.options[0].hidden = true;
      choose(sel, current);
    },
  };
}

const NAMED: ReadonlyArray<readonly [string, string]> = [['ByLayer', 'ByLayer'], ['ByBlock', 'ByBlock'], ['1', 'Red'], ['2', 'Yellow'], ['3', 'Green'], ['4', 'Cyan'], ['5', 'Blue'], ['6', 'Magenta'], ['7', 'White']];

export function colorText(v: unknown): string {
  if (typeof v === 'number') return NAMED.find(([k]) => k === String(v))?.[1] ?? `Color ${v}`;
  return typeof v === 'string' ? (NAMED.find(([k]) => k === v)?.[1] ?? v) : '';
}

export function swatchOf(v: unknown): string {
  if (typeof v === 'number' && v >= 1 && v <= 255) return aciHex(v);
  if (typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v)) return v.toLowerCase();
  return '';
}

export function colorRow(label: string, commit: Commit, trueColor = true): PropRow {
  const wrap = trueColor ? '<span class="pp-swatch"><i></i><input type="color" tabindex="-1"></span>' : '<span class="pp-swatch"><i></i></span>';
  const { root } = frame(label, `<div class="pp-color">${wrap}<select class="cv-input pp-in"></select></div>`);
  const sel = q<HTMLSelectElement>(root, 'select');
  const dot = q<HTMLElement>(root, '.pp-swatch i');
  const pick = trueColor ? q<HTMLInputElement>(root, 'input[type="color"]') : null;
  sel.setAttribute('aria-label', label);
  sel.addEventListener('change', () => {
    const v = sel.value;
    if (v === '') return;
    commit(/^\d+$/.test(v) ? Number(v) : v);
  });
  pick?.addEventListener('change', () => commit(pick.value.toUpperCase()));
  return {
    el: root,
    paint(f, why) {
      setHidden(root, !f);
      if (!f) return;
      const ro = f.readonly || !!why;
      lock(root, [sel], ro, why || READ_ONLY);
      if (pick && pick.disabled !== ro) pick.disabled = ro;
      const current = f.varies || f.value === null || f.value === undefined ? '' : String(f.value);
      const items: Array<readonly [string, string]> = [['', f.varies ? VARIES : ''], ...NAMED];
      if (current !== '' && !NAMED.some(([k]) => k === current)) items.push([current, colorText(f.value)]);
      setOptions(sel, items);
      if (sel.options[0] && !sel.options[0].hidden) sel.options[0].hidden = true;
      choose(sel, current);
      const hex = f.varies ? '' : swatchOf(f.value);
      if (dot.dataset.c !== hex) { dot.dataset.c = hex; dot.style.background = hex; }
      if (pick && hex && pick.value !== hex) pick.value = hex;
    },
  };
}

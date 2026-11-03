import { el, q, setChecked, setClass, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';

export interface FieldSpec {
  name: string;
  type: string;
  default?: unknown;
  label?: string;
  min?: number | null;
  max?: number | null;
  unit?: string | null;
  choices?: unknown;
  group?: string | null;
  kind?: string;
  nullable?: boolean;
}

export interface FieldForm {
  el: HTMLElement;
  names: string[];
  set(values: Record<string, unknown>): void;
  read(): Record<string, unknown>;
  rowOf(name: string): HTMLElement | undefined;
  show(names: Set<string> | null): void;
}

export const prettify = (s: string): string => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

export function choiceList(raw: unknown): Array<[string, string]> {
  if (Array.isArray(raw)) {
    return raw.map((c) => {
      if (Array.isArray(c)) return [String(c[0]), String(c[1] ?? c[0])] as [string, string];
      if (c && typeof c === 'object') { const o = c as { value?: unknown; id?: unknown; label?: unknown }; const v = String(o.value ?? o.id ?? ''); return [v, String(o.label ?? prettify(v))] as [string, string]; }
      return [String(c), prettify(String(c))] as [string, string];
    });
  }
  if (raw && typeof raw === 'object') return Object.entries(raw as Record<string, unknown>).map(([k, v]) => [k, String(v)] as [string, string]);
  return [];
}

const kindOf = (s: FieldSpec): string => s.kind ?? s.type;

function boundsText(s: FieldSpec): string {
  const lo = s.min ?? null, hi = s.max ?? null;
  if (lo !== null && hi !== null) return `${lo} to ${hi}`;
  if (lo !== null) return `at least ${lo}`;
  if (hi !== null) return `at most ${hi}`;
  return '';
}

interface Row { spec: FieldSpec; root: HTMLElement; get(): unknown; set(v: unknown): void; input: HTMLInputElement | HTMLSelectElement }

export function fieldForm(specs: FieldSpec[], onChange: (name: string, value: unknown) => void, opts: { grouped?: boolean } = {}): FieldForm {
  const root = el('<div class="cm-fields"></div>');
  const rows = new Map<string, Row>();
  let lastGroup: string | null = null;
  for (const s of specs) {
    const k = kindOf(s);
    const label = `${s.label ?? prettify(s.name)}${s.unit ? ` (${s.unit})` : ''}`;
    if (opts.grouped && (s.group ?? '') !== lastGroup) {
      lastGroup = s.group ?? '';
      if (lastGroup) { const h = el('<div class="cm-group"></div>'); h.textContent = t(prettify(lastGroup)); root.appendChild(h); }
    }
    let row: Row;
    if (k === 'bool') {
      const r = el('<label class="cv-field cv-check cm-row"><span></span><input type="checkbox"></label>');
      setText(q(r, 'span'), t(label));
      const box = q<HTMLInputElement>(r, 'input');
      box.addEventListener('change', () => onChange(s.name, box.checked));
      row = { spec: s, root: r, input: box, get: () => box.checked, set: (v) => setChecked(box, !!v) };
    } else if (k === 'choice') {
      const r = el('<label class="cv-field cm-row"><span></span><select class="cv-input"></select></label>');
      setText(q(r, 'span'), t(label));
      const sel = q<HTMLSelectElement>(r, 'select');
      for (const [v, text] of choiceList(s.choices)) { const o = document.createElement('option'); o.value = v; o.textContent = t(text); sel.appendChild(o); }
      sel.addEventListener('change', () => onChange(s.name, sel.value));
      row = { spec: s, root: r, input: sel, get: () => sel.value, set: (v) => setValue(sel, String(v ?? '')) };
    } else if (k === 'text' && s.name === 'profile') {
      const r = el('<label class="cv-field cm-row cm-wide"><span></span><textarea class="cv-input cm-area" spellcheck="false" rows="5"></textarea></label>');
      setText(q(r, 'span'), t(label));
      const ta = q<HTMLTextAreaElement>(r, 'textarea');
      ta.addEventListener('keydown', (e) => e.stopPropagation());
      ta.addEventListener('change', () => onChange(s.name, ta.value));
      const input = ta as unknown as HTMLInputElement;
      row = { spec: s, root: r, input, get: () => ta.value, set: (v) => { const x = v === null || v === undefined ? '' : String(v); if (ta.value !== x && document.activeElement !== ta) ta.value = x; } };
    } else if (k === 'text') {
      const r = el('<label class="cv-field cm-row"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(r, 'span'), t(label));
      const inp = q<HTMLInputElement>(r, 'input');
      inp.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });
      inp.addEventListener('change', () => onChange(s.name, inp.value));
      row = { spec: s, root: r, input: inp, get: () => inp.value, set: (v) => setValue(inp, v === null || v === undefined ? '' : String(v)) };
    } else {
      const vec = k === 'vec2';
      const r = el('<label class="cv-field cm-row"><span></span><input class="cv-input u8-num" type="text" inputmode="decimal" spellcheck="false" autocomplete="off"></label>');
      setText(q(r, 'span'), t(label));
      const inp = q<HTMLInputElement>(r, 'input');
      const b = boundsText(s);
      if (b) inp.title = b;
      inp.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });
      const parse = (): unknown => {
        const raw = inp.value.trim().replace(/,/g, vec ? ' ' : '.');
        if (vec) { const p = raw.split(/\s+/).map(Number); return p.length === 2 && p.every(Number.isFinite) ? p : null; }
        if (!raw) return null;
        const n = Number(raw);
        return Number.isFinite(n) ? (k === 'int' ? Math.round(n) : n) : null;
      };
      inp.addEventListener('change', () => {
        const v = parse();
        if (v === null && s.nullable && !inp.value.trim()) { setClass(r, 'is-bad', false); onChange(s.name, null); return; }
        const bad = v === null ||(!vec && ((s.min !== null && s.min !== undefined && (v as number) < s.min) || (s.max !== null && s.max !== undefined && (v as number) > s.max)));
        setClass(r, 'is-bad', bad);
        if (!bad) onChange(s.name, v);
      });
      row = {
        spec: s, root: r, input: inp, get: parse,
        set: (v) => { setClass(r, 'is-bad', false); setValue(inp, Array.isArray(v) ? v.join(' ') : v === null || v === undefined ? '' : String(v)); },
      };
    }
    rows.set(s.name, row);
    root.appendChild(row.root);
  }
  return {
    el: root,
    names: specs.map((s) => s.name),
    set(values) { for (const [n, row] of rows) { const v = values[n]; row.set(v === undefined ? row.spec.default : v); } },
    read() { const o: Record<string, unknown> = {}; for (const [n, row] of rows) o[n] = row.get(); return o; },
    rowOf: (n) => rows.get(n)?.root,
    show(names) { for (const [n, row] of rows) { const on = !names || names.has(n); if (row.root.hidden === on) row.root.hidden = !on; } },
  };
}

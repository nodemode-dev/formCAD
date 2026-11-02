import { api, type CalcResult, type CommandLineState } from '../../io/api';
import type { DockPanel } from '../dock';
import { docStore } from '../doc-store';
import { el, q, setDisabled, setHidden, setText, setTitle, stored, store } from '../dom';
import { icon } from '../icons';
import { toast } from '../toast';
import { failure } from './engine-run';
import { setOptions } from './prop-rows';

const KEY = 'formCAD.quickcalc';
const HISTORY_SHOWN = 20;
const HISTORY_MAX = 100;
const VARIABLES_MAX = 50;
const RESERVED = new Set(['pi', 'e', 'ans']);
const NAME = /^[A-Za-z][A-Za-z0-9_]*$/;
const ENDS_OPEN = /[+\-*/^(,&]\s*$|\(\s*$/;

interface HistoryEntry { e: string; r: string }
type CalcValue = number | [number, number];
interface Saved { history: HistoryEntry[]; vars: Record<string, CalcValue>; ans: CalcValue | null }

const UNIT_TYPES: ReadonlyArray<readonly [string, string, string, string]> = [
  ['length', 'Length', 'mm', 'in'],
  ['area', 'Area', 'm2', 'ft2'],
  ['volume', 'Volume', 'l', 'us gallon'],
  ['angle', 'Angle', 'deg', 'rad'],
];

const KEYS: ReadonlyArray<readonly [string, string]> = [
  ['sin', 'sin('], ['cos', 'cos('], ['tan', 'tan('], ['sqrt', 'sqrt('], ['(', '('], [')', ')'],
  ['7', '7'], ['8', '8'], ['9', '9'], ['/', '/'], ['pi', 'pi'], ['^', '^'],
  ['4', '4'], ['5', '5'], ['6', '6'], ['*', '*'], ['ans', 'ans'], ['log', 'log('],
  ['1', '1'], ['2', '2'], ['3', '3'], ['-', '-'], ['ln', 'ln('], ['abs', 'abs('],
  ['0', '0'], ['.', '.'], [',', ','], ['+', '+'], ['[ ]', '[,]'], ['e', 'e'],
];

function load(): Saved {
  try {
    const v = JSON.parse(stored(KEY) ?? '{}') as Partial<Saved>;
    return {
      history: Array.isArray(v.history) ? v.history.filter((h) => typeof h?.e === 'string' && typeof h.r === 'string').slice(0, HISTORY_MAX) : [],
      vars: v.vars && typeof v.vars === 'object' ? v.vars : {},
      ans: v.ans ?? null,
    };
  } catch {
    return { history: [], vars: {}, ans: null };
  }
}

function fold(title: string, open: boolean): { root: HTMLElement; body: HTMLElement } {
  const root = el<HTMLElement>(`<section class="pp-sec${open ? '' : ' is-collapsed'}"><button class="pp-sec-head" type="button" aria-expanded="${open}"><span class="pp-sec-chev">${icon('chevronDown', 12)}</span><span class="pp-sec-title"></span></button><div class="pp-sec-body"${open ? '' : ' hidden'}></div></section>`);
  setText(q(root, '.pp-sec-title'), title);
  const body = q(root, '.pp-sec-body');
  const head = q<HTMLButtonElement>(root, '.pp-sec-head');
  head.addEventListener('click', () => {
    const closed = !root.classList.contains('is-collapsed');
    root.classList.toggle('is-collapsed', closed);
    head.setAttribute('aria-expanded', String(!closed));
    setHidden(body, closed);
  });
  return { root, body };
}

const asValue = (r: CalcResult): CalcValue | null => {
  if (r.kind === 'number' && typeof r.value === 'number') return r.value;
  if (r.kind === 'point' && Array.isArray(r.value)) return [Number(r.value[0]), Number(r.value[1])];
  return null;
};

export function quickCalcPanel(): DockPanel {
  return {
    id: 'quickcalc',
    label: 'QuickCalc',
    icon: 'calculator',
    order: 30,
    build(body) {
      body.classList.add('qc');
      const saved = load();
      const persist = (): void => { store(KEY, JSON.stringify(saved)); };

      const field = el<HTMLElement>('<div class="qc-field"><input class="cv-input qc-input" type="text" spellcheck="false" autocomplete="off" placeholder="Expression" aria-label="Expression"><p class="qc-error" role="status"></p></div>');
      const input = q<HTMLInputElement>(field, 'input');
      const errorLine = q(field, '.qc-error');
      const actions = el<HTMLElement>('<div class="qc-actions"><button class="cv-btn cv-btn-primary" type="button" data-qc="eval">=</button><button class="cv-btn" type="button" data-qc="clear">Clear</button><button class="cv-btn" type="button" data-qc="paste">Paste to Command Line</button></div>');
      body.append(field, actions);

      const drawing = fold('Get from the Drawing', true);
      drawing.body.innerHTML = '<div class="qc-grid4"><button class="cv-btn" type="button" data-pick="point">Point</button><button class="cv-btn" type="button" data-pick="distance">Distance</button><button class="cv-btn" type="button" data-pick="angle">Angle</button><button class="cv-btn" type="button" data-pick="intersection">Intersection</button></div>';
      const pickButtons = Array.from(drawing.body.querySelectorAll<HTMLButtonElement>('[data-pick]'));

      const keypad = fold('Keypad', true);
      keypad.body.classList.add('qc-keys');
      for (const [label, text] of KEYS) {
        const b = el<HTMLButtonElement>('<button class="cv-btn qc-key" type="button"></button>');
        setText(b, label);
        b.dataset.ins = text;
        keypad.body.appendChild(b);
      }

      const hist = fold('History', true);
      const histList = el<HTMLElement>('<div class="qc-history"></div>');
      const histRows = Array.from({ length: HISTORY_SHOWN }, () => {
        const row = el<HTMLElement>('<div class="qc-hrow" hidden><button class="qc-hexp" type="button"></button><button class="qc-hres" type="button"></button></div>');
        histList.appendChild(row);
        return { row, exp: q<HTMLButtonElement>(row, '.qc-hexp'), res: q<HTMLButtonElement>(row, '.qc-hres') };
      });
      const histEmpty = el<HTMLElement>('<p class="pp-note">No calculations yet.</p>');
      const histClear = el<HTMLButtonElement>('<button class="cv-btn" type="button">Clear History</button>');
      hist.body.append(histList, histEmpty, histClear);

      const units = fold('Units Conversion', false);
      units.body.innerHTML = '<label class="cv-prop-row"><span>Type</span><select class="cv-input pp-in" data-u="type"></select></label><label class="cv-prop-row"><span>From</span><select class="cv-input pp-in" data-u="from"></select></label><label class="cv-prop-row"><span>To</span><select class="cv-input pp-in" data-u="to"></select></label><label class="cv-prop-row"><span>Value</span><input class="cv-input pp-in" type="text" data-numtext data-u="value" placeholder="1" aria-label="Value"></label><div class="qc-actions"><button class="cv-btn" type="button" data-u="go">Convert</button><button class="qc-uresult" type="button" data-u="result" hidden></button></div>';
      const uType = q<HTMLSelectElement>(units.body, '[data-u="type"]');
      const uFrom = q<HTMLSelectElement>(units.body, '[data-u="from"]');
      const uTo = q<HTMLSelectElement>(units.body, '[data-u="to"]');
      const uValue = q<HTMLInputElement>(units.body, '[data-u="value"]');
      const uResult = q<HTMLButtonElement>(units.body, '[data-u="result"]');
      setOptions(uType, UNIT_TYPES.map(([k, label]) => [k, label] as const));

      const vars = fold('Variables', false);
      const varList = el<HTMLElement>('<div class="qc-vars"></div>');
      const varAdd = el<HTMLElement>('<div class="qc-addvar"><input class="cv-input" type="text" data-v="name" placeholder="Name" aria-label="Variable name" spellcheck="false"><input class="cv-input" type="text" data-v="expr" placeholder="Expression" aria-label="Variable expression" spellcheck="false"><button class="cv-btn" type="button" data-v="add">Add</button></div>');
      const varError = el<HTMLElement>('<p class="qc-error" role="status"></p>');
      vars.body.append(varList, varAdd, varError);
      const vName = q<HTMLInputElement>(varAdd, '[data-v="name"]');
      const vExpr = q<HTMLInputElement>(varAdd, '[data-v="expr"]');
      body.append(drawing.root, keypad.root, hist.root, units.root, vars.root);

      let pending = false;
      let unitLists: Record<string, string[]> = {};

      const showError = (text: string): void => { setText(errorLine, text); };
      const textOf = (v: CalcValue): string => (Array.isArray(v) ? `${v[0]},${v[1]}` : String(v));
      const variables = (): Record<string, CalcValue> => ({ ...saved.vars, ...(saved.ans !== null ? { ans: saved.ans } : {}) });

      const paintHistory = (): void => {
        histRows.forEach((r, i) => {
          const h = saved.history[i];
          setHidden(r.row, !h);
          if (!h) return;
          setText(r.exp, h.e);
          setText(r.res, h.r);
          setTitle(r.exp, h.e);
          setTitle(r.res, h.r);
        });
        setHidden(histEmpty, saved.history.length > 0);
        setDisabled(histClear, saved.history.length === 0);
      };

      const paintVars = (): void => {
        const rows = Object.entries(saved.vars);
        const have = new Map(Array.from(varList.children).map((c) => [(c as HTMLElement).dataset.key ?? '', c as HTMLElement]));
        for (const [k, node] of have) if (!(k in saved.vars)) node.remove();
        for (const [name, value] of rows) {
          let node = have.get(name);
          if (!node) {
            node = el<HTMLElement>(`<div class="qc-var"><button class="qc-vuse" type="button"></button><button class="cv-icon-btn qc-vdel" type="button" aria-label="Delete variable">${icon('close', 12)}</button></div>`);
            node.dataset.key = name;
            q(node, '.qc-vuse').addEventListener('click', () => insert(name));
            q(node, '.qc-vdel').addEventListener('click', () => { delete saved.vars[name]; persist(); paintVars(); });
            varList.appendChild(node);
          }
          setText(q(node, '.qc-vuse'), `${name} = ${textOf(value)}`);
        }
      };

      const insert = (text: string): void => {
        const start = input.selectionStart ?? input.value.length, end = input.selectionEnd ?? start;
        const caretBack = text === '[,]' ? 2 : 0;
        input.value = input.value.slice(0, start) + text + input.value.slice(end);
        const at = start + text.length - caretBack;
        input.focus();
        input.setSelectionRange(at, at);
      };

      const append = (text: string): void => {
        input.value = input.value.trim() === '' || !ENDS_OPEN.test(input.value) ? text : input.value.replace(/\s+$/, '') + text;
        input.focus();
      };

      const record = (e: string, r: string): void => {
        saved.history = [{ e, r }, ...saved.history].slice(0, HISTORY_MAX);
        persist();
        paintHistory();
      };

      const solve = async (expression: string): Promise<CalcResult> => {
        const doc = docStore.activeId ?? undefined;
        const picks: unknown[] = [];
        for (let round = 0; round < 8; round++) {
          const r = await api.calc({ expression, variables: variables(), picks, docId: doc });
          if (r.ok || !r.needsPick) return r;
          const got = await runPick('point');
          if (!got) return { ok: false, error: 'CAL: pick cancelled' };
          picks.push(got.value);
        }
        return { ok: false, error: 'CAL: too many picks' };
      };

      const evaluate = async (): Promise<void> => {
        const raw = input.value.trim();
        if (!raw) return;
        const m = /^([A-Za-z]\w*)\s*=\s*(.+)$/.exec(raw);
        const expression = m ? m[2] : raw;
        try {
          const r = await solve(expression);
          if (!r.ok) { showError(r.error ?? 'The expression could not be evaluated.'); return; }
          showError('');
          const v = asValue(r);
          if (v === null) return;
          saved.ans = v;
          if (m) {
            const name = m[1];
            if (RESERVED.has(name.toLowerCase())) { showError(`CAL: ${name} is reserved.`); return; }
            if (!(name in saved.vars) && Object.keys(saved.vars).length >= VARIABLES_MAX) { showError('CAL: at most 50 variables.'); return; }
            saved.vars[name] = v;
            paintVars();
          }
          record(raw, r.text ?? textOf(v));
          input.value = r.text ?? textOf(v);
          input.focus();
          input.select();
        } catch (e) {
          showError(failure(e));
        }
      };

      const runPick = async (mode: string): Promise<{ value: CalcValue; text: string } | null> => {
        const doc = docStore.activeId;
        if (!doc) { showError('Open a drawing first.'); return null; }
        pending = true;
        syncButtons();
        const publish = (state: CommandLineState): void => { document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc, state } })); };
        try {
          const first = await api.sendInput(doc, 'quickcalc.pick');
          publish(first);
          if (!first.active) return null;
          const second = await api.sendInput(doc, mode);
          publish(second);
          if (!second.active) return null;
          const last = await new Promise<CommandLineState | null>((resolve) => {
            const onState = (e: Event): void => {
              const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
              if (d.doc !== doc || d.state.active) return;
              document.removeEventListener('formcad:command-state', onState);
              document.removeEventListener('formcad:cmdline-applied', onState);
              resolve(d.state);
            };
            document.addEventListener('formcad:command-state', onState);
            document.addEventListener('formcad:cmdline-applied', onState);
          });
          const line = last?.history[last.history.length - 1]?.trim() ?? '';
          if (!/^[-+]?[\d.]/.test(line)) return null;
          const parts = line.split(',').map(Number);
          if (parts.some((n) => !Number.isFinite(n))) return null;
          return { value: parts.length === 1 ? parts[0] : [parts[0], parts[1]], text: line };
        } catch (e) {
          showError(failure(e));
          return null;
        } finally {
          pending = false;
          syncButtons();
        }
      };

      function syncButtons(): void {
        const off = pending || !docStore.activeId;
        for (const b of pickButtons) setDisabled(b, off);
      }

      const convert = async (): Promise<void> => {
        const raw = uValue.value.trim();
        const value = raw === '' ? 1 : Number(raw);
        if (!Number.isFinite(value)) { toast('Not a number: ' + raw, 'error'); return; }
        try {
          const r = await api.calc({ convert: { value, from: uFrom.value, to: uTo.value, type: uType.value } });
          if (!r.ok) { setHidden(uResult, true); toast(r.error ?? 'The conversion failed.', 'error'); return; }
          setText(uResult, `${r.text} ${uTo.value}`);
          uResult.dataset.value = r.text ?? '';
          setHidden(uResult, false);
        } catch (e) {
          toast(failure(e), 'error');
        }
      };

      const fillUnits = async (): Promise<void> => {
        const kind = uType.value || 'length';
        if (!unitLists[kind]) {
          try {
            const r = await api.calc({ units: kind });
            unitLists = { ...unitLists, ...Object.fromEntries(Object.entries(r.units ?? {}).map(([k, v]) => [k, Array.isArray(v) ? (v as unknown as string[]) : Object.keys(v)])) };
          } catch (e) {
            toast(failure(e), 'error');
            return;
          }
        }
        const names = unitLists[kind] ?? [];
        const def = UNIT_TYPES.find((u) => u[0] === kind);
        setOptions(uFrom, names.map((n) => [n, n] as const));
        setOptions(uTo, names.map((n) => [n, n] as const));
        if (def) { uFrom.value = def[2]; uTo.value = def[3]; }
        setHidden(uResult, true);
      };

      actions.addEventListener('click', (e) => {
        const kind = (e.target as HTMLElement).closest<HTMLElement>('[data-qc]')?.dataset.qc;
        if (kind === 'eval') void evaluate();
        else if (kind === 'clear') { input.value = ''; showError(''); input.focus(); }
        else if (kind === 'paste') {
          const cmd = document.querySelector<HTMLInputElement>('.cv-cmd-input');
          const text = input.value.trim().replace(/^\[|\]$/g, '');
          if (!cmd || !text) return;
          cmd.value = text;
          document.dispatchEvent(new CustomEvent('formcad:cmdline-text'));
          cmd.focus();
        }
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); void evaluate(); }
        else if (e.key === 'Escape') { input.blur(); }
      });
      keypad.body.addEventListener('click', (e) => {
        const t = (e.target as HTMLElement).closest<HTMLElement>('[data-ins]')?.dataset.ins;
        if (t) insert(t);
      });
      drawing.body.addEventListener('click', (e) => {
        const mode = (e.target as HTMLElement).closest<HTMLElement>('[data-pick]')?.dataset.pick;
        if (!mode || pending) return;
        void runPick(mode).then((got) => {
          if (!got) return;
          append(Array.isArray(got.value) ? `[${got.text}]` : got.text);
        });
      });
      histList.addEventListener('click', (e) => {
        const t = e.target as HTMLElement;
        const idx = histRows.findIndex((r) => r.exp === t || r.res === t);
        if (idx < 0) return;
        const h = saved.history[idx];
        input.value = t.classList.contains('qc-hexp') ? h.e : h.r;
        input.focus();
      });
      histClear.addEventListener('click', () => { saved.history = []; persist(); paintHistory(); });
      uType.addEventListener('change', () => { void fillUnits(); });
      units.body.addEventListener('click', (e) => {
        const t = (e.target as HTMLElement).closest<HTMLElement>('[data-u]')?.dataset.u;
        if (t === 'go') void convert();
        else if (t === 'result' && uResult.dataset.value) append(uResult.dataset.value);
      });
      uValue.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void convert(); } });
      varAdd.addEventListener('click', (e) => {
        if (!(e.target as HTMLElement).closest('[data-v="add"]')) return;
        void addVariable();
      });
      for (const f of [vName, vExpr]) f.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void addVariable(); } });

      async function addVariable(): Promise<void> {
        const name = vName.value.trim();
        if (!NAME.test(name)) { setText(varError, 'A name starts with a letter and holds letters, digits and underscores.'); return; }
        if (RESERVED.has(name.toLowerCase())) { setText(varError, `${name} is reserved.`); return; }
        if (!(name in saved.vars) && Object.keys(saved.vars).length >= VARIABLES_MAX) { setText(varError, 'At most 50 variables.'); return; }
        try {
          const r = await solve(vExpr.value.trim());
          const v = r.ok ? asValue(r) : null;
          if (v === null) { setText(varError, r.error ?? 'The value must be a number or a point.'); return; }
          saved.vars[name] = v;
          persist();
          paintVars();
          setText(varError, '');
          vName.value = '';
          vExpr.value = '';
        } catch (e) {
          setText(varError, failure(e));
        }
      }

      document.addEventListener('formcad:quickcalc-focus', () => {
        if (body.offsetParent !== null) { input.focus(); input.select(); }
      });
      docStore.onChange(syncButtons);
      paintHistory();
      paintVars();
      syncButtons();
      void fillUnits();
    },
  };
}

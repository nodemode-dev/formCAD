import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, checkCtl, numberCtl, readout, selectCtl, type Ctl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { charWord, PmiLayer, type PmiDraw } from './pmi-layer';
import { docUrl, num, reportBox, req, section, text, type Json } from './kit';

interface Ref { kind: 'face' | 'edge'; pid: number }
interface Item extends Json { id: string; type: string; label?: string; state?: string; body?: number; refs?: Ref[]; refs2?: Ref[]; measured?: number | null }

const KINDS: ReadonlyArray<readonly [string, string]> = [['dimension', 'Dimension'], ['tolerance', 'Tolerance frame'], ['datum', 'Datum']];
const DTYPES: ReadonlyArray<readonly [string, string]> = [['distance', 'Distance'], ['diameter', 'Diameter'], ['radius', 'Radius'], ['thickness', 'Thickness'], ['angle', 'Angle']];
const CHARS = ['straightness', 'flatness', 'circularity', 'cylindricity', 'profile_line', 'profile_surface', 'parallelism', 'perpendicularity', 'angularity', 'position', 'concentricity', 'symmetry', 'runout', 'total_runout'];
const ZONES: ReadonlyArray<readonly [string, string]> = [['none', 'Plain'], ['diameter', 'Diameter zone'], ['sphere', 'Spherical zone']];
const MODS: ReadonlyArray<readonly [string, string]> = [['', 'None'], ['M', 'Maximum material'], ['L', 'Least material']];
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
const TWO_FEATURES = new Set(['distance', 'angle']);

export let pmiLayer: PmiLayer | null = null;
let showNotes = true;
let pullDisplay: (() => void) | null = null;

export function attachPmi(vp: import('../view3d/viewport').Viewport3D): void {
  if (pmiLayer) return;
  pmiLayer = new PmiLayer(vp);
  vp.addLayer(pmiLayer);
  pullDisplay?.();
}

function flatten(prefix: string, v: unknown, out: string[]): void {
  if (v === null || v === undefined) return;
  if (Array.isArray(v)) { for (const x of v) { if (typeof x === 'object') flatten(prefix, x, out); else out.push(`${prefix ? `${prefix}: ` : ''}${String(x)}`); } return; }
  if (typeof v === 'object') { for (const [k, x] of Object.entries(v as Json)) flatten(k.replace(/_/g, ' '), x, out); return; }
  out.push(`${prefix ? `${prefix}: ` : ''}${String(v)}`);
}

export function pmiPanel(): DockPanel {
  return {
    id: 'pmi',
    label: 'Model Notes',
    icon: 'pmiDim',
    order: 43,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      let items: Item[] = [];
      let datums: string[] = [];
      let reports: Json = {};
      let editing: string | null = null;
      let refA: Ref[] = [];
      let refB: Ref[] = [];
      let bodyHandle: number | null = null;

      const sList = section('Notes in this part');
      const list = el('<div class="u8-list xw-pmilist is-scroll" role="listbox" aria-label="Model notes"></div>');
      const empty = el('<p class="u8-note xw-empty"></p>');
      setText(empty, t('No notes yet. Pick faces or edges in the view and add one below.'));
      const show = checkCtl('Show notes in the view', showNotes, () => { showNotes = show.get(); paintLayer(); });
      sList.body.append(list, empty, show.el);

      const sForm = section('New note');
      const kind = selectCtl('Kind', KINDS, () => formSync());
      const dtype = selectCtl('Measures', DTYPES, () => { formSync(); void measure(); });
      const featA = readout('Feature');
      const featB = readout('Second feature');
      const useA = button('Use selection', () => capture('a'));
      const useB = button('Use selection as second', () => capture('b'));
      const value = numberCtl('Value (blank: measured)', 0);
      value.set(null);
      const measured = readout('Measured');
      const plus = numberCtl('Plus', 0);
      const minus = numberCtl('Minus', 0);
      const char = selectCtl('Characteristic', CHARS.map((c) => [c, charWord(c)] as const));
      const tol = numberCtl('Zone width', 0.05);
      const zone = selectCtl('Zone', ZONES);
      const modifier = selectCtl('Modifier', MODS);
      const d1 = selectCtl('Primary datum', [['', 'None']]);
      const d2 = selectCtl('Secondary datum', [['', 'None']]);
      const d3 = selectCtl('Tertiary datum', [['', 'None']]);
      const letter = selectCtl('Letter', LETTERS.map((l) => [l, l] as const));
      const noteText = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(noteText, 'span'), t('Note text'));
      const textIn = q<HTMLInputElement>(noteText, 'input');
      const form = el('<div class="xw-form"></div>');
      const rows: Array<[HTMLElement, (k: string, d: string) => boolean]> = [
        [dtype.el, (k) => k === 'dimension'],
        [value.el, (k) => k === 'dimension'],
        [measured.el, (k) => k === 'dimension'],
        [plus.el, (k) => k === 'dimension'],
        [minus.el, (k) => k === 'dimension'],
        [char.el, (k) => k === 'tolerance'],
        [tol.el, (k) => k === 'tolerance'],
        [zone.el, (k) => k === 'tolerance'],
        [modifier.el, (k) => k === 'tolerance'],
        [d1.el, (k) => k === 'tolerance'],
        [d2.el, (k) => k === 'tolerance'],
        [d3.el, (k) => k === 'tolerance'],
        [letter.el, (k) => k === 'datum'],
        [featB.el, (k, d) => k === 'dimension' && TWO_FEATURES.has(d)],
        [useB, (k, d) => k === 'dimension' && TWO_FEATURES.has(d)],
      ];
      form.append(kind.el, featA.el, useA, dtype.el, featB.el, useB, value.el, measured.el, plus.el, minus.el, char.el, tol.el, zone.el, modifier.el, d1.el, d2.el, d3.el, letter.el, noteText);
      const out = reportBox(3);
      const add = button('Add note', () => void commit(), 'primary');
      const cancel = button('Cancel edit', () => stopEdit());
      sForm.body.append(form, buttons(add, cancel), out.el);

      const sRep = section('Last file report');
      const repBox = reportBox(8);
      sRep.body.append(repBox.el);

      body.append(sList.root, sForm.root, sRep.root);

      const refText = (r: Ref[]): string => (r.length ? r.map((x) => `${x.kind} ${x.pid}`).join(', ') : '-');
      const ctls: Array<Ctl<string>> = [d1, d2, d3];

      function formSync(): void {
        const k = kind.get();
        const d = dtype.get();
        for (const [row, on] of rows) setHidden(row, !on(k, d));
        setText(add, editing ? t('Update note') : t('Add note'));
        setHidden(cancel, !editing);
        featA.set(refText(refA));
        featB.set(refText(refB));
        for (const c of ctls) {
          const sel = c.input as HTMLSelectElement;
          const want = ['', ...datums];
          const have = Array.from(sel.options).map((o) => o.value);
          if (want.join('|') !== have.join('|')) {
            const keep = sel.value;
            sel.replaceChildren(...want.map((v) => { const o = document.createElement('option'); o.value = v; o.textContent = v === '' ? t('None') : v; return o; }));
            sel.value = want.includes(keep) ? keep : '';
          }
        }
      }

      function selection(): { refs: Ref[]; body: number | null } {
        const vp = view3d()?.vp;
        if (!vp) return { refs: [], body: null };
        const faces = vp.sel.faces.map((f) => ({ kind: 'face' as const, pid: f.face, body: f.body }));
        const edges = vp.sel.edges.map((e) => ({ kind: 'edge' as const, pid: e.edge, body: e.body }));
        const all = [...faces, ...edges];
        return { refs: all.map((a) => ({ kind: a.kind, pid: a.pid })), body: all.length ? all[0].body : null };
      }

      function capture(which: 'a' | 'b'): void {
        const s = selection();
        if (!s.refs.length) { toast(t('Select a face or an edge in the view first.'), 'info'); return; }
        const wantMany = kind.get() === 'tolerance' && which === 'a';
        const picked = wantMany ? s.refs : s.refs.slice(0, 1);
        if (which === 'a') { refA = picked; bodyHandle = s.body; } else refB = picked;
        formSync();
        void measure();
      }

      async function measure(): Promise<void> {
        const id = docStore.activeId;
        if (!id || kind.get() !== 'dimension' || bodyHandle === null || !refA.length) { measured.set('-'); return; }
        if (TWO_FEATURES.has(dtype.get()) && !refB.length) { measured.set('-'); return; }
        try {
          const r = await req<Json>('POST', docUrl(id, 'pmi/measure'), { body: bodyHandle, dtype: dtype.get(), refs: refA, refs2: refB });
          measured.set(`${num(r.value)} ${String(r.unit ?? '')}`.trim());
        } catch (e) { measured.set(text(e)); }
      }

      function stopEdit(): void {
        editing = null;
        refA = []; refB = [];
        pmiLayer?.highlight('');
        formSync();
        paintList();
      }

      function record(): Json | null {
        const k = kind.get();
        if (bodyHandle === null || !refA.length) { out.set([t('Pick the feature in the view and use the selection first.')], true); return null; }
        const base: Json = { type: k, body: bodyHandle, refs: refA, text: textIn.value.trim() };
        if (k === 'dimension') {
          if (TWO_FEATURES.has(dtype.get()) && !refB.length) { out.set([t('This measure needs a second feature.')], true); return null; }
          return { ...base, dtype: dtype.get(), refs2: TWO_FEATURES.has(dtype.get()) ? refB : [], value: value.get(), plus: Math.max(0, plus.get() ?? 0), minus: Math.max(0, minus.get() ?? 0) };
        }
        if (k === 'tolerance') {
          const t0 = tol.get();
          if (t0 === null || t0 <= 0) { out.set([t('The zone width must be above zero.')], true); return null; }
          return { ...base, char: char.get(), tol: t0, zone: zone.get(), modifier: modifier.get(), datums: ctls.map((c) => c.get()).filter(Boolean) };
        }
        return { ...base, letter: letter.get() };
      }

      async function commit(): Promise<void> {
        const id = docStore.activeId;
        const rec = record();
        if (!id || !rec) return;
        out.set([`${t('Saving')}...`]);
        try {
          if (editing) {
            const { type: _t, body: _b, ...changes } = rec;
            void _t; void _b;
            await req('PATCH', docUrl(id, `pmi/${editing}`), changes);
          } else await req('POST', docUrl(id, 'pmi'), rec);
          out.set([editing ? t('Note updated.') : t('Note added.')]);
          stopEdit();
          await refresh();
        } catch (e) { out.set([text(e)], true); }
      }

      function edit(it: Item): void {
        editing = it.id;
        kind.set(it.type);
        bodyHandle = typeof it.body === 'number' ? it.body : null;
        refA = (it.refs ?? []).map((r) => ({ kind: r.kind, pid: r.pid }));
        refB = (it.refs2 ?? []).map((r) => ({ kind: r.kind, pid: r.pid }));
        if (typeof it.dtype === 'string') dtype.set(it.dtype);
        value.set(typeof it.value === 'number' ? it.value : null);
        plus.set(num(it.plus)); minus.set(num(it.minus));
        if (typeof it.char === 'string') char.set(it.char);
        tol.set(num(it.tol, 0.05));
        if (typeof it.zone === 'string') zone.set(it.zone);
        modifier.set(typeof it.modifier === 'string' ? it.modifier : '');
        formSync();
        const ds = Array.isArray(it.datums) ? (it.datums as string[]) : [];
        ctls.forEach((c, i) => c.set(ds[i] ?? ''));
        if (typeof it.letter === 'string') letter.set(it.letter);
        textIn.value = typeof it.text === 'string' ? it.text : '';
        pmiLayer?.highlight(it.id);
        void measure();
        paintList();
      }

      async function remove(it: Item): Promise<void> {
        const id = docStore.activeId;
        if (!id) return;
        try { await req('DELETE', docUrl(id, `pmi/${it.id}`)); if (editing === it.id) stopEdit(); await refresh(); } catch (e) { toast(text(e), 'error'); }
      }

      function paintList(): void {
        patchList(list, items, {
          key: (i) => i.id,
          create: (i) => {
            const row = el(`<div class="u8-row xw-pmirow" role="option"><span class="u8-row-name"></span><span class="u8-badge"></span><button class="u8-mini" type="button" aria-label="Delete">${icon('delete', 12)}</button></div>`);
            row.addEventListener('click', (ev) => { if ((ev.target as HTMLElement).closest('button')) return; const cur = items.find((x) => x.id === i.id); if (cur) edit(cur); });
            q(row, 'button').addEventListener('click', () => { const cur = items.find((x) => x.id === i.id); if (cur) void remove(cur); });
            return row;
          },
          update: (node, i) => {
            setText(q(node, '.u8-row-name'), i.label || i.id);
            const badge = q(node, '.u8-badge');
            setText(badge, i.state === 'lost' ? t('lost') : i.state === 'unsupported' ? t('unsupported') : i.type);
            badge.dataset.s = i.state === 'lost' ? 'missing' : i.state === 'unsupported' ? 'outofdate' : 'loaded';
            setClass(node, 'is-selected', editing === i.id);
          },
        });
        setHidden(empty, items.length > 0);
        setText(empty, items.length ? '' : t('No notes yet. Pick faces or edges in the view and add one below.'));
      }

      function paintReports(): void {
        const lines: string[] = [];
        const w = reports.write as Json | undefined;
        const r = reports.read as Json | undefined;
        if (w) { lines.push(t('Written')); flatten('', w, lines); }
        if (r) { lines.push(t('Read back')); flatten('', r, lines); }
        repBox.set(lines.length ? lines : [t('No file has been written or read yet.')]);
      }

      async function pullDisplayNow(): Promise<void> {
        const id = docStore.activeId;
        if (!id || !pmiLayer) return;
        try {
          const d = await req<{ items: PmiDraw[] }>('GET', docUrl(id, 'pmi/display'));
          pmiLayer.set(d.items, showNotes);
        } catch { pmiLayer.set([], false); }
      }
      function paintLayer(): void { void pullDisplayNow(); }
      pullDisplay = paintLayer;

      async function refresh(): Promise<void> {
        const id = docStore.activeId;
        if (!id) { items = []; datums = []; reports = {}; paintList(); paintReports(); formSync(); return; }
        try {
          const r = await req<{ items: Item[]; datums: string[]; reports: Json }>('GET', docUrl(id, 'pmi'));
          items = r.items;
          datums = r.datums;
          reports = r.reports ?? {};
          const used = new Set(datums);
          const free = LETTERS.find((l) => !used.has(l)) ?? 'A';
          if (!editing && used.has(letter.get())) letter.set(free);
        } catch { items = []; }
        paintList();
        paintReports();
        formSync();
        await pullDisplayNow();
        setDisabled(add, false);
      }

      let timer = 0;
      const later = (): void => { window.clearTimeout(timer); timer = window.setTimeout(() => { void refresh(); }, 150); };
      events.on('doc', (e) => { if (e.id === docStore.activeId) later(); });
      docStore.onChange(later);
      formSync();
      later();
      return { show: later };
    },
  };
}

import { drawingCanvas } from '../../canvas/mount';
import { api, type PropertiesPayload, type PropertyField } from '../../io/api';
import { commands } from '../commands';
import type { DockPanel } from '../dock';
import { docStore } from '../doc-store';
import { el, q, setClass, setHidden, setText, setTitle } from '../dom';
import { icon } from '../icons';
import { PopupMenu } from '../menu';
import { sysvars } from '../sysvar-store';
import { toast } from '../toast';
import { runEngineText } from './engine-run';
import { properties } from './property-store';
import type { PropRow } from './prop-rows';
import { GENERAL, KIND_BY_NAME, KINDS, kindTitle, type RowDef } from './props-kinds';
import { buildRow } from './row-factory';
import { selection } from './selection-bus';

export interface TableNames {
  layers: string[];
  linetypes: string[];
  textstyles: string[];
  dimstyles: string[];
  mleaderstyles: string[];
  tablestyles: string[];
}

interface Block {
  root: HTMLElement;
  title: HTMLElement;
  body: HTMLElement;
  rows: Array<{ def: RowDef; row: PropRow }>;
}

interface CurrentRow {
  id: string;
  row: PropRow;
  field(t: TableNames): PropertyField;
}

const NOW = (): number => Math.min(8, Math.max(0, sysvars.num('LUPREC', 4)));
const ANGLE_NAMES = ['ByLayer', 'ByBlock'];

function block(title: string, defs: RowDef[], commit: (def: RowDef) => (v: unknown) => void): Block {
  const root = el<HTMLElement>('<section class="pp-sec"><button class="pp-sec-head" type="button" aria-expanded="true"></button><div class="pp-sec-body"></div></section>');
  const head = q<HTMLButtonElement>(root, '.pp-sec-head');
  head.innerHTML = `<span class="pp-sec-chev">${icon('chevronDown', 12)}</span><span class="pp-sec-title"></span>`;
  const label = q(head, '.pp-sec-title');
  setText(label, title);
  const body = q(root, '.pp-sec-body');
  const rows = defs.map((def) => ({ def, row: buildRow(def, commit(def), NOW) }));
  for (const r of rows) body.appendChild(r.row.el);
  head.addEventListener('click', () => {
    const closed = !root.classList.contains('is-collapsed');
    setClass(root, 'is-collapsed', closed);
    head.setAttribute('aria-expanded', String(!closed));
    setHidden(body, closed);
  });
  return { root, title: label, body, rows };
}

const lwOf = (v: unknown): string | number => {
  const n = Number(v);
  return n === -1 ? 'ByLayer' : n === -2 ? 'ByBlock' : n === -3 ? 'Default' : Math.round(n) / 100;
};

function currentRows(): CurrentRow[] {
  const sv = (name: string, fallback: unknown): unknown => sysvars.get(name) ?? fallback;
  const field = (value: unknown, options: unknown[] | undefined, type: string, readonly = false): PropertyField => ({ value, varies: false, type, readonly, options });
  const set = (name: string) => (v: unknown): void => { void sysvars.set(name, v); };
  const list: Array<{ id: string; def: RowDef; commit: (v: unknown) => void; field(t: TableNames): PropertyField }> = [
    { id: 'color', def: { id: 'color', label: 'Color', type: 'color', show: () => undefined }, commit: (v) => { void sysvars.set('CECOLOR', v === 'ByLayer' ? 256 : v === 'ByBlock' ? 0 : v); }, field: () => field(Number(sv('CECOLOR', 256)) === 256 ? 'ByLayer' : Number(sv('CECOLOR', 256)) === 0 ? 'ByBlock' : sv('CECOLOR', 256), undefined, 'color') },
    { id: 'layer', def: { id: 'layer', label: 'Layer', type: 'choice', show: () => undefined }, commit: set('CLAYER'), field: (t) => field(sv('CLAYER', '0'), t.layers, 'string') },
    { id: 'linetype', def: { id: 'linetype', label: 'Linetype', type: 'choice', show: () => undefined }, commit: set('CELTYPE'), field: (t) => field(sv('CELTYPE', 'ByLayer'), t.linetypes, 'string') },
    { id: 'ltscale', def: { id: 'ltscale', label: 'Linetype scale', type: 'number', show: () => undefined }, commit: set('CELTSCALE'), field: () => field(Number(sv('CELTSCALE', 1)), undefined, 'number') },
    { id: 'lineweight', def: { id: 'lineweight', label: 'Lineweight', type: 'lineweight', show: () => undefined }, commit: (v) => { void sysvars.set('CELWEIGHT', v === 'ByLayer' ? -1 : v === 'ByBlock' ? -2 : v === 'Default' ? -3 : Math.round(Number(v) * 100)); }, field: () => field(lwOf(sv('CELWEIGHT', -1)), [...ANGLE_NAMES, 'Default', 0, 0.05, 0.09, 0.13, 0.15, 0.18, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.53, 0.6, 0.7, 0.8, 0.9, 1, 1.06, 1.2, 1.4, 1.58, 2, 2.11], 'lineweight') },
    { id: 'transparency', def: { id: 'transparency', label: 'Transparency', type: 'text', show: () => undefined }, commit: () => undefined, field: () => field('ByLayer', undefined, 'string', true) },
    { id: 'thickness', def: { id: 'thickness', label: 'Thickness', type: 'number', show: () => undefined }, commit: set('THICKNESS'), field: () => field(Number(sv('THICKNESS', 0)), undefined, 'number') },
    { id: 'textstyle', def: { id: 'textstyle', label: 'Text style', type: 'choice', show: () => undefined }, commit: set('TEXTSTYLE'), field: (t) => field(sv('TEXTSTYLE', 'Standard'), t.textstyles, 'string') },
    { id: 'dimstyle', def: { id: 'dimstyle', label: 'Dimension style', type: 'choice', show: () => undefined }, commit: set('DIMSTYLE'), field: (t) => field(sv('DIMSTYLE', 'Standard'), t.dimstyles, 'string') },
    { id: 'mleaderstyle', def: { id: 'mleaderstyle', label: 'Multileader style', type: 'choice', show: () => undefined }, commit: set('CMLEADERSTYLE'), field: (t) => field(sv('CMLEADERSTYLE', 'Standard'), t.mleaderstyles, 'string') },
    { id: 'tablestyle', def: { id: 'tablestyle', label: 'Table style', type: 'choice', show: () => undefined }, commit: set('CTABLESTYLE'), field: (t) => field(sv('CTABLESTYLE', 'Standard'), t.tablestyles, 'string') },
    { id: 'annoscale', def: { id: 'annoscale', label: 'Annotation scale', type: 'text', show: () => undefined }, commit: () => undefined, field: () => field(sv('CANNOSCALE', '1:1'), undefined, 'string', true) },
    { id: 'textheight', def: { id: 'textheight', label: 'Text height', type: 'number', show: () => undefined }, commit: set('TEXTSIZE'), field: () => field(Number(sv('TEXTSIZE', 2.5)), undefined, 'number') },
    { id: 'plotstyle', def: { id: 'plotstyle', label: 'Plot style', type: 'text', show: () => undefined }, commit: () => undefined, field: () => field('ByColor', undefined, 'string', true) },
    { id: 'plottable', def: { id: 'plottable', label: 'Plot style table', type: 'text', show: () => undefined }, commit: () => undefined, field: () => field('None', undefined, 'string', true) },
    { id: 'plotattached', def: { id: 'plotattached', label: 'Plot style attached to', type: 'text', show: () => undefined }, commit: () => undefined, field: () => field('Model', undefined, 'string', true) },
    { id: 'plottype', def: { id: 'plottype', label: 'Plot table type', type: 'text', show: () => undefined }, commit: () => undefined, field: () => field('Not available', undefined, 'string', true) },
  ];
  return list.map((x) => ({ id: x.id, row: buildRow(x.def, x.commit, NOW), field: x.field }));
}

export function propertiesPanel(): DockPanel {
  return {
    id: 'properties',
    label: 'Properties',
    icon: 'properties',
    order: 5,
    grow: true,
    build(body) {
      body.classList.add('pp');
      const head = el<HTMLElement>(
        '<div class="pp-head"><div class="pp-seg" role="group" aria-label="Palette filter"><button class="pp-seg-btn is-on" type="button" aria-pressed="true">All</button><button class="pp-seg-btn" type="button" disabled aria-pressed="false">My</button></div>' +
        '<div class="pp-pick"><button class="pp-type" type="button" aria-haspopup="listbox"><span class="pp-type-label"></span></button>' +
        `<button class="cv-icon-btn pp-tool" type="button" data-pp="pickadd">${icon('plus', 14)}</button>` +
        `<button class="cv-icon-btn pp-tool" type="button" data-pp="select">${icon('select', 14)}</button>` +
        `<button class="cv-icon-btn pp-tool" type="button" data-pp="quick">${icon('quickSelect', 14)}</button></div></div>`);
      const scroll = el<HTMLElement>('<div class="pp-scroll"></div>');
      const empty = el<HTMLElement>('<p class="pp-note"></p>');
      body.append(head, scroll);

      const typeBtn = q<HTMLButtonElement>(head, '.pp-type');
      const typeLabel = q(head, '.pp-type-label');
      const pickAdd = q<HTMLButtonElement>(head, '[data-pp="pickadd"]');
      const selectBtn = q<HTMLButtonElement>(head, '[data-pp="select"]');
      const quickBtn = q<HTMLButtonElement>(head, '[data-pp="quick"]');
      setTitle(q(head, '.pp-seg-btn[disabled]'), 'Not available yet');
      setTitle(selectBtn, 'Select objects');
      setTitle(quickBtn, 'Quick Select');
      selectBtn.setAttribute('aria-label', 'Select objects');
      quickBtn.setAttribute('aria-label', 'Quick Select');
      pickAdd.setAttribute('aria-label', 'Toggle PICKADD');

      const pop = el<HTMLElement>('<div class="pp-type-pop cv-dd-pop" role="listbox" hidden><div class="cv-dd-list"></div></div>');
      const popList = q(pop, '.cv-dd-list');
      document.getElementById('overlay-root')?.appendChild(pop);

      let view: PropertiesPayload | null = null;
      let counts = new Map<string, number>();
      let filter: string | null = null;
      let tables: TableNames = { layers: [], linetypes: [], textstyles: [], dimstyles: [], mleaderstyles: [], tablestyles: [] };
      let tablesDoc = '';
      let seq = 0;

      const edit = (scope: string) => (def: RowDef) => (value: unknown): void => {
        const refusal = properties.editRow(view, scope, def, value);
        if (refusal) { toast(refusal, 'info'); paint(); }
      };

      const general = block('General', GENERAL, edit('general'));
      const current = block('Current settings', [], () => () => undefined);
      current.root.classList.add('pp-current');
      const curRows = currentRows();
      for (const r of curRows) current.body.appendChild(r.row.el);
      setText(current.title, 'Current settings');
      const kindBlocks = new Map<string, Block>();
      const makeKind = (kind: string): Block => {
        const spec = KIND_BY_NAME.get(kind);
        const b = block(spec?.title ?? kindTitle(kind), spec?.rows ?? [], edit(kind));
        b.root.dataset.kind = kind;
        setHidden(b.root, true);
        kindBlocks.set(kind, b);
        return b;
      };
      scroll.append(current.root, general.root);
      for (const k of KINDS) scroll.appendChild(makeKind(k.kind).root);
      scroll.appendChild(empty);
      setHidden(general.root, true);

      const items = new Map<string, HTMLButtonElement>();
      const makeItem = (key: string): HTMLButtonElement => {
        const b = el<HTMLButtonElement>(`<button class="cv-dd-item" type="button" role="option" data-value="${key}"><span></span>${icon('check', 14)}</button>`);
        b.addEventListener('click', () => {
          filter = key === '*' ? null : key;
          setHidden(pop, true);
          void refresh();
        });
        setHidden(b, true);
        popList.appendChild(b);
        items.set(key, b);
        return b;
      };
      makeItem('*');
      for (const k of KINDS) makeItem(k.kind);

      const loadTables = async (): Promise<void> => {
        const doc = docStore.activeId;
        if (!doc) return;
        try {
          const s = await api.snapshot(doc, 2147483647);
          const names = (key: string): string[] => ((s.tables[key] as Array<{ name: string }> | undefined) ?? []).map((r) => r.name);
          tables = { layers: names('layers'), linetypes: names('linetypes'), textstyles: names('textstyles'), dimstyles: names('dimstyles'), mleaderstyles: names('mleaderstyles'), tablestyles: names('tablestyles') };
          tablesDoc = `${doc}:${s.rev}`;
        } catch {
          return;
        }
        paint();
      };

      const refresh = async (): Promise<void> => {
        const mine = ++seq;
        const base = properties.payload;
        if (!base || !base.count) {
          view = null;
          counts = new Map();
          filter = null;
          paint();
          return;
        }
        counts = new Map(Object.entries(base.kinds).map(([k, v]) => [k, v.count]));
        let next = base;
        if (filter && base.kinds[filter]) {
          try {
            next = await api.properties(properties.doc ?? docStore.activeId ?? '', base.kinds[filter].handles);
          } catch {
            next = base;
          }
          if (mine !== seq) return;
        } else filter = null;
        view = next;
        paint();
      };

      const label = (kind: string, n: number): string => `${kindTitle(kind)}${n > 1 ? ` (${n})` : ''}`;

      function paint(): void {
        const p = view;
        const has = !!p && p.count > 0;
        setHidden(current.root, has);
        setHidden(general.root, !has);
        if (!has || !p) {
          for (const b of kindBlocks.values()) setHidden(b.root, true);
          setText(typeLabel, 'No selection');
          setHidden(empty, true);
          const t = tables;
          for (const r of curRows) r.row.paint(r.field(t));
          return;
        }
        for (const r of general.rows) r.row.paint(r.def.show(p.general));
        const total = Array.from(counts.values()).reduce((a, b) => a + b, 0);
        for (const kind of Object.keys(p.kinds)) if (!kindBlocks.has(kind)) { const b = makeKind(kind); scroll.insertBefore(b.root, empty); makeItem(kind); }
        for (const [kind, b] of kindBlocks) {
          const k = p.kinds[kind];
          const shown = !!k && (KIND_BY_NAME.get(kind)?.rows.length ?? 0) > 0;
          setHidden(b.root, !shown);
          if (!shown || !k) continue;
          setText(b.title, label(kind, k.count));
          for (const r of b.rows) r.row.paint(r.def.show(k.props));
        }
        const kinds = Array.from(counts.keys());
        const text = filter ? label(filter, counts.get(filter) ?? 0) : kinds.length === 1 ? label(kinds[0], total) : `All (${total})`;
        setText(typeLabel, text);
        const bare = kinds.filter((k) => !(KIND_BY_NAME.get(k)?.rows.length));
        setText(empty, bare.length ? `${bare.map((k) => kindTitle(k)).join(', ')}: use the object's own edit command to change its geometry.` : '');
        setHidden(empty, !bare.length);
        for (const [key, item] of items) {
          const n = key === '*' ? total : counts.get(key) ?? 0;
          setHidden(item, key === '*' ? kinds.length < 2 : n === 0);
          setText(item.querySelector('span') as HTMLElement, key === '*' ? `All (${n})` : label(key, n));
          const chosen = key === '*' ? filter === null : filter === key;
          setClass(item, 'is-chosen', chosen);
          item.setAttribute('aria-selected', String(chosen));
        }
      }

      const syncPickAdd = (): void => {
        const on = sysvars.num('PICKADD', 1) !== 0;
        setClass(pickAdd, 'is-on', on);
        pickAdd.setAttribute('aria-pressed', String(on));
        setTitle(pickAdd, on ? 'PICKADD is on: each pick adds to the selection' : 'PICKADD is off: a new pick replaces the selection');
      };

      typeBtn.addEventListener('click', () => {
        if (!pop.hidden) { setHidden(pop, true); return; }
        setHidden(pop, false);
        const r = typeBtn.getBoundingClientRect();
        pop.style.minWidth = `${Math.round(r.width)}px`;
        pop.style.left = `${Math.round(r.left)}px`;
        pop.style.top = `${Math.round(r.bottom + 4)}px`;
      });
      document.addEventListener('pointerdown', (e) => {
        if (!pop.hidden && !pop.contains(e.target as Node) && !typeBtn.contains(e.target as Node)) setHidden(pop, true);
      }, true);
      pickAdd.addEventListener('click', () => { void sysvars.set('PICKADD', sysvars.num('PICKADD', 1) !== 0 ? 0 : 1); });
      selectBtn.addEventListener('click', () => { void runEngineText('select'); });
      quickBtn.addEventListener('click', () => { commands.run('open-quick-select'); });

      const menu = new PopupMenu(commands, null, true);
      menu.setItems(['open-quick-select', 'select-all', 'deselect-all', '-', 'win-hide-palettes']);
      body.addEventListener('contextmenu', (e) => {
        if ((e.target as HTMLElement).closest('input, select, textarea')) return;
        e.preventDefault();
        menu.openAt(e.clientX, e.clientY);
      });

      selection.onChange(() => { filter = null; });
      properties.onChange(() => { void refresh(); });
      sysvars.onChange(() => {
        syncPickAdd();
        if (!view) paint();
        const doc = docStore.activeId;
        if (doc && !view && !tablesDoc.startsWith(`${doc}:`)) void loadTables();
      });
      docStore.onChange(() => {
        const doc = docStore.current();
        if (!doc || view) return;
        if (tablesDoc !== `${doc.id}:${doc.rev}`) void loadTables();
      });
      syncPickAdd();
      paint();
      return { show: () => { if (!view) void loadTables(); } };
    },
  };
}

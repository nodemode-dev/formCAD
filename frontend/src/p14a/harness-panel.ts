import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, setHidden, setText } from '../ui/dom';
import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, selectCtl } from '../u8/ui';
import { asArr, dataTable, entityList, formGrid, guard, mm, reportBox, section, sig, type Json, type RowItem } from './kit';
import { sampleArc, type RouteLayer } from './route-layer';
import { harnessFeed as feed } from './route-store';

const NODE_KINDS: Array<[string, string]> = [['connector', 'Connector'], ['clip', 'Clip'], ['splice', 'Splice'], ['branch', 'Branch'], ['waypoint', 'Waypoint'], ['end', 'End']];
const BADGE: Record<string, string> = { connector: 'CN', clip: 'CL', splice: 'SP', branch: 'BR', waypoint: 'WP', end: 'EN' };
const TABLES: Array<[string, string]> = [['wirelist', 'Wire list'], ['fromto', 'From-to'], ['segments', 'Segments'], ['connectors', 'Connector pins']];

export const layerRef: { layer: RouteLayer | null } = { layer: null };

const endName = (e: Json | undefined): string => (e ? `${String(e.node ?? '')}${e.pin ? `:${String(e.pin)}` : ''}` : '');

function polyline(path: Json): number[][] {
  const out: number[][] = [];
  for (const p of asArr<Json>(path.pieces)) {
    const a = p.a as number[], b = p.b as number[];
    if (p.k === 'arc') out.push(...sampleArc(p.c as number[], a, b));
    else out.push(a, b);
  }
  for (const s of asArr<number[]>(path.samples)) out.push(s);
  return out;
}

const toSegs = (pts: number[][]): number[][][] => [pts];

export function harnessPanel(): DockPanel {
  return {
    id: 'harness', label: 'Harness', icon: 'harness', order: 48,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel', 'p14-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open an assembly to build a harness.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);

      const sOver = section('Overview');
      const over = reportBox(4);
      sOver.body.append(over.el);

      const sNodes = section('Nodes');
      const nodeList = el('<div class="u8-list p14-list" role="listbox" aria-label="Harness nodes"></div>');
      const paintNodes = entityList(nodeList, () => undefined, (k) => { void act('remove', { kind: 'node', id: k }); });
      const nf = formGrid([
        { key: 'kind', label: 'Kind', kind: 'select', options: NODE_KINDS }, { key: 'label', label: 'Label', kind: 'text', value: '' },
        { key: 'x', label: 'x (mm)', value: 0 }, { key: 'y', label: 'y (mm)', value: 0 }, { key: 'z', label: 'z (mm)', value: 0 },
        { key: 'pins', label: 'Pins', value: 4 }, { key: 'inner_d', label: 'Clip bore (mm)', value: 0 }, { key: 'component', label: 'On component', kind: 'text', value: '' },
      ], () => paintNodeForm());
      const paintNodeForm = (): void => { const k = String(nf.ctl.kind.get()); nf.show('pins', k === 'connector'); nf.show('inner_d', k === 'clip'); };
      sNodes.body.append(nodeList, nf.el, buttons(button('Add node', () => { void addNode(); }, 'primary')));

      const sSeg = section('Segments');
      const segList = el('<div class="u8-list p14-list" role="listbox" aria-label="Harness segments"></div>');
      const paintSegs = entityList(segList, () => undefined, (k) => { void act('remove', { kind: 'segment', id: k }); });
      const sf = formGrid([
        { key: 'a', label: 'From node', kind: 'select', options: [] }, { key: 'b', label: 'To node', kind: 'select', options: [] },
        { key: 'via', label: 'Through (clips, waypoints)', kind: 'text', value: '' },
        { key: 'mode', label: 'Path', kind: 'select', options: [['fillet', 'Arcs between lines'], ['spline', 'Smooth curve']] },
        { key: 'radius', label: 'Corner radius (mm, 0 = automatic)', value: 0 }, { key: 'diameter', label: 'Diameter (mm, 0 = from wires)', value: 0 },
      ]);
      sSeg.body.append(segList, sf.el, buttons(button('Add segment', () => { void addSegment(); }, 'primary')));

      const sWire = section('Wires and cables');
      const wireList = el('<div class="u8-list p14-list" role="listbox" aria-label="Wires and cables"></div>');
      const paintWires = entityList(wireList, () => undefined, (k) => { void act('remove', { kind: k.startsWith('CB') && !k.includes('-') ? 'cable' : 'wire', id: k }); });
      const wf = formGrid([
        { key: 'fa', label: 'Wire from node', kind: 'select', options: [] }, { key: 'fp', label: 'From pin', kind: 'text', value: '1' },
        { key: 'ta', label: 'Wire to node', kind: 'select', options: [] }, { key: 'tp', label: 'To pin', kind: 'text', value: '1' },
        { key: 'gauge', label: 'Gauge (AWG)', kind: 'text', value: '20' }, { key: 'colour', label: 'Colour', kind: 'text', value: '' }, { key: 'net', label: 'Net', kind: 'text', value: '' },
        { key: 'cores', label: 'Cable cores (cable only)', value: 2 }, { key: 'cod', label: 'Cable diameter (mm)', value: 4 }, { key: 'shield', label: 'Shielded', kind: 'check', value: false },
      ]);
      sWire.body.append(wireList, wf.el, buttons(button('Add wire', () => { void addWire(); }, 'primary'), button('Add cable', () => { void addCable(); })));

      const sBend = section('Bundles and bend radius');
      const bendTab = dataTable(5);
      const flags = reportBox(5);
      sBend.body.append(bendTab.el, flags.el);

      const sFlat = section('Formboard');
      const settings = formGrid([{ key: 'branch_angle', label: 'Branch angle (deg)', value: 90 }, { key: 'clearance', label: 'Clearance (mm)', value: 12 }, { key: 'min_bend_factor', label: 'Bend radius factor', value: 10 }, { key: 'allowance', label: 'End allowance (mm)', value: 6 }]);
      const svgNs = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(svgNs, 'svg');
      svg.setAttribute('class', 'p14-flat');
      svg.setAttribute('viewBox', '0 0 300 150');
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', 'Flattened harness');
      const lines: SVGLineElement[] = [];
      const dots: SVGCircleElement[] = [];
      const labels: SVGTextElement[] = [];
      for (let i = 0; i < 40; i++) { const l = document.createElementNS(svgNs, 'line'); l.setAttribute('class', 'p14-flat-seg'); l.setAttribute('visibility', 'hidden'); lines.push(l); svg.appendChild(l); }
      for (let i = 0; i < 40; i++) { const c = document.createElementNS(svgNs, 'circle'); c.setAttribute('r', '3'); c.setAttribute('class', 'p14-flat-node'); c.setAttribute('visibility', 'hidden'); dots.push(c); svg.appendChild(c); const tx = document.createElementNS(svgNs, 'text'); tx.setAttribute('class', 'p14-flat-text'); labels.push(tx); svg.appendChild(tx); }
      const flatBox = reportBox(2);
      sFlat.body.append(settings.el, buttons(button('Save settings', () => { void saveSettings(); }), button('Flatten', () => { void act('flatten', {}); }), button('Draw the formboard', () => { void act('formboard', {}, true); }), button('Clear the sheet', () => { void act('clearsheet', {}); })), svg, flatBox.el);

      const sTab = section('Wire list and from-to');
      const tabSel = selectCtl('Table', TABLES, () => paintTable());
      const tab = dataTable(8);
      sTab.body.append(tabSel.el, tab.el, buttons(button('Export CSV', () => { void exportCsv(); })));
      live.append(sOver.root, sNodes.root, sSeg.root, sWire.root, sBend.root, sFlat.root, sTab.root);

      async function act(action: string, args: Json, draw = false): Promise<Json | null> {
        const r = await guard(() => feed.post('', { action, args }));
        if (r && draw) toast(t('Formboard drawn on its sheet.'), 'info');
        return r;
      }
      async function addNode(): Promise<void> {
        const v = nf.get();
        const kind = String(v.kind ?? 'connector');
        const args: Json = { kind, label: v.label ?? '', point: [v.x ?? 0, v.y ?? 0, v.z ?? 0] };
        if (kind === 'connector') args.pins = Math.max(0, Math.round(Number(v.pins ?? 0)));
        if (kind === 'clip') args.inner_d = v.inner_d ?? 0;
        if (v.component) args.component = v.component;
        await act('addnode', args);
      }
      async function addSegment(): Promise<void> {
        const v = sf.get();
        if (!v.a || !v.b) { toast(t('Add two nodes first.'), 'error'); return; }
        await act('addsegment', { a: v.a, b: v.b, via: String(v.via ?? '').split(/[,\s]+/).filter(Boolean), mode: v.mode, radius: v.radius ?? 0, diameter: v.diameter ?? 0 });
      }
      async function addWire(): Promise<void> {
        const v = wf.get();
        if (!v.fa || !v.ta) { toast(t('Add two nodes first.'), 'error'); return; }
        await act('addwire', { from: { node: v.fa, pin: v.fp ?? '' }, to: { node: v.ta, pin: v.tp ?? '' }, gauge: v.gauge ?? '20', colour: v.colour ?? '', net: v.net ?? '' });
      }
      async function addCable(): Promise<void> {
        const v = wf.get();
        if (!v.fa || !v.ta) { toast(t('Add two nodes first.'), 'error'); return; }
        const n = Math.max(1, Math.round(Number(v.cores ?? 2)));
        const start = Number(v.fp) || 1, end = Number(v.tp) || 1;
        const cores = Array.from({ length: n }, (_, i) => ({ from_pin: String(start + i), to_pin: String(end + i), gauge: v.gauge ?? '20', colour: i === 0 ? 'white' : 'black', net: v.net ? `${String(v.net)}${i + 1}` : '' }));
        await act('addcable', { from: v.fa, to: v.ta, cores, od: v.cod ?? 4, shield: v.shield === true });
      }
      async function saveSettings(): Promise<void> { await act('settings', { changes: settings.get() }); }
      async function exportCsv(): Promise<void> {
        const kind = tabSel.get();
        const path = await pickPath('save', t('Export the table'), `${kind}.csv`, [{ name: 'CSV table', extensions: ['csv'] }], t('Save'));
        if (!path) return;
        const r = await guard(() => feed.post('/export', { kind, file: path }));
        if (r) toast(`${t('Table written')}: ${String(r.path ?? path)}`, 'info');
      }

      const report = (): Json => feed.get('report');
      const wiresOf = (): Json[] => asArr<Json>(report().wires);
      function paintTable(): void {
        const kind = tabSel.get();
        const ws = wiresOf();
        if (kind === 'fromto') tab.set(['From', 'To', 'Wire', 'Net', 'Cut mm'], [...ws].sort((a, b) => endName(a.from as Json).localeCompare(endName(b.from as Json))).map((w) => [endName(w.from as Json), endName(w.to as Json), String(w.id), String(w.net ?? ''), mm(w.cut, 1)]));
        else if (kind === 'segments') tab.set(['Segment', 'From', 'To', 'Wires', 'Length', 'OD', 'Min R', 'Bend'], asArr<Json>(report().segments).map((s) => [String(s.id), String(s.a), String(s.b), String(s.count), mm(s.length, 1), mm(s.od, 2), mm(s.required_radius, 1), s.ok ? 'ok' : 'TIGHT']), (i) => asArr<Json>(report().segments)[i]?.ok === false);
        else if (kind === 'connectors') {
          const rows: string[][] = [];
          for (const n of asArr<Json>(feed.get('list').nodes).filter((x) => x.kind === 'connector')) for (const p of asArr<Json>(n.pins)) {
            const hits = ws.filter((w) => [w.from, w.to].some((e) => (e as Json).node === n.id && (e as Json).pin === p.id));
            if (!hits.length) rows.push([String(n.id), String(p.id), '', '']);
            for (const w of hits) rows.push([String(n.id), String(p.id), String(w.id), endName((((w.from as Json).node === n.id) ? w.to : w.from) as Json)]);
          }
          tab.set(['Connector', 'Pin', 'Wire', 'To'], rows);
        } else tab.set(['Wire', 'Gauge', 'Colour', 'From', 'To', 'Run mm', 'Cut mm'], ws.map((w) => [String(w.id), String(w.gauge ?? ''), String(w.colour ?? ''), endName(w.from as Json), endName(w.to as Json), mm(w.run, 1), mm(w.cut, 1)]));
      }

      function paintFlat(): void {
        const flat = (feed.get('list').flat ?? {}) as Json;
        const pos = (flat.nodes ?? {}) as Record<string, number[]>;
        const ids = Object.keys(pos);
        const segs = asArr<Json>(report().segments);
        if (!ids.length) { lines.forEach((l) => l.setAttribute('visibility', 'hidden')); dots.forEach((c, i) => { c.setAttribute('visibility', 'hidden'); setText(labels[i] as unknown as HTMLElement, ''); }); flatBox.set([t('Not flattened yet.')]); return; }
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const p of Object.values(pos)) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
        const sc = Math.min(260 / Math.max(1, x1 - x0), 110 / Math.max(1, y1 - y0));
        const X = (p: number[]): number => 20 + (p[0] - x0) * sc;
        const Y = (p: number[]): number => 130 - (p[1] - y0) * sc;
        lines.forEach((l, i) => {
          const s = segs[i];
          const a = s ? pos[String(s.a)] : undefined, b = s ? pos[String(s.b)] : undefined;
          if (!a || !b) { l.setAttribute('visibility', 'hidden'); return; }
          l.setAttribute('x1', String(X(a))); l.setAttribute('y1', String(Y(a))); l.setAttribute('x2', String(X(b))); l.setAttribute('y2', String(Y(b)));
          l.setAttribute('visibility', 'visible');
          l.setAttribute('class', s?.ok === false ? 'p14-flat-seg is-bad' : 'p14-flat-seg');
        });
        dots.forEach((c, i) => {
          const id = ids[i];
          const lb = labels[i];
          if (!id) { c.setAttribute('visibility', 'hidden'); lb.textContent = ''; return; }
          c.setAttribute('cx', String(X(pos[id]))); c.setAttribute('cy', String(Y(pos[id]))); c.setAttribute('visibility', 'visible');
          lb.setAttribute('x', String(X(pos[id]) + 5)); lb.setAttribute('y', String(Y(pos[id]) - 5)); lb.textContent = id;
        });
        flatBox.set([`${t('Trunk')}: ${asArr<string>(flat.trunk).join(', ') || '-'}`, `${t('Branch angle')} ${sig(flat.angle, 3)} deg, ${t('clearance')} ${sig(flat.clearance, 3)} mm`]);
      }

      function paintLayer(): void {
        const layer = layerRef.layer;
        if (!layer) return;
        const ok: number[][][] = [], bad: number[][][] = [];
        for (const s of asArr<Json>(report().segments)) (s.ok === false ? bad : ok).push(...toSegs(polyline((s.path ?? {}) as Json)));
        const pts = Object.values((report().nodes ?? {}) as Record<string, Json>).map((n) => n.p as number[]).filter(Boolean);
        layer.setHarness(ok, bad, pts);
        layer.setShown(true);
      }

      let sigKey = '';
      const paint = (): void => {
        const on = !!docStore.current();
        setHidden(note, on); setHidden(live, !on);
        if (!on || !feed.has()) return;
        const l = feed.get('list');
        const r = report();
        const nodes = asArr<Json>(l.nodes), segs = asArr<Json>(r.segments), wires = asArr<Json>(l.wires), cables = asArr<Json>(l.cables);
        const tot = (r.totals ?? {}) as Json;
        const fl = asArr<Json>(r.flags);
        over.set([`${nodes.length} ${t('nodes')}, ${segs.length} ${t('segments')}, ${wires.length} ${t('wires')}, ${cables.length} ${t('cables')}`, `${t('Wire length')} ${mm(tot.wire_length, 1)} mm`, `${t('Bend radius violations')}: ${String(r.violations ?? 0)}`, ...asArr<string>(r.warnings).slice(0, 1)], Number(r.violations ?? 0) > 0);
        const nodeOpts = nodes.map((n) => [String(n.id), `${String(n.id)} ${String(n.label ?? '')}`.trim()] as [string, string]);
        for (const k of ['a', 'b']) sf.options(k, nodeOpts);
        for (const k of ['fa', 'ta']) wf.options(k, nodeOpts);
        paintNodeForm();
        paintNodes(nodes.map((n): RowItem => ({ key: String(n.id), badge: BADGE[String(n.kind)] ?? 'ND', name: `${String(n.id)} ${String(n.label ?? '')}`.trim(), sub: n.kind === 'connector' ? `${asArr(n.pins).length} ${t('pins')}` : String(n.kind) })));
        paintSegs(segs.map((s): RowItem => ({ key: String(s.id), badge: 'SG', name: `${String(s.id)} ${String(s.a)} - ${String(s.b)}`, sub: `${mm(s.length, 0)} mm`, bad: s.ok === false })));
        paintWires([...cables.map((c): RowItem => ({ key: String(c.id), badge: 'CB', name: `${String(c.id)} ${String(c.label ?? '')}`.trim(), sub: `${asArr(c.cores).length} ${t('cores')}` })), ...wires.filter((w) => !w.cable).map((w): RowItem => ({ key: String(w.id), badge: 'WR', name: `${String(w.id)} ${endName(w.from as Json)} - ${endName(w.to as Json)}`, sub: `${String(w.gauge ?? '')} ${String(w.colour ?? '')}`.trim() }))]);
        bendTab.set(['Segment', 'Wires', 'OD mm', 'Min R mm', 'Tightest', 'Bend'], segs.map((s) => [String(s.id), String(s.count), mm(s.od, 2), mm(s.required_radius, 1), s.tightest === null || s.tightest === undefined ? '-' : mm(s.tightest, 1), s.ok ? 'ok' : 'TIGHT']), (i) => segs[i]?.ok === false);
        flags.set(fl.map((f) => `${String(f.rule)}: ${String(f.status)}. ${String(f.source)}`).slice(0, 5), false);
        const st = (l.settings ?? {}) as Json;
        const key = JSON.stringify(st);
        if (key !== sigKey) { sigKey = key; for (const k of ['branch_angle', 'clearance', 'min_bend_factor', 'allowance']) if (typeof st[k] === 'number') settings.set(k, st[k]); }
        paintTable();
        paintFlat();
        paintLayer();
      };
      feed.onChange(paint);
      docStore.onChange(paint);
      paint();
      return { show: () => { feed.setActive(true); } };
    },
  };
}

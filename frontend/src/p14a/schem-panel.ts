import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, setHidden, setText } from '../ui/dom';
import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons } from '../u8/ui';
import { asArr, dataTable, entityList, formGrid, guard, mm, reportBox, section, type Json, type RowItem } from './kit';
import { schemFeed as feed } from './route-store';

export function schemPanel(): DockPanel {
  return {
    id: 'schem', label: 'Electrical schematic', icon: 'schematic', order: 50,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel', 'p14-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a drawing to place devices and wires on a schematic sheet.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);

      const sOver = section('Overview');
      const over = reportBox(3);
      const symNote = el('<p class="u8-note p14-note"></p>');
      sOver.body.append(over.el, symNote);

      const sDev = section('Devices');
      const devList = el('<div class="u8-list p14-list" role="listbox" aria-label="Devices"></div>');
      const paintDevs = entityList(devList, () => undefined, (k) => { void guard(() => feed.del(`/devices/${encodeURIComponent(k)}`)); });
      const df = formGrid([
        { key: 'type', label: 'Kind', kind: 'select', options: [] }, { key: 'refdes', label: 'Reference (blank = automatic)', kind: 'text', value: '' }, { key: 'label', label: 'Label', kind: 'text', value: '' },
        { key: 'x', label: 'x', value: 100 }, { key: 'y', label: 'y', value: 100 },
        { key: 'rotation', label: 'Rotation', kind: 'select', options: [['0', '0'], ['90', '90'], ['180', '180'], ['270', '270']] },
        { key: 'sheet', label: 'Sheet', value: 1 }, { key: 'pin_count', label: 'Pins (connectors)', value: 4 },
      ]);
      sDev.body.append(devList, df.el, buttons(button('Add device', () => { void addDevice(); }, 'primary')));

      const sWire = section('Wires');
      const wireList = el('<div class="u8-list p14-list" role="listbox" aria-label="Wires"></div>');
      const paintWires = entityList(wireList, () => undefined, (k) => { void guard(() => feed.del(`/wires/${encodeURIComponent(k)}`)); });
      const wf = formGrid([
        { key: 'fd', label: 'From device', kind: 'select', options: [] }, { key: 'fp', label: 'From pin', kind: 'select', options: [] },
        { key: 'td', label: 'To device', kind: 'select', options: [] }, { key: 'tp', label: 'To pin', kind: 'select', options: [] },
        { key: 'name', label: 'Wire name (blank = number)', kind: 'text', value: '' }, { key: 'gauge', label: 'Gauge', kind: 'text', value: '20' },
        { key: 'colour', label: 'Colour', kind: 'text', value: '' }, { key: 'signal_class', label: 'Signal class', kind: 'text', value: 'signal' }, { key: 'sheet', label: 'Sheet', value: 1 },
      ], () => paintPins());
      sWire.body.append(wireList, wf.el, buttons(button('Add wire', () => { void addWire(); }, 'primary')));

      const sNum = section('Numbering and checks');
      const nf = formGrid([{ key: 'template', label: 'Number template', kind: 'text', value: '{prefix}{sheet}-{seq:02}' }, { key: 'prefix', label: 'Prefix', kind: 'text', value: 'W' }, { key: 'keep_manual', label: 'Keep manual numbers', kind: 'check', value: true }]);
      const checkTab = dataTable(4);
      sNum.body.append(nf.el, buttons(button('Number the wires', () => { void numberWires(); }, 'primary'), button('Redraw the sheets', () => { void draw(); })), checkTab.el);

      const sList = section('Wire list');
      const wlTab = dataTable(8);
      sList.body.append(wlTab.el, buttons(button('Export CSV', () => { void exportCsv(); })));
      live.append(sOver.root, sDev.root, sWire.root, sNum.root, sList.root);

      const devs = (): Json[] => asArr<Json>(feed.get('list').devices);
      const pinOpts = (id: unknown): Array<[string, string]> => asArr<Json>(devs().find((d) => d.id === id)?.pins).map((p) => [String(p.id), String(p.id)]);
      function paintPins(): void {
        wf.options('fp', pinOpts(wf.ctl.fd.get()));
        wf.options('tp', pinOpts(wf.ctl.td.get()));
      }

      async function addDevice(): Promise<void> {
        const v = df.get();
        const kind = String(v.type ?? 'resistor');
        const rec: Json = { type: kind, label: v.label ?? '', x: v.x ?? 0, y: v.y ?? 0, rotation: Number(v.rotation ?? 0), sheet: v.sheet ?? 1 };
        if (v.refdes) rec.refdes = v.refdes;
        if (kind === 'connector') rec.pin_count = Math.max(1, Math.round(Number(v.pin_count ?? 4)));
        await guard(() => feed.post('/devices', rec));
      }
      async function addWire(): Promise<void> {
        const v = wf.get();
        if (!v.fd || !v.td || !v.fp || !v.tp) { toast(t('Add two devices with pins first.'), 'error'); return; }
        await guard(() => feed.post('/wires', { from: { device: v.fd, pin: v.fp }, to: { device: v.td, pin: v.tp }, name: v.name ?? '', gauge: v.gauge ?? '', colour: v.colour ?? '', signal_class: v.signal_class ?? 'signal', sheet: v.sheet ?? 1 }));
      }
      async function numberWires(): Promise<void> {
        const v = nf.get();
        const r = await guard(() => feed.post('/number', { template: v.template, prefix: v.prefix, keep_manual: v.keep_manual === true }));
        if (r) toast(t('Wires numbered.'), 'info');
      }
      async function draw(): Promise<void> {
        const r = await guard(() => feed.post('/draw', {}));
        if (r) toast(t('Sheets redrawn.'), 'info');
      }
      async function exportCsv(): Promise<void> {
        const path = await pickPath('save', t('Export the wire list'), 'wirelist.csv', [{ name: 'CSV table', extensions: ['csv'] }], t('Save'));
        if (!path) return;
        const r = await guard(() => feed.post('/export', { path }));
        if (r) toast(`${t('Wire list written')}: ${String(r.path ?? path)}`, 'info');
      }

      let sigKey = '';
      const paint = (): void => {
        const on = !!docStore.current();
        setHidden(note, on); setHidden(live, !on);
        if (!on || !feed.has()) return;
        const l = feed.get('list');
        const wires = asArr<Json>(l.wires);
        const chk = feed.get('check');
        const probs = asArr<Json>(chk.problems);
        const set = (l.settings ?? {}) as Json;
        over.set([`${devs().length} ${t('devices')}, ${wires.length} ${t('wires')}, ${asArr(l.sheets).length} ${t('sheets')}`, `${t('Template')} ${String(set.template ?? '')}`, `${String(chk.errors ?? 0)} ${t('errors')}, ${probs.length} ${t('problems')}`], Number(chk.errors ?? 0) > 0);
        setText(symNote, String(((l.labels ?? {}) as Json).symbols ?? ''));
        df.options('type', asArr<string>(l.kinds).map((k) => [k, k.replace(/_/g, ' ')] as [string, string]));
        const opts = devs().map((d) => [String(d.id), `${String(d.refdes)} ${String(d.label ?? '')}`.trim()] as [string, string]);
        wf.options('fd', opts); wf.options('td', opts);
        paintPins();
        df.show('pin_count', df.ctl.type.get() === 'connector');
        paintDevs(devs().map((d): RowItem => ({ key: String(d.id), badge: 'DV', name: `${String(d.refdes)} ${String(d.label ?? '')}`.trim(), sub: `${String(d.type)} s${String(d.sheet)}` })));
        paintWires(wires.map((w): RowItem => ({ key: String(w.id), badge: 'WR', name: `${String(w.number ?? '')} ${String(w.name ?? '')}`.trim() || String(w.id), sub: `${String(w.gauge ?? '')} ${String(w.colour ?? '')}`.trim() })));
        const key = JSON.stringify(set);
        if (key !== sigKey) { sigKey = key; if (typeof set.template === 'string') nf.set('template', set.template); if (typeof set.prefix === 'string') nf.set('prefix', set.prefix); }
        checkTab.set(['Severity', 'Code', 'Message'], probs.map((p) => [String(p.severity), String(p.code), String(p.message)]), (i) => probs[i]?.severity === 'error');
        wlTab.set(['Number', 'Name', 'From', 'To', 'Gauge', 'Colour', 'Sheet'], asArr<Json>(feed.get('wirelist').rows).map((r) => [String(r.number ?? ''), String(r.name ?? ''), String(r.from), String(r.to), String(r.gauge ?? ''), String(r.colour ?? ''), mm(r.sheet, 0)]));
      };
      feed.onChange(paint);
      docStore.onChange(paint);
      paint();
      return { show: () => { feed.setActive(true); } };
    },
  };
}

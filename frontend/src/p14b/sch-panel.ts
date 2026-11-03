import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import type { DockPanel } from '../ui/dock';
import { button, buttons, checkCtl, dirOf, fillSelect, guard, num, reportBox, section, selectCtl, textField } from './kit';
import { ecStage } from './stage';
import { ec, type Json } from './store';

const POWER = ['+5V', '+3V3', '+12V', '-12V', 'GND', 'VCC', 'VDD', 'VSS'];

export function schPanel(): DockPanel {
  return {
    id: 'ecsch', label: 'Schematic', icon: 'ecad',
    build(body) {
      body.classList.add('ec-panel');
      const sheets = section('Sheets');
      const sheetList = el('<div class="ec-list ec-list-sm"></div>');
      const sheetName = textField('Sheet name', '');
      const childSel = selectCtl('Child sheet', [['', '-']]);
      sheets.body.append(sheetList, sheetName.el,
        buttons(button('New sheet', () => void guard(async () => { await ec.ops([{ op: 'add_sheet', name: sheetName.get() || `Sheet ${((ec.sum?.sheets ?? []) as unknown[]).length + 1}` }]); })),
          button('Rename', () => void guard(async () => { if (sheetName.get()) await ec.ops([{ op: 'set_sheet', sheet: ec.sheetId, name: sheetName.get() }]); })),
          button('Delete', () => void guard(async () => { await ec.ops([{ op: 'delete_sheet', sheet: ec.sheetId }]); }), 'danger')),
        childSel.el,
        buttons(button('Add sheet symbol', () => void guard(async () => { if (childSel.get()) await ec.ops([{ op: 'add_sheet_symbol', child: childSel.get(), pos: [30, 190] }]); }))));

      const place = section('Place');
      const filter = textField('Search', '');
      const symList = el('<div class="ec-list"></div>');
      const symInfo = el('<div class="ec-info"></div>');
      const powerSel = selectCtl('Power net', POWER.map((p) => [p, p] as [string, string]), () => { ecStage.sch.power = powerSel.get(); });
      const labelIn = textField('Label text', 'NET1', (v) => { ecStage.sch.labelText = v || 'NET1'; });
      place.body.append(filter.el, symList, symInfo, powerSel.el, labelIn.el,
        buttons(button('Wire tool', () => ecStage.sch.setTool('wire')), button('Label tool', () => ecStage.sch.setTool('label')), button('Power tool', () => ecStage.sch.setTool('power'))));
      filter.input.addEventListener('input', () => paintSyms());

      const part = section('Selected part');
      const partInfo = el('<div class="ec-info"></div>');
      const ref = textField('Reference', '', (v) => void setPart({ refdes: v }));
      const val = textField('Value', '', (v) => void setPart({ value: v }));
      const fp = selectCtl('Footprint', [['', '-']], () => void setPart({ footprint: fp.get() }));
      const dnp = checkCtl('Do not populate', false, () => void setPart({ dnp: dnp.get() }));
      part.body.append(partInfo, ref.el, val.el, fp.el, dnp.el,
        buttons(button('Rotate', () => void ecStage.sch.rotate(90)), button('Mirror', () => void ecStage.sch.mirror()),
          button('Delete', () => { const s = ecStage.sch.sel; if (s) void ecStage.sch.remove(s); }, 'danger')),
        buttons(button('Annotate unset', () => void guard(async () => { await ec.ops([{ op: 'annotate' }]); })), button('Annotate all', () => void guard(async () => { await ec.ops([{ op: 'annotate', all: true }]); }))));

      const erc = section('ERC');
      const ercLine = el('<div class="ec-info"></div>');
      const ercList = el('<div class="ec-list ec-list-md"></div>');
      const markers = checkCtl('Show markers', true, () => { ecStage.sch.markers = markers.get(); ecStage.sch.view.request(); });
      const ruleSel = selectCtl('Rule', [['', '-']]);
      const sevSel = selectCtl('Severity', [['error', 'error'], ['warning', 'warning'], ['ignore', 'ignore']]);
      erc.body.append(ercLine, markers.el, ercList, ruleSel.el, sevSel.el,
        buttons(button('Apply severity', () => void guard(async () => { if (ruleSel.get()) await ec.call('POST', 'ecad/erc/settings', { rules: { [ruleSel.get()]: sevSel.get() } }); })),
          button('Recheck', () => void ec.refresh())));

      const out = section('Netlist and BOM');
      const nlLine = el('<div class="ec-info"></div>');
      const nlPath = textField('Netlist file', '');
      const bomPath = textField('BOM file', '');
      const rep = reportBox(2);
      out.body.append(nlLine, nlPath.el, bomPath.el,
        buttons(button('Netlist (.net)', () => void guard(async () => { const r = await ec.call<Json>('POST', 'ecad/export/netlist', { path: nlPath.get(), format: 'text' }); rep.set(r ? [`Netlist: ${r.path ?? nlPath.get()}`, `${r.components ?? ''} components, ${r.nets ?? ''} nets`] : ['Netlist export refused'], !r); })),
          button('Netlist (json)', () => void guard(async () => { const p = nlPath.get().replace(/\.[^./\\]+$/, '') + '.json'; const r = await ec.call<Json>('POST', 'ecad/export/netlist', { path: p, format: 'json' }); rep.set(r ? [`Netlist: ${r.path ?? p}`] : ['Netlist export refused'], !r); })),
          button('BOM (.csv)', () => void guard(async () => { const r = await ec.call<Json>('POST', 'ecad/export/bom', { path: bomPath.get() }); rep.set(r ? [`BOM: ${r.path ?? bomPath.get()}`, `${r.lines ?? r.rows ?? ''} lines`] : ['BOM export refused'], !r); }))),
        rep.el);

      body.append(sheets.root, place.root, part.root, erc.root, out.root);

      async function setPart(patch: Json): Promise<void> {
        const s = ecStage.sch.sel;
        if (s?.kind !== 'part') return;
        await ec.ops([{ op: 'set_part', part: s.id, ...patch }]);
      }

      let symSig = '';
      const paintSyms = (): void => {
        if (!ecStage.sch) return;
        const f = filter.get().toLowerCase();
        const rows = ec.symbols.filter((s) => !f || `${s.id} ${s.name}`.toLowerCase().includes(f)).slice(0, 80);
        const sig = rows.map((r) => r.id).join(',') + '|' + ecStage.sch.symbol;
        if (sig === symSig) return;
        symSig = sig;
        patchList(symList, rows, {
          key: (r) => String(r.id),
          create: (r) => { const n = el(`<div class="ec-row" role="button" tabindex="0"><span class="ec-row-id"></span><span class="ec-row-name"></span></div>`); n.addEventListener('click', () => { ecStage.sch.symbol = String(r.id); ecStage.sch.setTool('place'); symSig = ''; paintSyms(); }); return n; },
          update: (n, r) => { setText(q(n, '.ec-row-id'), String(r.id)); setText(q(n, '.ec-row-name'), `${r.name} · ${r.pins} pins`); setClass(n, 'is-on', ecStage.sch.symbol === r.id); },
        });
        const cur = ec.symbols.find((s) => s.id === ecStage.sch.symbol);
        setText(symInfo, cur ? `${t('Placing')} ${cur.id} · ${cur.default_footprint || t('no footprint')}` : '');
      };

      const paint = (): void => {
        if (!ecStage.sch) return;
        const list = (ec.sum?.sheets ?? []) as Json[];
        patchList(sheetList, list, {
          key: (s) => String(s.id),
          create: (s) => { const n = el('<div class="ec-row" role="button" tabindex="0"><span class="ec-row-id"></span><span class="ec-row-name"></span></div>'); n.addEventListener('click', () => void ec.setSheet(String(s.id))); return n; },
          update: (n, s) => { setText(q(n, '.ec-row-id'), String(s.id)); setText(q(n, '.ec-row-name'), `${s.name} · ${s.parts} parts, ${s.wires} wires`); setClass(n, 'is-on', s.id === ec.sheetId); },
        });
        fillSelect(childSel.input as HTMLSelectElement, [['', '-'], ...list.filter((s) => s.id !== ec.sheetId).map((s) => [String(s.id), String(s.name)] as [string, string])]);
        paintSyms();
        const sel = ecStage.sch.sel;
        const c = sel?.kind === 'part' ? ((ec.scene?.components ?? []) as Json[]).find((x) => x.part === sel.id) : null;
        const p = sel?.kind === 'part' ? ((ec.sum?.parts ?? []) as Json[]).find((x) => x.id === sel.id) : null;
        setText(partInfo, p ? `${p.id} · ${p.symbol} · ${(p.placements as Json[]).length} placement` : sel ? `${sel.kind} ${sel.id}` : t('Nothing selected'));
        for (const x of [ref, val]) setDisabled(x.input, !p);
        setDisabled(fp.input as HTMLSelectElement, !p);
        setDisabled(dnp.input as HTMLInputElement, !p);
        if (p) {
          ref.set(String(p.refdes)); val.set(String(p.value));
          const fps = ec.footprints.map((f) => [String(f.id), String(f.id)] as [string, string]);
          if (p.footprint && !fps.some((f) => f[0] === p.footprint)) fps.unshift([String(p.footprint), String(p.footprint)]);
          fillSelect(fp.input as HTMLSelectElement, [['', '-'], ...fps]);
          if (document.activeElement !== fp.input) (fp.input as HTMLSelectElement).value = String(p.footprint ?? '');
          (dnp.input as HTMLInputElement).checked = !!p.dnp;
        }
        void c;
        const es = ec.erc?.summary;
        setText(ercLine, es ? `${es.error ?? 0} ${t('errors')}, ${es.warning ?? 0} ${t('warnings')}` : '');
        const viol = ((ec.erc?.violations ?? []) as Json[]).slice(0, 60);
        patchList(ercList, viol, {
          key: (v) => `${v.rule}|${v.message}|${(v.pos ?? []).join(',')}`,
          create: (v) => { const n = el('<div class="ec-row" role="button" tabindex="0"><span class="ec-row-sev"></span><span class="ec-row-name"></span></div>'); n.addEventListener('click', () => { if (v.sheet && v.sheet !== ec.sheetId) void ec.setSheet(String(v.sheet)).then(() => ecStage.sch.view.centerOn(v.pos[0], v.pos[1])); else if (v.pos) ecStage.sch.view.centerOn(v.pos[0], v.pos[1]); }); return n; },
          update: (n, v) => { setText(q(n, '.ec-row-sev'), v.severity === 'error' ? 'E' : 'W'); setClass(n, 'is-bad', v.severity === 'error'); setText(q(n, '.ec-row-name'), String(v.message)); n.title = String(v.message); },
        });
        const rules = Object.keys((ec.erc?.rules ?? {}) as Json);
        fillSelect(ruleSel.input as HTMLSelectElement, [['', '-'], ...rules.map((r) => [r, r] as [string, string])]);
        const nl = ec.net;
        setText(nlLine, nl ? `${(nl.components ?? []).length} ${t('components')}, ${(nl.nets ?? []).length} ${t('nets')}, ${(nl.unconnected ?? []).length} ${t('unconnected pins')}` : '');
        const dir = dirOf(docStore.current()?.path);
        const nm = String(ec.sum?.name ?? 'design').replace(/[^A-Za-z0-9_-]+/g, '_');
        if (dir) { nlPath.set(`${dir}/${nm}.net`); bomPath.set(`${dir}/${nm}-bom.csv`); }
        void num;
      };
      ec.onChange(paint);
      ecStage.onChange(paint);
      void ec.loadLibraries();
      paint();
      return { show: () => { void ec.loadLibraries(); paint(); } };
    },
  };
}

import { el, patchList, q, setClass, setDisabled, setText } from '../ui/dom';
import type { DockPanel } from '../ui/dock';
import { t } from '../ui/i18n';
import { req } from '../u8/net';
import { button, buttons, checkCtl, fillSelect, fixed, guard, numberCtl, progressBar, readout, reportBox, section, selectCtl } from './kit';
import { ecStage } from './stage';
import { ec, type Json } from './store';

export function pcbPanel(): DockPanel {
  return {
    id: 'ecpcb', label: 'Board', icon: 'pcb',
    build(body) {
      body.classList.add('ec-panel');
      const board = section('Board');
      const counts = el('<div class="ec-info"></div>');
      const bw = numberCtl('Width (mm)', 45), bh = numberCtl('Height (mm)', 32), br = numberCtl('Corner radius (mm)', 0);
      const layers = selectCtl('Copper layers', [['2', '2'], ['4', '4'], ['6', '6'], ['8', '8']]);
      const brep = reportBox(2);
      board.body.append(counts, bw.el, bh.el, br.el, layers.el,
        buttons(button('Apply outline', () => void guard(async () => {
          const w = bw.get(), h = bh.get();
          if (w && h) await ec.call('PUT', 'pcb/board', { rect: [0, 0, w, h], corner_radius: br.get() ?? 0, layers: Number(layers.get()) });
        })), button('Apply layers', () => void guard(async () => { await ec.call('PUT', 'pcb/board', { layers: Number(layers.get()) }); }))),
        buttons(button('Sync from schematic', () => void guard(async () => {
          const r = await ec.call<Json>('POST', 'pcb/sync', {});
          brep.set(r ? [`Added ${(r.added ?? []).length}, updated ${(r.updated ?? []).length}`, `Missing footprints ${(r.missing ?? []).length}, orphans ${(r.orphans ?? []).length}`] : ['Sync refused'], !r);
        })), button('Auto place new', () => void guard(async () => { await ec.call('POST', 'pcb/place', {}); }))),
        brep.el);

      const lay = section('Layers and tools');
      const mk = (label: string, key: keyof import('./pcb-view').Vis): ReturnType<typeof checkCtl> => {
        const c = checkCtl(label, true, () => { const v = ecStage.pcb.vis; v[key] = c.get(); ecStage.pcb.view.request(); });
        return c;
      };
      const cF = mk('Top copper', 'fcu'), cB = mk('Bottom copper', 'bcu'), cS = mk('Silkscreen', 'silk'), cZ = mk('Zone fills', 'zones'), cR = mk('Ratsnest', 'rat'), cD = mk('DRC markers', 'drc'), cC = mk('Courtyards', 'court'), cK = mk('Keepouts', 'keep');
      (cC.input as HTMLInputElement).checked = false;
      const active = selectCtl('Active layer', [['F.Cu', 'F.Cu'], ['B.Cu', 'B.Cu']], () => ecStage.pcb.setActive(active.get()));
      const netSel = selectCtl('Current net', [['', '-']], () => { ecStage.pcb.net = netSel.get(); });
      const width = numberCtl('Track width (mm, 0 = rule)', 0, () => { ecStage.pcb.width = width.get() ?? 0; });
      const via = numberCtl('Via diameter (mm, 0 = rule)', 0, () => { ecStage.pcb.viaDia = via.get() ?? 0; });
      const grid = numberCtl('Grid (mm)', 0.25, () => { const g = grid.get(); if (g && g > 0.01) ecStage.pcb.grid = g; });
      lay.body.append(cF.el, cB.el, cS.el, cZ.el, cR.el, cD.el, cC.el, cK.el, active.el, netSel.el, width.el, via.el, grid.el);

      const sel = section('Selected item');
      const selInfo = el('<div class="ec-info"></div>');
      const px = numberCtl('X (mm)', 0), py = numberCtl('Y (mm)', 0), pr = numberCtl('Rotation', 0);
      const side = selectCtl('Side', [['top', 'top'], ['bottom', 'bottom']]);
      const lock = checkCtl('Locked', false);
      const apply = (): void => void guard(async () => {
        const s = ecStage.pcb.sel;
        if (s?.kind !== 'part') return;
        await ecStage.pcb.editPart({ x: px.get(), y: py.get(), rot: pr.get(), side: side.get(), locked: lock.get() });
      });
      for (const c of [px, py, pr, side, lock]) c.input.addEventListener('change', apply);
      sel.body.append(selInfo, px.el, py.el, pr.el, side.el, lock.el,
        buttons(button('Rotate 90', () => { const s = ecStage.pcb.sel; const p = s?.kind === 'part' ? (ec.pcb?.parts as Json[]).find((x) => x.refdes === s.id) : null; if (p) void ecStage.pcb.editPart({ rot: (Number(p.rot) + 90) % 360 }); }),
          button('Flip side', () => { const s = ecStage.pcb.sel; const p = s?.kind === 'part' ? (ec.pcb?.parts as Json[]).find((x) => x.refdes === s.id) : null; if (p) void ecStage.pcb.editPart({ side: p.side === 'bottom' ? 'top' : 'bottom' }); }),
          button('Delete', () => { const s = ecStage.pcb.sel; if (s) void ecStage.pcb.remove(s); }, 'danger')));

      const rules = section('Rules and DRC');
      const profile = selectCtl('Rule profile', [['generic', 'generic']]);
      const ruleRead = el('<div class="ec-info ec-info-2"></div>');
      const drcLine = el('<div class="ec-info"></div>');
      const drcList = el('<div class="ec-list ec-list-md"></div>');
      const overrideKey = selectCtl('Override', [['clearance', 'clearance'], ['track_width', 'track_width'], ['annular_ring', 'annular_ring'], ['drill', 'drill'], ['via_dia', 'via_dia'], ['via_drill', 'via_drill'], ['hole_to_hole', 'hole_to_hole'], ['edge_clearance', 'edge_clearance']]);
      const overrideVal = numberCtl('Override value (mm)', 0.16);
      rules.body.append(profile.el, ruleRead, overrideKey.el, overrideVal.el,
        buttons(button('Apply profile', () => void guard(async () => { await ec.call('PUT', 'pcb/rules', { profile: profile.get() }); await loadRules(); })),
          button('Apply override', () => void guard(async () => { const v = overrideVal.get(); if (v !== null) await ec.call('PUT', 'pcb/rules', { overrides: { ...(ec.pcb?.rules?.overrides ?? {}), [overrideKey.get()]: v } }); await loadRules(); })),
          button('Run DRC', () => void guard(async () => { await ec.runDrc(); }), 'primary')),
        drcLine, drcList);

      const route = section('Autorouter');
      const mode = selectCtl('Nets', [['unrouted', 'Unrouted only'], ['all', 'Reroute all']]);
      const pitch = numberCtl('Grid pitch (mm)', 0.1);
      const rw = numberCtl('Track width (mm, 0 = rule)', 0);
      const bar = progressBar();
      const rrep = reportBox(3);
      route.body.append(mode.el, pitch.el, rw.el,
        buttons(button('Route', () => void guard(async () => {
          const body: Json = { mode: mode.get() };
          if (pitch.get()) body.pitch = pitch.get();
          if (rw.get()) body.width = rw.get();
          const r = await ec.route(body);
          if (r) rrep.set([`Routed ${r.nets_routed} of ${r.nets_total} nets`, `${r.tracks} segments, ${r.vias} vias, ${r.rips} rip-ups`, `${fixed(r.seconds, 2)} s at ${r.pitch} mm${Object.keys(r.failed ?? {}).length ? `, failed ${Object.keys(r.failed).join(', ')}` : ''}`]);
          else rrep.set(['Routing stopped or refused'], true);
        }), 'primary'),
          button('Clear net copper', () => void guard(async () => { const n = netSel.get(); if (n) await ec.call('DELETE', `pcb/nets/${encodeURIComponent(n)}/copper`); }), 'danger')),
        bar.el, rrep.el);
      bar.onCancel(() => void ec.cancel());

      const rat = section('Ratsnest');
      const ratList = el('<div class="ec-list ec-list-md"></div>');
      rat.body.append(ratList);
      void readout;

      body.append(board.root, lay.root, sel.root, rules.root, route.root, rat.root);

      async function loadRules(): Promise<void> {
        if (!ec.docId) return;
        try { ec.rules = await req<Json>('GET', ec.url('pcb/rules')); paint(); } catch { /* shown by DRC */ }
      }

      const paint = (): void => {
        if (!ecStage.pcb) return;
        const p = ec.pcb;
        if (p) {
          const c = p.counts;
          setText(counts, `${c.parts} ${t('parts')} · ${c.tracks} ${t('tracks')} · ${c.vias} ${t('vias')} · ${c.zones} ${t('zones')} · ${c.nets} ${t('nets')}`);
          const o = (p.board.outline ?? []) as number[][];
          if (o.length) {
            let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
            for (const [x, y] of o) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
            bw.set(Math.round((x1 - x0) * 1000) / 1000); bh.set(Math.round((y1 - y0) * 1000) / 1000);
          }
          (layers.input as HTMLSelectElement).value = String(p.board.layers ?? 2);
          const nets = ((p.netlist?.nets ?? []) as Json[]).map((n) => [String(n.name), String(n.name)] as [string, string]);
          fillSelect(netSel.input as HTMLSelectElement, [['', '-'], ...nets]);
          if (document.activeElement !== netSel.input) (netSel.input as HTMLSelectElement).value = ecStage.pcb.net;
        }
        if ((active.input as HTMLSelectElement).value !== ecStage.pcb.active) (active.input as HTMLSelectElement).value = ecStage.pcb.active;
        const s = ecStage.pcb.sel;
        const part = s?.kind === 'part' ? ((p?.parts ?? []) as Json[]).find((x) => x.refdes === s.id) : null;
        setText(selInfo, !s ? t('Nothing selected') : part ? `${part.refdes} · ${part.footprint} · ${part.value}` : `${s.kind} ${s.id}`);
        for (const c of [px, py, pr, side, lock]) setDisabled(c.input as HTMLInputElement, !part);
        if (part) { px.set(part.x); py.set(part.y); pr.set(part.rot); (side.input as HTMLSelectElement).value = part.side; (lock.input as HTMLInputElement).checked = !!part.locked; }
        const rp = ec.rules;
        if (rp) {
          const names = Object.entries((rp.profiles ?? {}) as Json).map(([k, v]) => [k, String((v as Json).name ?? k)] as [string, string]);
          fillSelect(profile.input as HTMLSelectElement, names);
          if (document.activeElement !== profile.input) (profile.input as HTMLSelectElement).value = String(rp.current?.profile ?? 'generic');
          const vals = (rp.current?.values ?? {}) as Json;
          setText(ruleRead, ['clearance', 'track_width', 'via_dia', 'via_drill', 'annular_ring', 'edge_clearance'].map((k) => `${k} ${vals[k]}`).join(' · '));
        }
        const d = ec.drc;
        const stale = d && ec.drcRev !== ec.rev;
        setText(drcLine, d ? `${d.errors} ${t('errors')}, ${d.warnings} ${t('warnings')}${d.passed ? ` · ${t('passed')}` : ''}${stale ? ` · ${t('out of date')}` : ''} · ${d.profile}` : t('DRC has not run'));
        patchList(drcList, ((d?.violations ?? []) as Json[]).slice(0, 80), {
          key: (v) => `${v.type}|${v.message}`,
          create: (v) => { const n = el('<div class="ec-row" role="button" tabindex="0"><span class="ec-row-sev"></span><span class="ec-row-name"></span></div>'); n.addEventListener('click', () => { if (v.at) ecStage.pcb.focus(v.at[0], v.at[1]); }); return n; },
          update: (n, v) => { setText(q(n, '.ec-row-sev'), v.severity === 'error' ? 'E' : 'W'); setClass(n, 'is-bad', v.severity === 'error'); setText(q(n, '.ec-row-name'), String(v.message)); n.title = String(v.message); },
        });
        const j = ec.job;
        bar.set(j?.progress ?? 0, j ? `${j.phase || t('Routing')} · ${Math.round((j.progress ?? 0) * 100)} %` : '', !!j && j.state !== 'end');
        setDisabled(q<HTMLButtonElement>(route.root, '.u8-btn.is-primary'), ec.jobRunning);
        patchList(ratList, ec.rat.slice(0, 60), {
          key: (r) => `${r.net}|${r.from}|${r.to}`,
          create: (r) => { const n = el('<div class="ec-row" role="button" tabindex="0"><span class="ec-row-id"></span><span class="ec-row-name"></span></div>'); n.addEventListener('click', () => ecStage.pcb.focus((r.a[0] + r.b[0]) / 2, (r.a[1] + r.b[1]) / 2)); return n; },
          update: (n, r) => { setText(q(n, '.ec-row-id'), String(r.net)); setText(q(n, '.ec-row-name'), `${r.from} to ${r.to} · ${fixed(r.length, 2)} mm`); },
        });
      };
      ec.onChange(paint);
      ecStage.onChange(paint);
      void loadRules();
      paint();
      return { show: () => { void loadRules(); paint(); } };
    },
  };
}

import { docStore } from '../ui/doc-store';
import { el, setText } from '../ui/dom';
import type { DockPanel } from '../ui/dock';
import { t } from '../ui/i18n';
import { req } from '../u8/net';
import { button, buttons, checkCtl, dirOf, fixed, guard, numberCtl, reportBox, section, textField } from './kit';
import { ecStage } from './stage';
import { ec, type Json } from './store';

export function outPanel(): DockPanel {
  return {
    id: 'ecout', label: 'Board outputs', icon: 'fab',
    build(body) {
      body.classList.add('ec-panel');
      const fab = section('Fabrication files');
      const folder = textField('Output folder', '');
      const zip = checkCtl('One zip file', false);
      const stepPath = textField('STEP file', '');
      const rep = reportBox(6);
      const run = async (tail: string, payload: Json, lines: (r: Json) => string[]): Promise<void> => {
        const r = await guard(async () => req<Json>('POST', ec.url(`ecad/export/${tail}`), payload));
        rep.set(r ? lines(r) : ['The export was refused. See the message above.'], !r);
      };
      fab.body.append(folder.el, zip.el, stepPath.el,
        buttons(
          button('Gerber and drill', () => void run('gerber', zip.get() ? { out: folder.get().replace(/\/?$/, '') + '.zip', zip: true } : { out: folder.get() }, (r) => [
            `${(r.layers ?? []).length} layers, ${(r.drills ?? []).length} drill files, ${(r.files ?? []).length} files`,
            ...((r.layers ?? []) as Json[]).slice(0, 5).map((l) => `${l.layer}: ${l.apertures} apertures, ${l.flashes} flashes, ${l.draws} draws`),
          ]), 'primary'),
          button('Drill only', () => void run('drill', { out: folder.get() }, (r) => ((r.drills ?? []) as Json[]).map((d) => `${d.function}: ${d.tools} tools, ${d.hits} hits`))),
        ),
        buttons(
          button('IDF', () => void run('idf', { out: folder.get() }, (r) => [`Board ${r.board ?? ''}`, `Library ${r.library ?? ''}`, `${r.components} components, ${r.packages} packages`])),
          button('STEP', () => void run('step', { out: stepPath.get() }, (r) => [`${r.file ?? stepPath.get()}`, `${r.bodies} bodies, ${r.components} components`])),
        ), rep.el);

      const set = section('Export settings');
      const mask = numberCtl('Mask margin (mm)', 0.05), paste = numberCtl('Paste margin (mm)', 0), tent = checkCtl('Tent vias', true);
      set.body.append(mask.el, paste.el, tent.el, buttons(button('Save settings', () => void guard(async () => { await req('PUT', ec.url('ecad/export/settings'), { mask_margin: mask.get() ?? 0.05, paste_margin: paste.get() ?? 0, tent_vias: tent.get() }); }))));

      const link = section('Enclosure link');
      const ref = textField('Enclosure part file', '');
      const lstat = el('<div class="ec-info ec-info-2"></div>');
      const lrep = reportBox(3);
      link.body.append(ref.el, lstat,
        buttons(button('Link', () => void guard(async () => { await ec.call('PUT', 'ecad/link', { ref: { doc: ref.get() } }); })),
          button('Pull outline', () => void guard(async () => { const r = await ec.call<Json>('POST', 'ecad/link/sync'); lrep.set(r ? [`Outline ${(r.outline_points ?? r.points ?? '')} points`, `Holes ${(r.holes ?? r.hole_count ?? '')}`, JSON.stringify(r).slice(0, 120)] : ['Sync refused'], !r); }), 'primary'),
          button('Push outline', () => void guard(async () => { const r = await ec.call<Json>('POST', 'ecad/link/push', {}); lrep.set(r ? [`Sketch ${r.name ?? 'BoardOutline'} written`, JSON.stringify(r).slice(0, 120)] : ['Push refused'], !r); })),
          button('Unlink', () => void guard(async () => { await ec.call('DELETE', 'ecad/link'); }), 'danger')),
        lrep.el);

      const kicad = section('KiCad files');
      const kOn = checkCtl('Allow KiCad file interchange', false, () => void guard(async () => { await req('PUT', ec.url('ecad/kicad'), { enabled: kOn.get() }); }));
      const kPath = textField('KiCad board file', '');
      const krep = reportBox(2);
      kicad.body.append(kOn.el, kPath.el,
        buttons(button('Export', () => void guard(async () => { const r = await req<Json>('POST', ec.url('ecad/export/kicad'), { out: kPath.get() }); krep.set([JSON.stringify(r).slice(0, 140)]); })),
          button('Import', () => void guard(async () => { const r = await ec.call<Json>('POST', 'ecad/import/kicad', { path: kPath.get() }); krep.set(r ? [JSON.stringify(r).slice(0, 140)] : ['Import refused'], !r); }))),
        krep.el);

      const b3 = section('3D board');
      const b3line = el('<div class="ec-info ec-info-2"></div>');
      const comps = checkCtl('Show components', true, () => ecStage.layer?.setComponents(comps.get()));
      b3.body.append(b3line, comps.el, buttons(button('Show 3D board', () => void ecStage.setTab('b3d'), 'primary'), button('Refresh info', () => void loadInfo())));

      body.append(fab.root, set.root, link.root, kicad.root, b3.root);

      async function loadInfo(): Promise<void> {
        if (!ec.docId || !ec.isEcad()) return;
        try { ec.b3d = await req<Json>('GET', ec.url('ecad/board3d')); } catch { ec.b3d = null; }
        try { const s = await req<Json>('GET', ec.url('ecad/export/settings')); mask.set(s.mask_margin ?? 0.05); paste.set(s.paste_margin ?? 0); (tent.input as HTMLInputElement).checked = s.tent_vias !== false; } catch { /* defaults */ }
        try { const k = await req<Json>('GET', ec.url('ecad/kicad')); (kOn.input as HTMLInputElement).checked = !!k.enabled; } catch { /* off */ }
        paint();
      }

      const paint = (): void => {
        const cur = docStore.current();
        const dir = dirOf(cur?.path);
        const nm = String(ec.sum?.name ?? 'board').replace(/[^A-Za-z0-9_-]+/g, '_');
        if (dir) { folder.set(`${dir}/fab`); stepPath.set(`${dir}/${nm}.step`); kPath.set(`${dir}/${nm}.kicad_pcb`); ref.set(ec.link?.ref?.doc ?? ref.get() ?? ''); }
        const l = ec.link;
        setText(lstat, !l ? '' : l.linked ? `${t('Linked')}${l.stale ? ` · ${t('part changed since the last pull')}` : ` · ${t('in sync')}`}${l.problem ? ` · ${l.problem}` : ''}` : t('Not linked'));
        const b = ec.b3d;
        setText(b3line, b ? `${fixed(b.thickness, 3)} mm · ${b.components} ${t('components')} · ${b.holes} ${t('holes')} · ${b.valid && b.closed ? t('valid solid') : t('check the solid')}` : '');
      };
      ec.onChange(paint);
      void loadInfo();
      return { show: () => { void loadInfo(); paint(); } };
    },
  };
}

import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setText, setTitle } from '../ui/dom';
import { t } from '../ui/i18n';
import { dv, type BreakSpec, type ViewInfo } from './api';
import * as rt from './runtime';
import { drawStore } from './store';
import { button, checkCtl, numberCtl, readout, row, section, selectCtl, textCtl } from './ui';

const STATUS: Record<string, string> = { ok: 'Up to date', stale: 'Out of date', error: 'Could not be built', empty: 'Nothing to show' };
const KIND: Record<string, string> = { base: 'Base view', projected: 'Projected view', auxiliary: 'Auxiliary view', section: 'Section view', detail: 'Detail view', broken: 'Broken view', crop: 'Cropped view' };

export function propsPanel(): DockPanel {
  return {
    id: 'viewprops',
    label: 'View Properties',
    icon: 'dwProps',
    order: 45,
    build(body) {
      body.classList.add('dw-panel');
      const note = el('<p class="dw-note dw-hold"></p>');
      setText(note, t('Select a view on the sheet to change it.'));
      let cur: ViewInfo | null = null;
      const edit = (changes: Record<string, unknown>): void => {
        const v = cur;
        if (v) void drawStore.run((id) => dv.patch(id, v.handle, { changes }));
      };

      const id = section('View');
      const name = readout('Name');
      const kind = readout('Kind');
      const label = textCtl('Label', (v) => edit({ label: v }));
      const showLabel = checkCtl('Show label', (v) => edit({ show: { label: v } }));
      const scale = textCtl('Scale', (v) => { if (v.trim()) edit({ scale: v.trim() }); }, true);
      const px = numberCtl('Sheet X', (v) => { if (v !== null && cur) edit({ position: [v, cur.position[1]] }); });
      const py = numberCtl('Sheet Y', (v) => { if (v !== null && cur) edit({ position: [cur.position[0], v] }); });
      const source = readout('Model');
      id.body.append(name.el, kind.el, label.el, showLabel.el, scale.el, px.el, py.el, source.el);

      const edges = section('Edges');
      const mode = selectCtl('Mode', [['auto', 'Automatic'], ['exact', 'Exact'], ['draft', 'Draft']], (v) => edit({ mode: v }));
      const hidden = checkCtl('Hidden edges', (v) => edit({ show: { hidden: v } }));
      const tangent = checkCtl('Tangent edges', (v) => edit({ show: { tangent: v } }));
      const sil = checkCtl('Silhouette edges', (v) => edit({ show: { silhouette: v } }));
      const seam = checkCtl('Seam edges', (v) => edit({ show: { seam: v } }));
      const hatch = checkCtl('Section hatching', (v) => edit({ show: { hatch: v } }));
      const auto = checkCtl('Update when the model changes', (v) => edit({ auto: v }));
      edges.body.append(mode.el, hidden.el, tangent.el, sil.el, seam.el, hatch.el, auto.el);

      const state = section('Status');
      const status = el('<div class="dw-status"><span class="dw-dot"></span><span class="dw-status-text"></span></div>');
      const stats = readout('Build');
      const msg = el('<p class="dw-note dw-hold"></p>');
      const upd = button('Update view', () => { if (cur) void rt.updateOne(cur); }, 'primary');
      const del = button('Delete', () => { if (cur) void rt.deleteView(cur, false); }, 'danger');
      const delC = button('Delete with children', () => { if (cur) void rt.deleteView(cur, true); }, 'danger');
      state.body.append(status, stats.el, msg, row(upd, del, delC));

      const typed = section('Type settings');
      const secKind = readout('Section');
      const flip = button('Flip direction', () => {
        const v = cur;
        if (!v || !v.section.kind) return;
        void drawStore.run((i) => dv.patch(i, v.handle, { changes: { section: { flip: !v.section.flip } } }));
      });
      const detR = numberCtl('Detail radius (mm)', (v) => {
        const c = cur;
        if (c && v !== null && v > 0) void drawStore.run((i) => dv.patch(i, c.handle, { changes: { detail: { radius: v } } }));
      });
      const breaksList = el('<div class="dw-list dw-breaks"></div>');
      const clearCrop = button('Remove crop', () => { const v = cur; if (v) void drawStore.run((i) => dv.patch(i, v.handle, { clear_crop: true })); });
      const breakBtn = button('Add break...', () => rt.armBreak());
      const cropBtn = button('Crop...', () => rt.armCrop());
      typed.body.append(secKind.el, flip, detR.el, breaksList, row(breakBtn, cropBtn, clearCrop));

      body.append(note, id.root, edges.root, state.root, typed.root);
      const sections = [id.root, edges.root, state.root, typed.root];

      const paintBreaks = (v: ViewInfo | null): void => {
        const list = (v?.broken.breaks ?? []).map((b, i) => ({ b, i }));
        patchList(breaksList, list, {
          key: (r) => String(r.i),
          create: (r) => {
            const n = el(`<div class="dw-row"><span class="dw-row-name"></span><button class="dw-row-up" type="button" aria-label="Remove break">x</button></div>`);
            q(n, 'button').addEventListener('click', () => {
              const c = cur;
              if (!c) return;
              const rest: BreakSpec[] = (c.broken.breaks ?? []).filter((_, k) => k !== r.i);
              void drawStore.run((i) => dv.patch(i, c.handle, rest.length ? { breaks: rest } : { clear_breaks: true }));
            });
            return n;
          },
          update: (n, r) => setText(q(n, '.dw-row-name'), `${r.b.axis.toUpperCase()} ${r.b.lo.toFixed(1)} to ${r.b.hi.toFixed(1)}, ${r.b.style}`),
        });
      };

      const paint = (): void => {
        const v = drawStore.selected;
        cur = v;
        setText(note, v ? t('Changes apply to the selected view.') : t('Select a view on the sheet to change it.'));
        for (const s of sections) setClass(s, 'is-idle', !v);
        paintBreaks(v);
        if (!v) return;
        name.set(v.name);
        kind.set(t(KIND[v.vtype] ?? v.vtype));
        label.set(v.label);
        showLabel.set(v.show.label);
        scale.set(v.scaleText);
        px.set(v.position[0]);
        py.set(v.position[1]);
        source.set(v.source.doc || t('This document'));
        mode.set(v.mode);
        hidden.set(v.show.hidden);
        tangent.set(v.show.tangent);
        sil.set(v.show.silhouette);
        seam.set(v.show.seam);
        hatch.set(v.show.hatch);
        auto.set(v.auto);
        const st = v.state.status;
        status.className = `dw-status is-${st}`;
        setText(q(status, '.dw-status-text'), t(STATUS[st] ?? st));
        const s = v.state.stats;
        stats.set(`${v.state.mode_used ?? ''} ${v.state.ms ? `${Math.round(v.state.ms)} ms` : ''}${s?.faces ? `, ${s.faces} faces` : ''}`.trim());
        setText(msg, v.state.message);
        secKind.set(`${v.section.kind ?? ''} ${v.section.letter ?? ''}`.trim() || '-');
        if (flip.disabled !== !v.section.kind) flip.disabled = !v.section.kind;
        detR.disable(!v.detail.radius);
        detR.set(v.detail.radius ?? null);
        setTitle(upd, t('Rebuild this view from the model'));
      };
      drawStore.onChange(paint);
      paint();
      return { show: paint };
    },
  };
}

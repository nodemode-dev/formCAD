import type { DockPanel } from '../ui/dock';
import { pickPath, type FileKind } from '../ui/file-dialogs';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setTitle } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { selection } from '../ui/panels/selection-bus';
import { dv } from './api';
import * as rt from './runtime';
import { palette, SCALES, STANDARD_VIEWS } from './state';
import { drawStore } from './store';
import { button, row, section, selectCtl, textCtl } from './ui';

const OPEN_FCAD_KIND: FileKind = { name: 'FormCAD documents', extensions: ['fcad'] };
const GLYPH: Record<string, string> = { front: 'dwVFront', back: 'dwVBack', left: 'dwVLeft', right: 'dwVRight', top: 'dwVTop', bottom: 'dwVBottom' };

interface Tile { id: string; icon: string; label: string; run: () => void }

const ANNOT: Tile[] = [
  { id: 'dim', icon: 'dwDim', label: 'Dimension', run: () => rt.armDim() },
  { id: 'frame', icon: 'dwFrame', label: 'Tolerance frame', run: () => rt.armFrame() },
  { id: 'datum', icon: 'dwDatum', label: 'Datum symbol', run: () => rt.armDatum() },
  { id: 'balloon', icon: 'dwBalloon', label: 'Balloon', run: () => rt.armBalloon() },
  { id: 'bom', icon: 'dwBom', label: 'Parts list', run: () => rt.armBom() },
  { id: 'finish', icon: 'dwFinish', label: 'Finish mark', run: () => rt.armFinish() },
];

const VIEWTOOLS: Tile[] = [
  { id: 'section', icon: 'dwSection', label: 'Section', run: () => rt.armSection() },
  { id: 'detail', icon: 'dwDetail', label: 'Detail', run: () => rt.armDetail() },
  { id: 'aux', icon: 'dwAux', label: 'Auxiliary', run: () => rt.armAux() },
  { id: 'break', icon: 'dwBreak', label: 'Break', run: () => rt.armBreak() },
  { id: 'crop', icon: 'dwCrop', label: 'Crop', run: () => rt.armCrop() },
  { id: 'flat', icon: 'smFlat', label: 'Flat pattern', run: () => rt.armFlat() },
];

function tiles(list: Tile[], cls: string): { root: HTMLElement; nodes: Map<string, HTMLButtonElement> } {
  const root = el(`<div class="dw-tiles ${cls}"></div>`);
  const nodes = new Map<string, HTMLButtonElement>();
  for (const x of list) {
    const b = el<HTMLButtonElement>(`<button class="dw-tile" type="button" data-tool="${x.id}">${icon(x.icon, 20)}<span></span></button>`);
    setText(q(b, 'span'), t(x.label));
    setTitle(b, t(x.label));
    b.addEventListener('click', x.run);
    nodes.set(x.id, b);
    root.appendChild(b);
  }
  return { root, nodes };
}

export function palettePanel(): DockPanel {
  return {
    id: 'drawviews',
    label: 'Drawing Views',
    icon: 'dwViews',
    order: 44,
    build(body) {
      body.classList.add('dw-panel');
      const note = el('<p class="dw-note dw-sheetnote dw-hold"></p>');

      const model = section('Model');
      const src = selectCtl('Show', [['', 'This document'], ['file', 'Another file']], () => onSource());
      const fileRead = el('<div class="dw-file" hidden></div>');
      const pick = button('Choose file...', () => { void chooseFile(); });
      const comp = textCtl('Body or component', (v) => { palette.component = v.trim(); }, true);
      comp.input.setAttribute('placeholder', t('All'));
      model.body.append(src.el, fileRead, comp.el);
      const fileRow = row(pick);
      fileRow.hidden = true;
      model.body.appendChild(fileRow);

      const std = section('Standard views');
      const scaleCtl = textCtl('Scale', (v) => { palette.scale = v.trim() || '1:1'; }, true);
      const dl = el('<datalist id="dw-scales"></datalist>');
      for (const s of SCALES) { const o = document.createElement('option'); o.value = s; dl.appendChild(o); }
      scaleCtl.input.setAttribute('list', 'dw-scales');
      scaleCtl.set(palette.scale);
      const modeCtl = selectCtl('Edges', [['auto', 'Automatic'], ['exact', 'Exact'], ['draft', 'Draft']], (v) => { palette.mode = v as typeof palette.mode; });
      const angle = selectCtl('Projection', [['third', 'Third angle'], ['first', 'First angle']], (v) => {
        void drawStore.run((id) => dv.projection(id, drawStore.layout, v as 'first' | 'third'));
      });
      const stdTiles = tiles(STANDARD_VIEWS.map((v) => ({ id: v.id, icon: GLYPH[v.id] ?? 'dwVIso', label: v.label, run: () => rt.armBase(v.id) })), 'dw-tiles-std');
      std.body.append(stdTiles.root, scaleCtl.el, dl, modeCtl.el, angle.el);

      const vt = section('View tools');
      const viewTiles = tiles(VIEWTOOLS, 'dw-tiles-tools');
      vt.body.appendChild(viewTiles.root);

      const list = section('Views on this sheet');
      const rows = el('<div class="dw-list" role="listbox" aria-label="Views"></div>');
      const empty = el('<p class="dw-note dw-listnote"></p>');
      const upStale = button('Update out of date', () => { void rt.updateViews(false); });
      const upAll = button('Update all', () => { void rt.updateViews(true); });
      list.body.append(rows, empty, row(upStale, upAll));

      const ann = section('Annotate');
      const annTiles = tiles(ANNOT, 'dw-tiles-tools');
      const bomUp = button('Update parts lists', () => { void rt.bomUpdate(); });
      const autoB = button('Auto balloons', () => { void rt.autoBalloons(); });
      const cm = button('Centre marks', () => { void rt.viewAction('centermarks', 'Centre marks: '); });
      const hatch = button('Section hatch', () => { void rt.viewAction('sectionhatch', 'Hatches: '); });
      const frameEdit = button('Edit frame...', () => { void rt.openFrameEditor(); });
      const title = button('Title block...', () => rt.openTitleBlock());
      const sets = button('Settings...', () => rt.openSettings());
      ann.body.append(annTiles.root, row(autoB, bomUp), row(cm, hatch), row(frameEdit, title), row(sets));

      body.append(note, model.root, std.root, vt.root, list.root, ann.root);

      const onSource = (): void => {
        if (src.get() === '') palette.sourceDoc = '';
        paint();
        if (src.get() === 'file' && !palette.sourceDoc) void chooseFile();
      };
      async function chooseFile(): Promise<void> {
        const abs = await pickPath('open', 'Choose Model File', '', [OPEN_FCAD_KIND], 'Choose');
        if (!abs) { if (!palette.sourceDoc) src.set(''); paint(); return; }
        const rel = await rt.sourceRelative(abs);
        if (!rel) { if (!palette.sourceDoc) src.set(''); paint(); return; }
        palette.sourceDoc = rel;
        paint();
      }

      const paint = (): void => {
        const inLayout = drawStore.inLayout;
        setText(note, inLayout ? t('Pick a view, then click the sheet to place it.') : t('Open a layout tab to place views on a sheet.'));
        const sel = drawStore.selected;
        const active = rt.activeTool();
        setClass(body, 'is-off', !inLayout);
        for (const b of body.querySelectorAll<HTMLButtonElement>('.dw-tile, .dw-btn, select, input')) setDisabled(b, !inLayout && !b.closest('.dw-file'));
        for (const [id, b] of stdTiles.nodes) setClass(b, 'is-on', active === `base:${id}`);
        for (const [id, b] of viewTiles.nodes) setClass(b, 'is-on', active === id);
        for (const [id, b] of annTiles.nodes) setClass(b, 'is-on', active === id);
        src.set(palette.sourceDoc ? 'file' : '');
        setText(fileRead, palette.sourceDoc);
        setHidden(fileRead, !palette.sourceDoc);
        setHidden(fileRow, src.get() !== 'file');
        angle.set(drawStore.projection);
        patchList(rows, drawStore.views, {
          key: (v) => String(v.handle),
          create: (v) => {
            const r = el(`<div class="dw-row" role="option"><span class="dw-dot"></span><span class="dw-row-name"></span><span class="dw-row-sub"></span><button class="dw-row-up" type="button">${icon('dwUpdate', 14)}</button></div>`);
            r.addEventListener('click', (e) => {
              if ((e.target as HTMLElement).closest('.dw-row-up')) { void rt.updateOne(v); return; }
              selection.select([v.handle]);
            });
            return r;
          },
          update: (n, v) => {
            setText(q(n, '.dw-row-name'), `${v.name}  ${v.label || v.vtype}`);
            setText(q(n, '.dw-row-sub'), v.scaleText);
            setClass(n, 'is-selected', sel?.handle === v.handle);
            setClass(n, 'is-stale', v.state.status === 'stale');
            setClass(n, 'is-error', v.state.status === 'error');
            const up = q(n, '.dw-row-up');
            setHidden(up, v.state.status !== 'stale');
            setTitle(up, t('Update this view'));
            setTitle(n, v.state.message || v.vtype);
          },
        });
        setText(empty, drawStore.views.length ? '' : t('No views on this sheet yet.'));
        setDisabled(upStale as HTMLButtonElement, !inLayout || drawStore.stale().length === 0);
      };
      drawStore.onChange(paint);
      rt.toolHost()?.onChange(paint);
      document.addEventListener('formcad:draw-host', () => rt.toolHost()?.onChange(paint));
      paint();
      return { show: paint };
    },
  };
}

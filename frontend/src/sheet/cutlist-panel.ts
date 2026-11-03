import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import type { CutBend } from './api';
import { sheetStore } from './store';
import { fmt } from './ui';

const FACTS: Array<[string, string, string]> = [
  ['thickness', 'Thickness', 'mm'],
  ['material', 'Material', ''],
  ['size', 'Blank size', 'mm'],
  ['area', 'Blank area', 'mm2'],
  ['outer', 'Cutting length, outline', 'mm'],
  ['inner', 'Cutting length, cutouts', 'mm'],
  ['bends', 'Bends', ''],
  ['cutouts', 'Cutouts', ''],
];

export function cutListPanel(run: { toggle: () => void; exportDxf: () => void; rule: () => void; tables: () => void }): DockPanel {
  return {
    id: 'sm-cutlist',
    label: 'Cut List',
    icon: 'smCutList',
    order: 46,
    build(body) {
      body.classList.add('sm-panel');
      const note = el('<p class="sm-note sm-hold"></p>');
      const facts = el('<dl class="sm-facts"></dl>');
      for (const [key, label, unit] of FACTS) {
        const dt = el(`<dt data-k="${key}"></dt>`);
        const dd = el(`<dd data-k="${key}"><span class="sm-v"></span><span class="sm-u"></span></dd>`);
        setText(dt, t(label));
        setText(q(dd, '.sm-u'), unit);
        facts.append(dt, dd);
      }
      const head = el('<div class="sm-bhead"><span></span><span></span><span></span><span></span><span></span></div>');
      ['Bend', 'Direction', 'Angle', 'Radius', 'Allowance'].forEach((w, i) => setText(head.children[i] as HTMLElement, t(w)));
      const list = el('<div class="sm-blist" role="list"></div>');
      const warn = el('<p class="sm-note sm-warn" role="alert"></p>');
      const tools = el('<div class="sm-tools"></div>');
      const mk = (ic: string, label: string, fn: () => void): HTMLButtonElement => {
        const b = el<HTMLButtonElement>(`<button class="cv-btn sm-btn" type="button">${icon(ic, 14)}<span></span></button>`);
        setText(q(b, 'span:not(.icon)'), t(label));
        b.addEventListener('click', fn);
        tools.appendChild(b);
        return b;
      };
      const tog = mk('smFlat', 'Flat pattern', run.toggle);
      const exp = mk('smDxf', 'Export DXF...', run.exportDxf);
      const rule = mk('smRule', 'Rule...', run.rule);
      const tbl = mk('smTable', 'Tables...', run.tables);
      body.append(note, tools, facts, head, list, warn);

      const paint = (): void => {
        const on = sheetStore.isSheet;
        setText(note, on ? '' : t('Add a base flange or convert a solid to sheet metal to see its cut list.'));
        for (const b of [tog, exp, rule, tbl]) setDisabled(b, !on);
        setClass(tog, 'is-on', sheetStore.on);
        tog.setAttribute('aria-pressed', sheetStore.on ? 'true' : 'false');
        const c = sheetStore.cut;
        const set = (k: string, v: string): void => { setText(q(facts, `dd[data-k="${k}"] .sm-v`), v); };
        set('thickness', c ? fmt(c.thickness, 4) : '');
        set('material', c ? (c.material || '-') : '');
        set('size', c ? `${fmt(c.bbox_length, 4)} x ${fmt(c.bbox_width, 4)}` : '');
        set('area', c ? fmt(c.blank_area, 3) : '');
        set('outer', c ? fmt(c.cutting_length_outside, 4) : '');
        set('inner', c ? fmt(c.cutting_length_inside, 4) : '');
        set('bends', c ? String(c.num_bends) : '');
        set('cutouts', c ? String(c.num_cutouts) : '');
        patchList<CutBend>(list, c?.bends ?? [], {
          key: (b) => b.id,
          create: () => el('<div class="sm-brow" role="listitem"><span class="sm-bid"></span><span class="sm-bdir"></span><span class="sm-bang"></span><span class="sm-brad"></span><span class="sm-bba"></span></div>'),
          update: (n, b) => {
            setText(q(n, '.sm-bid'), b.record ?? b.id);
            setText(q(n, '.sm-bdir'), t(b.direction === 'up' ? 'Up' : 'Down'));
            setText(q(n, '.sm-bang'), fmt((b.angle * 180) / Math.PI, 2));
            setText(q(n, '.sm-brad'), fmt(b.radius, 4));
            setText(q(n, '.sm-bba'), fmt(b.ba, 4));
            setClass(n, 'is-up', b.direction === 'up');
            setClass(n, 'is-down', b.direction !== 'up');
          },
        });
        setText(warn, sheetStore.error);
      };
      sheetStore.onChange(paint);
      paint();
      return { show: () => { sheetStore.refresh(0); paint(); } };
    },
  };
}

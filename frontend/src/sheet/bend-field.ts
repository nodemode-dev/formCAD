import type { ParamSchema } from '../part/api';
import type { FieldView } from '../part/fields';
import { el, patchList, q, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import type { BendRecord } from './api';
import { fmt } from './ui';
import { sheetStore } from './store';

interface Pair { id: number; a: string; b: string }

let pairId = 0;

const describe = (b: BendRecord): string => `${b.id} ${t(b.direction === 'up' ? 'up' : 'down')} ${fmt((b.angle * 180) / Math.PI, 1)} R${fmt(b.radius, 3)}`;

export function bendField(p: ParamSchema, change: () => void, pairs: boolean): FieldView {
  const row = el<HTMLElement>('<div class="pp-row sm-bendfield"><span class="pp-lab"></span><div class="sm-bpick"></div></div>');
  setText(q(row, '.pp-lab'), t(p.label || p.name));
  const host = q(row, '.sm-bpick');
  const picked = new Set<string>();
  let rows: Pair[] = [];

  const paintBends = (): void => {
    patchList<BendRecord>(host, sheetStore.bends, {
      key: (b) => b.id,
      create: (b) => {
        const n = el<HTMLElement>('<label class="sm-bchk"><input type="checkbox"><span></span></label>');
        const box = q<HTMLInputElement>(n, 'input');
        box.addEventListener('change', () => { if (box.checked) picked.add(b.id); else picked.delete(b.id); change(); });
        return n;
      },
      update: (n, b) => {
        const box = q<HTMLInputElement>(n, 'input');
        if (box.checked !== picked.has(b.id)) box.checked = picked.has(b.id);
        setText(q(n, 'span'), describe(b));
      },
    });
  };

  const options = (sel: HTMLSelectElement): void => {
    patchList<BendRecord>(sel, sheetStore.bends, {
      key: (b) => b.id,
      create: (b) => { const o = document.createElement('option'); o.value = b.id; return o; },
      update: (n, b) => setText(n, describe(b)),
    });
  };

  const paintPairs = (): void => {
    patchList<Pair>(host, rows, {
      key: (r) => String(r.id),
      create: (r) => {
        const n = el<HTMLElement>(`<div class="sm-pair"><select class="cv-input" data-s="a"></select><select class="cv-input" data-s="b"></select><button class="cv-icon-btn" type="button" aria-label="Remove">${icon('close', 12)}</button></div>`);
        for (const key of ['a', 'b'] as const) {
          const sel = q<HTMLSelectElement>(n, `select[data-s="${key}"]`);
          sel.addEventListener('change', () => { r[key] = sel.value; change(); });
        }
        q(n, 'button').addEventListener('click', () => { rows = rows.filter((x) => x.id !== r.id); paintPairs(); change(); });
        return n;
      },
      update: (n, r) => {
        for (const key of ['a', 'b'] as const) {
          const sel = q<HTMLSelectElement>(n, `select[data-s="${key}"]`);
          options(sel);
          if (sel.value !== r[key]) sel.value = r[key];
          if (sel.value !== r[key]) r[key] = sel.value;
        }
      },
    });
  };

  let add: HTMLButtonElement | null = null;
  if (pairs) {
    add = el<HTMLButtonElement>('<button class="cv-btn sm-addpair" type="button"></button>');
    setText(add, t('Add corner'));
    add.addEventListener('click', () => {
      const first = sheetStore.bends[0]?.id ?? '';
      rows.push({ id: ++pairId, a: first, b: sheetStore.bends[1]?.id ?? first });
      paintPairs();
      change();
    });
    row.appendChild(add);
  }

  const paint = (): void => { if (pairs) paintPairs(); else paintBends(); };
  sheetStore.onChange(paint);
  paint();

  return {
    row,
    name: p.name,
    set: (v) => {
      picked.clear();
      rows = [];
      if (Array.isArray(v)) {
        if (pairs) for (const x of v) if (Array.isArray(x) && x.length === 2) rows.push({ id: ++pairId, a: String(x[0]), b: String(x[1]) });
        if (!pairs) for (const x of v) picked.add(String(x));
      }
      paint();
    },
    get: () => {
      if (pairs) return rows.length ? rows.map((r) => [r.a, r.b]) : null;
      const ids = sheetStore.bends.map((b) => b.id).filter((id) => picked.has(id));
      return ids.length ? ids : null;
    },
    show: (on) => setHidden(row, !on),
    bad: () => false,
  };
}

import { el, patchList, q, setText } from '../dom';
import { t } from '../i18n';
import { loadTables } from '../dialogs/engine';
import { Popover } from './popover';
import { aciHex } from './pref-rows';

export const LINEWEIGHT_STEPS = [-3, 0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211];
export const lineweightLabel = (v: number): string => (v < 0 ? 'Default' : `${(v / 100).toFixed(2)} mm`);

const LIBRARY_LINETYPES = ['BORDER', 'CENTER', 'CENTER2', 'CENTERX2', 'DASHDOT', 'DASHDOT2', 'DASHED', 'DASHED2', 'DASHEDX2', 'DIVIDE', 'DOT', 'DOT2', 'HIDDEN', 'HIDDEN2', 'HIDDENX2', 'PHANTOM', 'PHANTOM2', 'FENCELINE1', 'ZIGZAG'];
const STANDARD_NINE = [1, 2, 3, 4, 5, 6, 7, 8, 9];
const GRAYS = [250, 251, 252, 253, 254, 255];
const SHADE_ORDER = [0, 2, 4, 6, 8, 1, 3, 5, 7, 9];

export const colorHex = (c: number | string): string => (typeof c === 'string' ? c : aciHex(c));

let colorPop: Popover | null = null;
let colorCb: ((v: number | string) => void) | null = null;
let colorNow: HTMLElement | null = null;
let colorCur = 7;

function buildColor(): Popover {
  const p = new Popover('lm-pop-color', 300);
  const cells: string[] = [];
  for (const shade of SHADE_ORDER) for (let hue = 0; hue < 24; hue++) {
    const n = 10 + hue * 10 + shade;
    cells.push(`<button class="lm-cell" type="button" data-aci="${n}" title="${t('Index color')}: ${n}" style="--c:${aciHex(n)}"></button>`);
  }
  const wide = (n: number): string => `<button class="lm-cell lm-cell-wide" type="button" data-aci="${n}" title="${t('Index color')}: ${n}" style="--c:${aciHex(n)}"></button>`;
  p.root.innerHTML =
    `<div class="lm-pop-tabs"><button type="button" class="lm-pop-tab is-on" data-tab="idx">${t('Index Color')}</button><button type="button" class="lm-pop-tab" data-tab="true">${t('True Color')}</button></div>` +
    `<div class="lm-pane" data-pane="idx"><div class="lm-aci">${cells.join('')}</div><div class="lm-aci-row">${STANDARD_NINE.map(wide).join('')}</div><div class="lm-aci-row">${GRAYS.map(wide).join('')}</div></div>` +
    '<div class="lm-pane" data-pane="true" hidden><div class="lm-rgb"><label>R<input class="cv-input" type="number" min="0" max="255" value="255" data-ch="0"></label><label>G<input class="cv-input" type="number" min="0" max="255" value="255" data-ch="1"></label><label>B<input class="cv-input" type="number" min="0" max="255" value="255" data-ch="2"></label></div>' +
    `<span class="lm-rgb-sw"></span><button class="cv-btn cv-btn-primary" type="button" data-apply>${t('Apply true color')}</button></div>` +
    '<div class="lm-pop-now"></div>';
  colorNow = q(p.root, '.lm-pop-now');
  p.root.addEventListener('click', (e) => {
    const tgt = e.target as HTMLElement;
    const cell = tgt.closest<HTMLElement>('[data-aci]');
    if (cell) { const v = Number(cell.dataset.aci); p.hide(); colorCb?.(v); return; }
    const tab = tgt.closest<HTMLElement>('[data-tab]');
    if (tab) {
      for (const b of Array.from(p.root.querySelectorAll<HTMLElement>('.lm-pop-tab'))) b.classList.toggle('is-on', b === tab);
      for (const pane of Array.from(p.root.querySelectorAll<HTMLElement>('.lm-pane'))) pane.hidden = pane.dataset.pane !== tab.dataset.tab;
      return;
    }
    if (tgt.closest('[data-apply]')) {
      const v = Array.from(p.root.querySelectorAll<HTMLInputElement>('[data-ch]')).map((i) => Math.max(0, Math.min(255, Math.round(Number(i.value) || 0))));
      const hex = `#${v.map((n) => n.toString(16).padStart(2, '0')).join('').toUpperCase()}`;
      p.hide();
      colorCb?.(hex);
    }
  });
  const sw = q(p.root, '.lm-rgb-sw');
  p.root.addEventListener('input', () => {
    const v = Array.from(p.root.querySelectorAll<HTMLInputElement>('[data-ch]')).map((i) => Math.max(0, Math.min(255, Math.round(Number(i.value) || 0))));
    sw.style.setProperty('--c', `rgb(${v.join(',')})`);
  });
  return p;
}

export function pickColor(anchor: HTMLElement, current: number | string, cb: (v: number | string) => void): void {
  colorPop ??= buildColor();
  colorCb = cb;
  colorCur = typeof current === 'number' ? current : 0;
  for (const c of Array.from(colorPop.root.querySelectorAll<HTMLElement>('[data-aci]'))) c.classList.toggle('is-cur', Number(c.dataset.aci) === colorCur);
  if (colorNow) setText(colorNow, `${t('Current')}: ${typeof current === 'number' ? current : current}`);
  colorPop.show(anchor);
}

let ltPop: Popover | null = null;
let ltList: HTMLElement | null = null;
let ltMore: HTMLElement | null = null;
let ltCb: ((name: string) => void) | null = null;

interface LtRow { key: string; loaded: boolean; cur: boolean }

function ltPatch(rows: LtRow[], host: HTMLElement): void {
  patchList(host, rows, {
    key: (r) => r.key,
    create: (r) => {
      const b = el<HTMLButtonElement>('<button class="lm-lt" type="button"><span class="lm-lt-name"></span><span class="lm-lt-line"></span></button>');
      setText(q(b, '.lm-lt-name'), r.key);
      b.dataset.name = r.key;
      b.classList.toggle('is-cur', r.cur);
      return b;
    },
    update: (n, r) => { n.classList.toggle('is-cur', r.cur); },
  });
}

function buildLt(): Popover {
  const p = new Popover('lm-pop-lt', 240);
  p.root.innerHTML = `<div class="lm-pop-head">${t('Loaded linetypes')}</div><div class="lm-lt-list"></div><div class="lm-pop-sep"></div><button class="lm-lt lm-lt-load" type="button">${t('Load...')}</button><div class="lm-lt-list lm-lt-more" hidden></div>`;
  ltList = q(p.root, '.lm-lt-list');
  ltMore = q(p.root, '.lm-lt-more');
  p.root.addEventListener('click', (e) => {
    const tgt = e.target as HTMLElement;
    if (tgt.closest('.lm-lt-load')) { if (ltMore) ltMore.hidden = !ltMore.hidden; return; }
    const b = tgt.closest<HTMLElement>('[data-name]');
    if (b?.dataset.name) { p.hide(); ltCb?.(b.dataset.name); }
  });
  return p;
}

export async function pickLinetype(anchor: HTMLElement, current: string, cb: (name: string) => void): Promise<void> {
  ltPop ??= buildLt();
  ltCb = cb;
  const tables = await loadTables();
  const loaded = (tables?.linetypes ?? []).map((l) => l.name).filter((n) => !/^by(layer|block)$/i.test(n));
  const have = new Set(loaded.map((n) => n.toUpperCase()));
  if (ltList) ltPatch(loaded.map((n) => ({ key: n, loaded: true, cur: n.toUpperCase() === current.toUpperCase() })), ltList);
  if (ltMore) ltPatch(LIBRARY_LINETYPES.filter((n) => !have.has(n)).map((n) => ({ key: n, loaded: false, cur: false })), ltMore);
  ltPop.show(anchor);
}

let lwPop: Popover | null = null;
let lwCb: ((v: number) => void) | null = null;

export function pickLineweight(anchor: HTMLElement, current: number, cb: (v: number) => void): void {
  if (!lwPop) {
    lwPop = new Popover('lm-pop-lw', 170);
    lwPop.root.innerHTML = LINEWEIGHT_STEPS.map((v) => `<button class="lm-lw" type="button" data-lw="${v}"><span class="lm-lw-bar" style="--h:${v < 0 ? 1 : Math.max(1, Math.min(6, v / 30))}px"></span><span>${t(lineweightLabel(v))}</span></button>`).join('');
    const pop = lwPop;
    pop.root.addEventListener('click', (e) => {
      const b = (e.target as HTMLElement).closest<HTMLElement>('[data-lw]');
      if (b) { pop.hide(); lwCb?.(Number(b.dataset.lw)); }
    });
  }
  lwCb = cb;
  for (const b of Array.from(lwPop.root.querySelectorAll<HTMLElement>('[data-lw]'))) b.classList.toggle('is-cur', Number(b.dataset.lw) === current);
  lwPop.show(anchor);
}

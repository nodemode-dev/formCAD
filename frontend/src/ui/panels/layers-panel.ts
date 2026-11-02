import type { LayerRow } from '../../io/api-cad';
import type { DockPanel } from '../dock';
import { docStore } from '../doc-store';
import { sendCommand } from '../dialogs/engine';
import { el, patchList, q, setClass, setText, setTitle } from '../dom';
import { icon } from '../icons';
import { t } from '../i18n';
import { layerFeed } from './layer-data';
import { colorHex } from './layer-pickers';
import { openLayerManager } from './layer-manager';
import { Popover } from './popover';

const TOOLS: Array<[string, string, string, () => void]> = [
  ['layers', 'Layer Properties', 'manager', () => { openLayerManager(); }],
  ['layer', "Make Object's Layer Current", 'laymcur', () => sendCommand('laymcur')],
  ['layerMatch', 'Match Layer', 'laymch', () => sendCommand('laymch')],
  ['layerPrev', 'Previous Layer', 'layerp', () => sendCommand('layerp')],
  ['layerIso', 'Isolate Layer', 'layiso', () => sendCommand('layiso')],
  ['bulbOff', 'Turn Off Layer', 'layoff', () => sendCommand('layoff')],
  ['snow', 'Freeze Layer', 'layfrz', () => sendCommand('layfrz')],
  ['lock', 'Lock Layer', 'laylck', () => sendCommand('laylck')],
  ['unlock', 'Unlock Layer', 'layulk', () => sendCommand('layulk')],
];

const rowHtml = (): string =>
  `<button class="lp-t" type="button" data-t="on">${icon('bulbOn', 14)}</button>` +
  `<button class="lp-t" type="button" data-t="frozen">${icon('sun', 14)}</button>` +
  `<button class="lp-t" type="button" data-t="locked">${icon('unlock', 14)}</button>` +
  '<i class="lm-sw"></i><button class="lp-name" type="button"></button>';

function fillRow(n: HTMLElement, r: LayerRow): void {
  setClass(n, 'is-current', r.current);
  setClass(n, 'is-off', !r.on);
  const tog = (key: string, on: boolean, a: string, b: string): void => {
    const btn = q<HTMLButtonElement>(n, `[data-t="${key}"]`);
    setClass(btn, 'is-off', !on);
    if (btn.dataset.s !== (on ? '1' : '0')) { btn.dataset.s = on ? '1' : '0'; btn.innerHTML = icon(on ? a : b, 14); }
  };
  tog('on', r.on, 'bulbOn', 'bulbOff');
  tog('frozen', !r.frozen, 'sun', 'snow');
  tog('locked', !r.locked, 'unlock', 'lock');
  q(n, '.lm-sw').style.setProperty('--c', colorHex(r.color));
  setText(q(n, '.lp-name'), r.name);
}

const rowDef = {
  key: (r: LayerRow): string => r.name,
  create: (r: LayerRow): HTMLElement => { const n = el<HTMLElement>(`<div class="lp-row">${rowHtml()}</div>`); fillRow(n, r); return n; },
  update: fillRow,
};

export function layersPanel(): DockPanel {
  return {
    id: 'layers',
    label: 'Layers',
    icon: 'layers',
    order: 2,
    build: (body) => {
      body.appendChild(el(
        '<div class="lp"><div class="lp-tools"></div>' +
        `<button class="lp-combo" type="button" aria-haspopup="listbox"><i class="lm-sw"></i><span class="lp-combo-name"></span>${icon('chevronDown', 12)}</button>` +
        '<div class="lp-state"></div>' +
        `<button class="lp-disc" type="button" aria-expanded="false"><span></span>${icon('chevronDown', 12)}</button>` +
        '<div class="lp-list" hidden></div></div>'));
      const tools = q(body, '.lp-tools');
      for (const [ic, title, , run] of TOOLS) {
        const b = el<HTMLButtonElement>(`<button class="lp-tool" type="button">${icon(ic, 16)}</button>`);
        b.title = t(title);
        b.setAttribute('aria-label', t(title));
        b.addEventListener('click', run);
        tools.appendChild(b);
      }
      setText(q(body, '.lp-state'), t('Unsaved Layer State'));
      const combo = q<HTMLButtonElement>(body, '.lp-combo');
      const list = q(body, '.lp-list');
      const disc = q<HTMLButtonElement>(body, '.lp-disc');
      const discText = q(disc, 'span');
      const pop = new Popover('lp-pop', 280);
      const popList = el('<div class="lp-list lp-list-pop"></div>');
      pop.root.appendChild(popList);
      let shown = false;
      let data: LayerRow[] = [];
      const label = (): void => setText(discText, t(shown ? 'Hide Layer List' : 'Show Layer List'));
      label();
      const paint = (): void => {
        const l = layerFeed.data;
        if (!l) return;
        data = l.layers;
        const cur = l.layers.find((r) => r.current);
        setText(q(combo, '.lp-combo-name'), l.current);
        q(combo, '.lm-sw').style.setProperty('--c', cur ? colorHex(cur.color) : 'transparent');
        if (shown) patchList(list, l.layers, rowDef);
        if (pop.isOpen) patchList(popList, l.layers, rowDef);
      };
      layerFeed.onChange(paint);
      const act = (host: HTMLElement) => (e: MouseEvent): void => {
        const tg = e.target as HTMLElement;
        const name = tg.closest<HTMLElement>('.lp-row')?.dataset.key;
        const row = data.find((r) => r.name === name);
        if (!name || !row) return;
        const tkey = tg.closest<HTMLElement>('[data-t]')?.dataset.t;
        if (tkey === 'on') void layerFeed.ops([{ op: 'set', name, props: { on: !row.on } }]);
        else if (tkey === 'frozen') void layerFeed.ops([{ op: 'set', name, props: { frozen: !row.frozen } }]);
        else if (tkey === 'locked') void layerFeed.ops([{ op: 'set', name, props: { locked: !row.locked } }]);
        else if (tg.closest('.lp-name')) { void layerFeed.ops([{ op: 'current', name }]); if (host !== list) pop.hide(); }
      };
      list.addEventListener('click', act(list));
      popList.addEventListener('click', act(popList));
      combo.addEventListener('click', () => {
        if (pop.isOpen) { pop.hide(); return; }
        patchList(popList, data, rowDef);
        pop.show(combo);
      });
      disc.addEventListener('click', () => {
        shown = !shown;
        list.hidden = !shown;
        disc.setAttribute('aria-expanded', String(shown));
        label();
        if (shown) patchList(list, data, rowDef);
      });
      const ctx = new Popover('lm-pop-menu', 200);
      let ctxName = '';
      ctx.root.innerHTML = ['current|Set Current', 'on|Turn Off Layer', 'freeze|Freeze Layer', 'lock|Lock Layer', 'delete|Delete Layer', 'manager|Layer Properties Manager'].map((s) => `<button type="button" data-m="${s.split('|')[0]}">${t(s.split('|')[1])}</button>`).join('');
      list.addEventListener('contextmenu', (e) => {
        const name = (e.target as HTMLElement).closest<HTMLElement>('.lp-row')?.dataset.key;
        const row = data.find((r) => r.name === name);
        if (!name || !row) return;
        e.preventDefault();
        ctxName = name;
        setText(q(ctx.root, '[data-m="on"]'), t(row.on ? 'Turn Off Layer' : 'Turn On Layer'));
        setText(q(ctx.root, '[data-m="freeze"]'), t(row.frozen ? 'Thaw Layer' : 'Freeze Layer'));
        setText(q(ctx.root, '[data-m="lock"]'), t(row.locked ? 'Unlock Layer' : 'Lock Layer'));
        const ghost = el<HTMLElement>('<span style="position:fixed;width:1px;height:1px"></span>');
        ghost.style.left = `${e.clientX}px`;
        ghost.style.top = `${e.clientY}px`;
        document.body.appendChild(ghost);
        ctx.show(ghost);
        ghost.remove();
      });
      ctx.root.addEventListener('click', (e) => {
        const m = (e.target as HTMLElement).closest<HTMLElement>('[data-m]')?.dataset.m;
        const row = data.find((r) => r.name === ctxName);
        ctx.hide();
        if (!m || !row) return;
        if (m === 'current') void layerFeed.ops([{ op: 'current', name: ctxName }]);
        else if (m === 'on') void layerFeed.ops([{ op: 'set', name: ctxName, props: { on: !row.on } }]);
        else if (m === 'freeze') void layerFeed.ops([{ op: 'set', name: ctxName, props: { frozen: !row.frozen } }]);
        else if (m === 'lock') void layerFeed.ops([{ op: 'set', name: ctxName, props: { locked: !row.locked } }]);
        else if (m === 'delete') void layerFeed.ops([{ op: 'delete', names: [ctxName] }]);
        else openLayerManager();
      });
      setTitle(combo, t('Current layer'));
      layerFeed.setActive(true);
      docStore.onChange(() => paint());
      return { show: () => layerFeed.schedule() };
    },
  };
}

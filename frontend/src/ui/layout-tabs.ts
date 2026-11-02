import { onShellMounted } from '../app';
import { drawingCanvas } from '../canvas/mount';
import { api } from '../io/api';
import { cad, type LayoutRow } from '../io/api-cad';
import { confirmAction, promptName } from './dialogs';
import { sendCommand } from './dialogs/engine';
import { interceptCommand } from './dialogs/intercept';
import { docStore } from './doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setTitle } from './dom';
import { pickLayoutTemplatePath } from './file-dialogs';
import { icon } from './icons';
import { t } from './i18n';
import { layoutState } from './layout-state';
import { Popover } from './panels/popover';
import { selection } from './panels/selection-bus';

const DEFAULT_SCALES = ['1:1', '1:2', '1:5', '1:10', '1:20', '1:25', '1:50', '1:100', '1:200', '1:500', '1:1000', '2:1', '5:1', '10:1'];

interface Tab { key: string; label: string; model: boolean; current: boolean }

class LayoutTabs {
  private readonly root: HTMLElement;
  private readonly strip: HTMLElement;
  private readonly more: HTMLButtonElement;
  private readonly listPop = new Popover('lm-pop-menu lt-list', 220);
  private readonly menuPop = new Popover('lm-pop-menu', 200);
  private menuTab = '';
  private readonly pointer = el<HTMLElement>('<span aria-hidden="true" style="position:fixed;width:1px;height:1px;pointer-events:none"></span>');
  private tabs: Tab[] = [];
  private sig = '';

  constructor(status: HTMLElement) {
    this.root = el<HTMLElement>(
      '<div class="cv-lt" role="group" aria-label="Layouts">' +
      `<button class="cv-lt-btn" type="button" data-lt="new">${icon('plus', 14)}</button>` +
      `<button class="cv-lt-btn" type="button" data-lt="list">${icon('menu', 14)}</button>` +
      '<div class="cv-lt-strip" role="tablist"></div>' +
      `<button class="cv-lt-btn cv-lt-more" type="button" data-lt="more" hidden>${icon('chevronDown', 14)}</button></div>`);
    status.appendChild(this.root);
    this.strip = q(this.root, '.cv-lt-strip');
    this.more = q<HTMLButtonElement>(this.root, '.cv-lt-more');
    setTitle(q(this.root, '[data-lt="new"]'), t('New layout'));
    setTitle(q(this.root, '[data-lt="list"]'), t('Layout list'));
    setTitle(this.more, t('All layouts'));
    this.root.addEventListener('click', (e) => this.click(e));
    this.root.addEventListener('contextmenu', (e) => this.context(e));
    this.root.addEventListener('dblclick', (e) => {
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-tab]')?.dataset.tab;
      if (key && key !== 'Model') void this.rename(key);
    });
    this.listPop.root.addEventListener('click', (e) => {
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-tab]')?.dataset.tab;
      this.listPop.hide();
      if (key) void layoutState.go(key);
    });
    this.menuPop.root.addEventListener('click', (e) => {
      const m = (e.target as HTMLElement).closest<HTMLElement>('[data-m]')?.dataset.m;
      this.menuPop.hide();
      if (m) void this.menuAction(m, this.menuTab);
    });
    new ResizeObserver(() => this.fit()).observe(this.strip);
    layoutState.onChange(() => this.paint());
    docStore.onChange(() => this.paint());
    this.paint();
  }

  private rows(): LayoutRow[] {
    return layoutState.summary?.layouts ?? [];
  }

  private click(e: MouseEvent): void {
    const tg = e.target as HTMLElement;
    const tab = tg.closest<HTMLElement>('[data-tab]')?.dataset.tab;
    if (tab) { void layoutState.go(tab); return; }
    const kind = tg.closest<HTMLElement>('[data-lt]')?.dataset.lt;
    if (kind === 'new') void layoutState.action({ action: 'new' });
    else if (kind === 'list' || kind === 'more') this.openList(tg.closest<HTMLElement>('[data-lt]') as HTMLElement);
  }

  private openList(anchor: HTMLElement): void {
    this.listPop.root.replaceChildren(...this.tabs.map((x) => {
      const b = el<HTMLButtonElement>('<button type="button"></button>');
      b.dataset.tab = x.key;
      setText(b, x.label);
      if (x.current) b.style.fontWeight = '700';
      return b;
    }));
    this.listPop.show(anchor);
  }

  private context(e: MouseEvent): void {
    const tab = (e.target as HTMLElement).closest<HTMLElement>('[data-tab]')?.dataset.tab;
    if (!tab || !docStore.activeId) return;
    e.preventDefault();
    this.menuTab = tab;
    const model = tab === 'Model';
    const items: Array<[string, string, boolean]> = [
      ['new', 'New Layout', true], ['template', 'From Template...', true], ['sep', '', true],
      ['delete', 'Delete Layout', !model], ['rename', 'Rename Layout', !model], ['copy', 'Copy Layout', !model],
      ['left', 'Move Left', !model], ['right', 'Move Right', !model], ['sep', '', true],
      ['pagesetup', 'Page Setup Manager...', true], ['plot', 'Print...', true],
    ];
    const root = this.menuPop.root;
    if (root.children.length !== items.length) {
      root.replaceChildren(...items.map(([m]) => {
        if (m === 'sep') return el('<div class="lm-pop-sep"></div>');
        const b = el<HTMLButtonElement>('<button type="button"></button>');
        b.dataset.m = m;
        return b;
      }));
    }
    items.forEach(([m, label, on], i) => {
      if (m === 'sep') return;
      const b = root.children[i] as HTMLButtonElement;
      setText(b, t(label));
      if (b.disabled !== !on) b.disabled = !on;
    });
    const ghost = this.pointer;
    ghost.style.left = `${e.clientX}px`;
    ghost.style.top = `${e.clientY}px`;
    if (!ghost.isConnected) document.body.appendChild(ghost);
    this.menuPop.show(ghost);
  }

  private async rename(name: string): Promise<void> {
    const to = await promptName(t('Rename Layout'), name, t('Rename'));
    if (to && to !== name) await layoutState.action({ action: 'rename', name, to });
  }

  private async menuAction(m: string, tab: string): Promise<void> {
    const rows = this.rows();
    const at = rows.findIndex((r) => r.name === tab);
    if (m === 'new') await layoutState.action({ action: 'new' });
    else if (m === 'template') {
      const path = await pickLayoutTemplatePath();
      if (path) await layoutState.action({ action: 'template', path });
    }
    else if (m === 'delete') {
      if (await confirmAction(t('Delete Layout'), `${t('Delete layout')} "${tab}"?`, t('Delete'), true)) await layoutState.action({ action: 'delete', name: tab });
    } else if (m === 'rename') await this.rename(tab);
    else if (m === 'copy') await layoutState.action({ action: 'copy', name: tab });
    else if (m === 'left' && at > 0) await layoutState.action({ action: 'move', name: tab, index: at - 1 });
    else if (m === 'right' && at >= 0 && at < rows.length - 1) await layoutState.action({ action: 'move', name: tab, index: at + 1 });
    else if (m === 'pagesetup' || m === 'plot') {
      if (!(await layoutState.go(tab))) return;
      if (!interceptCommand(m)) sendCommand(m);
    }
  }

  private paint(): void {
    const s = layoutState.summary;
    const has = !!docStore.activeId && !!s;
    setHidden(this.root, !has);
    if (!has || !s) return;
    const tabs: Tab[] = [{ key: 'Model', label: 'Model', model: true, current: s.tab === 'model' }, ...s.layouts.map((l) => ({ key: l.name, label: l.name, model: false, current: s.tab !== 'model' && s.current === l.name }))];
    this.tabs = tabs;
    patchList(this.strip, tabs, {
      key: (x) => x.key,
      create: (x) => {
        const b = el<HTMLButtonElement>('<button class="cv-lt-tab" type="button" role="tab"></button>');
        b.dataset.tab = x.key;
        setText(b, x.model ? t('Model') : x.label);
        return b;
      },
      update: (n, x) => {
        setClass(n, 'is-on', x.current);
        n.setAttribute('aria-selected', String(x.current));
        setTitle(n, x.label);
      },
    });
    const sig = tabs.map((x) => x.key + (x.current ? '*' : '')).join('|');
    if (sig !== this.sig) { this.sig = sig; this.fit(); }
  }

  private fit(): void {
    const nodes = Array.from(this.strip.children) as HTMLElement[];
    if (!nodes.length) return;
    for (const n of nodes) n.hidden = false;
    const room = this.strip.clientWidth;
    let used = 0;
    let hidden = 0;
    const cur = nodes.findIndex((n) => n.classList.contains('is-on'));
    const widths = nodes.map((n) => n.offsetWidth + 2);
    const keep = new Set<number>();
    if (cur >= 0) { keep.add(cur); used += widths[cur]; }
    for (let i = 0; i < nodes.length; i++) {
      if (keep.has(i)) continue;
      if (used + widths[i] <= room) { keep.add(i); used += widths[i]; } else break;
    }
    nodes.forEach((n, i) => { const h = !keep.has(i); if (n.hidden !== h) n.hidden = h; if (h) hidden++; });
    setHidden(this.more, hidden === 0);
  }
}

class ViewportBar {
  private readonly root: HTMLElement;
  private readonly space: HTMLButtonElement;
  private readonly scale: HTMLButtonElement;
  private readonly lock: HTMLButtonElement;
  private readonly max: HTMLButtonElement;
  private readonly pop = new Popover('lm-pop-menu lt-scales', 130);
  private scales = DEFAULT_SCALES;

  constructor(status: HTMLElement) {
    this.root = el<HTMLElement>(
      '<div class="cv-vpc" role="group" aria-label="Viewport" hidden>' +
      '<button class="cv-vpc-space" type="button"></button>' +
      '<button class="cv-vpc-scale" type="button"></button>' +
      `<button class="cv-vpc-tog" type="button" data-vp="lock">${icon('unlock', 14)}</button>` +
      `<button class="cv-vpc-tog" type="button" data-vp="max">${icon('vpMaximize', 14)}</button></div>`);
    status.appendChild(this.root);
    this.space = q(this.root, '.cv-vpc-space');
    this.scale = q(this.root, '.cv-vpc-scale');
    this.lock = q(this.root, '[data-vp="lock"]');
    this.max = q(this.root, '[data-vp="max"]');
    setTitle(this.space, t('Switch between paper space and the model space of a viewport'));
    setTitle(this.scale, t('Viewport scale'));
    this.space.addEventListener('click', () => this.toggleSpace());
    this.lock.addEventListener('click', () => this.toggleLock());
    this.max.addEventListener('click', () => this.toggleMax());
    this.scale.addEventListener('click', () => void this.openScales());
    this.pop.root.addEventListener('click', (e) => {
      const s = (e.target as HTMLElement).closest<HTMLElement>('[data-scale]')?.dataset.scale;
      this.pop.hide();
      const vp = layoutState.target();
      if (s && vp) void layoutState.run((id) => cad.setViewport(id, vp.h, { scaleText: s }));
    });
    layoutState.onChange(() => this.paint());
    this.paint();
  }

  private toggleSpace(): void {
    const s = layoutState.summary;
    const vp = layoutState.target();
    if (!s || !vp) return;
    void layoutState.run((id) => cad.space(id, { tab: s.current, viewport: s.viewport ? 0 : vp.h }));
  }

  private toggleLock(): void {
    const vp = layoutState.target();
    if (vp) void layoutState.run((id) => cad.setViewport(id, vp.h, { locked: !vp.locked }));
  }

  private toggleMax(): void {
    const s = layoutState.summary;
    const vp = layoutState.target();
    if (!s || !vp) return;
    void layoutState.run((id) => cad.space(id, { tab: s.current, viewport: vp.h, maximize: !s.maximized }));
  }

  private async openScales(): Promise<void> {
    const id = docStore.activeId;
    if (id) {
      try {
        const snap = await api.snapshot(id, 2147483000);
        const list = (snap.tables as Record<string, unknown>).scales;
        if (Array.isArray(list)) {
          const names = list.map((x) => String((x as { name?: unknown }).name ?? '')).filter(Boolean);
          if (names.length) this.scales = names;
        }
      } catch { /* keep defaults */ }
    }
    const cur = layoutState.target()?.scaleText ?? '';
    this.pop.root.replaceChildren(...this.scales.map((s) => {
      const b = el<HTMLButtonElement>('<button type="button"></button>');
      b.dataset.scale = s;
      setText(b, s);
      if (s === cur) b.style.fontWeight = '700';
      return b;
    }));
    this.pop.show(this.scale);
  }

  private paint(): void {
    const s = layoutState.summary;
    const on = !!docStore.activeId && layoutState.inLayout && !!s;
    setHidden(this.root, !on);
    if (!on || !s) return;
    const vp = layoutState.target();
    const active = s.viewport !== 0;
    setText(this.space, t(active ? 'MODEL' : 'PAPER'));
    setClass(this.space, 'is-model', active);
    setDisabled(this.space, !vp);
    setText(this.scale, vp ? vp.scaleText : '-');
    setDisabled(this.scale, !vp || vp.locked);
    const locked = !!vp?.locked;
    setClass(this.lock, 'is-on', locked);
    setTitle(this.lock, t(locked ? 'Viewport locked (click: unlock)' : 'Viewport unlocked (click: lock)'));
    if (this.lock.dataset.s !== (locked ? '1' : '0')) { this.lock.dataset.s = locked ? '1' : '0'; this.lock.innerHTML = icon(locked ? 'lock' : 'unlock', 14); }
    setDisabled(this.lock, !vp);
    setClass(this.max, 'is-on', !!s.maximized);
    setTitle(this.max, t(s.maximized ? 'Restore the viewport' : 'Maximize the viewport'));
    setDisabled(this.max, !vp);
  }
}

let lastMax = 0;

function followMaximize(): void {
  layoutState.onChange(() => {
    const s = layoutState.summary;
    const c = drawingCanvas();
    const m = s && layoutState.inLayout ? s.maximized : 0;
    if (!c || m === lastMax) return;
    lastMax = m;
    if (m) {
      const vp = layoutState.viewports.find((v) => v.h === m);
      const cs = vp?.center as number[] | undefined, sz = vp?.size as number[] | undefined;
      if (cs && sz) c.zoomWindow([cs[0] - sz[0] / 2, cs[1] - sz[1] / 2, cs[0] + sz[0] / 2, cs[1] + sz[1] / 2]);
    } else c.zoomExtents();
  });
}

function bindDouble(): void {
  const c = drawingCanvas();
  if (!c) return;
  c.on('dblclick', (e) => {
    const s = layoutState.summary;
    if (!s || !layoutState.inLayout || !docStore.activeId || selection.commandActive) return;
    const hit = layoutState.viewports.find((v) => {
      const cs = v.center as number[], sz = v.size as number[];
      return e.x >= cs[0] - sz[0] / 2 && e.x <= cs[0] + sz[0] / 2 && e.y >= cs[1] - sz[1] / 2 && e.y <= cs[1] + sz[1] / 2 && v.on;
    });
    if (hit && s.viewport !== hit.h) void layoutState.run((id) => cad.space(id, { tab: s.current, viewport: hit.h }));
    else if (!hit && s.viewport) void layoutState.run((id) => cad.space(id, { tab: s.current, viewport: 0 }));
  });
}

onShellMounted((ctx) => {
  const bar = el<HTMLElement>('<div class="cv-layoutbar" aria-label="Layouts and viewports"></div>');
  ctx.hosts.stage.appendChild(bar);
  new LayoutTabs(bar);
  new ViewportBar(bar);
  followMaximize();
  requestAnimationFrame(bindDouble);
});

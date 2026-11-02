import type { DockPanel } from '../ui/dock';
import { confirmAction, promptName } from '../ui/dialogs';
import { el, patchList, q, setClass, setHidden, setText, setTitle } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { part, type Feature, type FeatureStatus } from './api';
import { iconFor } from './kinds';
import { messageOf, partStore } from './store';

type Item = { kind: 'row'; f: Feature } | { kind: 'bar' };

export interface TreeHooks { edit: (fid: string) => void }

const BADGE: Record<FeatureStatus, { icon: string; label: string }> = {
  ok: { icon: 'success', label: 'Built' },
  warning: { icon: 'warning', label: 'Built with a warning' },
  error: { icon: 'error', label: 'Failed' },
  suppressed: { icon: 'ftSuppress', label: 'Suppressed' },
  stale: { icon: 'refresh', label: 'Waiting for a rebuild' },
  rolled: { icon: 'ftRollback', label: 'Rolled back' },
};

const badgeStatus = (f: Feature): FeatureStatus => (f.suppressed ? 'suppressed' : f.rolled ? 'rolled' : f.state.status);

function rowHtml(): string {
  return `<span class="pt-grip" title="Drag to reorder">${icon('grip', 12)}</span><span class="pt-ico"></span><span class="pt-name"></span><span class="pt-badge"></span>`;
}

function fillRow(n: HTMLElement, f: Feature): void {
  const status = badgeStatus(f);
  n.dataset.id = f.id;
  n.dataset.status = status;
  setClass(n, 'is-suppressed', f.suppressed);
  setClass(n, 'is-rolled', f.rolled);
  setClass(n, 'is-error', status === 'error');
  setClass(n, 'is-selected', partStore.selected === f.id);
  const ico = q(n, '.pt-ico');
  if (ico.dataset.t !== f.type) { ico.dataset.t = f.type; ico.innerHTML = icon(iconFor(f.type), 16); }
  setText(q(n, '.pt-name'), f.label);
  const badge = q(n, '.pt-badge');
  if (badge.dataset.s !== status) { badge.dataset.s = status; badge.innerHTML = icon(BADGE[status].icon, 14); }
  setTitle(badge, status === 'error' || status === 'warning' ? `${t(BADGE[status].label)}: ${f.state.message || f.state.warnings.join(' ')}` : t(BADGE[status].label));
}

export function featureTreePanel(hooks: TreeHooks): DockPanel {
  return {
    id: 'features',
    label: 'Features',
    icon: 'part',
    order: -1,
    build: (body) => {
      body.appendChild(el(
        '<div class="pt"><div class="pt-tools"></div><div class="pt-list" role="tree" aria-label="Feature tree"></div>' +
        '<p class="pt-empty">No features yet. Pick a plane or a face in the 3D view and start a sketch.</p>' +
        '<p class="pt-status" role="status"></p></div>'));
      const tools = q(body, '.pt-tools');
      const list = q(body, '.pt-list');
      const empty = q(body, '.pt-empty');
      const status = q(body, '.pt-status');
      setText(empty, t('No features yet. Pick a plane or a face in the 3D view and start a sketch.'));
      const tool = (ic: string, title: string, run: () => void): void => {
        const b = el<HTMLButtonElement>(`<button class="pt-tool" type="button" aria-label="${title}">${icon(ic, 16)}</button>`);
        b.title = t(title);
        b.addEventListener('click', run);
        tools.appendChild(b);
      };
      tool('refresh', 'Rebuild', () => { void partStore.run((id) => part.rebuild(id, false)); });
      tool('history', 'Force a full rebuild', () => { void partStore.run((id) => part.rebuild(id, true)); });
      tool('ftRollback', 'Roll forward to the end', () => { void partStore.run((id) => part.rollback(id, null)); });
      let dragging = false;
      let barAfter: string | null | undefined;

      const items = (): Item[] => {
        const feats = partStore.features;
        const out: Item[] = feats.map((f) => ({ kind: 'row', f }));
        const rb = partStore.tree?.rollback ?? null;
        const at = rb ? feats.findIndex((f) => f.id === rb) : -1;
        const pos = barAfter !== undefined ? (barAfter ? feats.findIndex((f) => f.id === barAfter) : -1) : at;
        const place = barAfter !== undefined && barAfter === null ? feats.length : pos >= 0 ? pos + 1 : feats.length;
        if (feats.length) out.splice(place, 0, { kind: 'bar' });
        return out;
      };

      const barNode = (): HTMLElement => {
        const n = el<HTMLElement>(`<div class="pt-bar" role="separator" title="Drag to roll the model back"><span class="pt-bar-line"></span><span class="pt-bar-grip">${icon('ftRollback', 14)}</span></div>`);
        n.addEventListener('pointerdown', (e) => startBarDrag(e, n));
        return n;
      };

      const relations = (): void => {
        const hover = partStore.find(partStore.hover);
        for (const n of Array.from(list.querySelectorAll<HTMLElement>('.pt-row'))) {
          const id = n.dataset.id ?? '';
          setClass(n, 'is-hover', !!hover && hover.id === id);
          setClass(n, 'is-parent', !!hover && hover.parents.includes(id));
          setClass(n, 'is-child', !!hover && hover.children.includes(id));
        }
        const shown = partStore.find(partStore.hover) ?? partStore.find(partStore.selected);
        const msg = shown ? (shown.state.message || shown.state.warnings.join(' ')) : '';
        setText(status, msg);
        setClass(status, 'is-error', !!shown && shown.state.status === 'error');
      };

      const rowNode = (f: Feature): HTMLElement => {
        const n = el<HTMLElement>(`<div class="pt-row" role="treeitem" tabindex="-1">${rowHtml()}</div>`);
        fillRow(n, f);
        n.addEventListener('pointerenter', () => { partStore.hover = f.id; relations(); });
        n.addEventListener('pointerleave', () => { if (partStore.hover === f.id) { partStore.hover = null; relations(); } });
        n.addEventListener('click', () => { partStore.selected = f.id; paint(); });
        n.addEventListener('dblclick', () => hooks.edit(f.id));
        n.addEventListener('contextmenu', (e) => { e.preventDefault(); partStore.selected = f.id; paint(); openMenu(f.id, e.clientX, e.clientY); });
        q(n, '.pt-grip').addEventListener('pointerdown', (e) => startRowDrag(e, f.id));
        return n;
      };

      let barCache: HTMLElement | null = null;
      const paint = (): void => {
        const its = items();
        const bi = its.findIndex((i) => i.kind === 'bar');
        const barEl = list.querySelector<HTMLElement>('.pt-bar');
        if (barEl && bi >= 0) {
          const before = its[bi - 1];
          const after = its[bi + 1];
          const okBefore = before && before.kind === 'row' && (barEl.previousElementSibling as HTMLElement | null)?.dataset.key === before.f.id;
          const okAfter = after && after.kind === 'row' ? (barEl.nextElementSibling as HTMLElement | null)?.dataset.key === after.f.id : !barEl.nextElementSibling || barEl.nextElementSibling.classList.contains('pt-drop');
          if (!okBefore || !okAfter) barEl.remove();
        }
        patchList<Item>(list, its, {
          key: (i) => (i.kind === 'bar' ? '__bar' : i.f.id),
          create: (i) => (i.kind === 'bar' ? (barCache ??= barNode()) : rowNode(i.f)),
          update: (n, i) => { if (i.kind === 'row') fillRow(n, i.f); },
        });
        setHidden(empty, partStore.features.length > 0);
        relations();
      };

      const rows = (): HTMLElement[] => Array.from(list.querySelectorAll<HTMLElement>('.pt-row'));

      const slotAt = (y: number, skip = ''): number => {
        const rs = rows().filter((r) => r.dataset.id !== skip);
        let slot = rs.length;
        for (let i = 0; i < rs.length; i++) {
          const r = rs[i].getBoundingClientRect();
          if (y < r.top + r.height / 2) { slot = i; break; }
        }
        return slot;
      };

      const drop = el<HTMLElement>('<div class="pt-drop" hidden></div>');
      list.appendChild(drop);
      const showDrop = (slot: number, skip: string, ok: boolean): void => {
        const rs = rows().filter((r) => r.dataset.id !== skip);
        const lr = list.getBoundingClientRect();
        const y = slot >= rs.length ? (rs.length ? rs[rs.length - 1].getBoundingClientRect().bottom : lr.top) : rs[slot].getBoundingClientRect().top;
        drop.style.transform = `translateY(${Math.round(y - lr.top + list.scrollTop)}px)`;
        setClass(drop, 'is-no', !ok);
        drop.hidden = false;
      };

      const startRowDrag = (e: PointerEvent, fid: string): void => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        const grip = e.currentTarget as HTMLElement;
        grip.setPointerCapture(e.pointerId);
        const src = list.querySelector<HTMLElement>(`.pt-row[data-id="${fid}"]`);
        setClass(src, 'is-dragging', true);
        const cache = new Map<string, { ok: boolean; message: string }>();
        let slot = -1;
        let verdict = { ok: false, message: '' };
        const order = (): string[] => partStore.features.map((f) => f.id).filter((x) => x !== fid);
        const check = async (s: number, token: number): Promise<void> => {
          const o = order();
          const after = s <= 0 ? '' : o[s - 1];
          const id = partStore.doc;
          const key = after;
          let v = cache.get(key);
          if (!v) { try { v = await part.canMove(id, fid, after); } catch (err) { v = { ok: false, message: messageOf(err) }; } cache.set(key, v); }
          if (token !== slot) return;
          verdict = v;
          showDrop(s, fid, v.ok);
          setText(status, v.ok ? '' : v.message);
          setClass(status, 'is-error', !v.ok);
        };
        const move = (ev: PointerEvent): void => {
          const s = slotAt(ev.clientY, fid);
          if (s === slot) return;
          slot = s;
          verdict = { ok: false, message: '' };
          showDrop(s, fid, false);
          void check(s, s);
        };
        const up = (): void => {
          grip.removeEventListener('pointermove', move);
          grip.removeEventListener('pointerup', up);
          grip.removeEventListener('pointercancel', up);
          drop.hidden = true;
          setClass(src, 'is-dragging', false);
          relations();
          if (slot < 0) return;
          const o = order();
          const after = slot <= 0 ? null : o[slot - 1];
          const cur = partStore.features.map((f) => f.id);
          const same = (cur.indexOf(fid) === 0 && after === null) || (after !== null && cur.indexOf(after) === cur.indexOf(fid) - 1);
          if (same) return;
          if (!verdict.ok) { if (verdict.message) toast(verdict.message, 'error'); return; }
          void partStore.run((id) => part.reorder(id, fid, after));
        };
        grip.addEventListener('pointermove', move);
        grip.addEventListener('pointerup', up);
        grip.addEventListener('pointercancel', up);
      };

      const startBarDrag = (e: PointerEvent, bar: HTMLElement): void => {
        if (e.button !== 0) return;
        e.preventDefault();
        bar.setPointerCapture(e.pointerId);
        dragging = true;
        setClass(bar, 'is-dragging', true);
        const feats = partStore.features;
        let target: string | null | undefined;
        const move = (ev: PointerEvent): void => {
          const s = Math.max(1, slotAt(ev.clientY));
          const nextTarget = s >= feats.length ? null : feats[s - 1].id;
          if (nextTarget === target) return;
          target = nextTarget;
          barAfter = target;
          paint();
          const idx = target === null ? feats.length : feats.findIndex((f) => f.id === target) + 1;
          for (const r of rows()) {
            const at = feats.findIndex((f) => f.id === r.dataset.id);
            setClass(r, 'is-rolled', at >= idx);
          }
        };
        const up = (): void => {
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', up);
          window.removeEventListener('pointercancel', up);
          dragging = false;
          setClass(bar, 'is-dragging', false);
          const to = target;
          if (to === undefined) { barAfter = undefined; paint(); return; }
          const last = feats.length ? feats[feats.length - 1].id : null;
          const send = to === last ? null : to;
          void partStore.run((id) => part.rollback(id, send)).then(() => { barAfter = undefined; paint(); });
        };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
      };

      const menu = el<HTMLElement>(
        '<div class="pt-menu" role="menu" hidden>' +
        '<button type="button" role="menuitem" data-a="edit"></button><button type="button" role="menuitem" data-a="suppress"></button>' +
        '<button type="button" role="menuitem" data-a="rename"></button><button type="button" role="menuitem" data-a="rollback"></button>' +
        '<button type="button" role="menuitem" data-a="delete" class="is-danger"></button></div>');
      (document.getElementById('overlay-root') ?? document.body).appendChild(menu);
      let menuFor = '';
      const hideMenu = (): void => { menu.hidden = true; menuFor = ''; };
      document.addEventListener('pointerdown', (e) => { if (!menu.hidden && !menu.contains(e.target as Node)) hideMenu(); }, true);
      document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { hideMenu(); e.stopPropagation(); } }, true);

      function openMenu(fid: string, x: number, y: number): void {
        const f = partStore.find(fid);
        if (!f) return;
        menuFor = fid;
        setText(q(menu, '[data-a="edit"]'), t('Edit Feature'));
        setText(q(menu, '[data-a="suppress"]'), t(f.suppressed ? 'Unsuppress' : 'Suppress'));
        setText(q(menu, '[data-a="rename"]'), t('Rename...'));
        setText(q(menu, '[data-a="rollback"]'), t('Roll Back to Here'));
        setText(q(menu, '[data-a="delete"]'), t('Delete...'));
        menu.style.visibility = 'hidden';
        menu.hidden = false;
        const w = menu.offsetWidth, h = menu.offsetHeight;
        menu.style.left = `${Math.max(4, Math.min(x, window.innerWidth - w - 4))}px`;
        menu.style.top = `${Math.max(4, Math.min(y, window.innerHeight - h - 4))}px`;
        menu.style.visibility = '';
      }

      menu.addEventListener('click', (e) => {
        const b = (e.target as HTMLElement).closest<HTMLElement>('[data-a]');
        const fid = menuFor;
        const f = partStore.find(fid);
        if (!b || !f) return;
        hideMenu();
        const act = b.dataset.a;
        if (act === 'edit') hooks.edit(fid);
        else if (act === 'suppress') void partStore.run((id) => part.suppress(id, fid, !f.suppressed));
        else if (act === 'rollback') void partStore.run((id) => part.rollback(id, fid === partStore.features[partStore.features.length - 1]?.id ? null : fid));
        else if (act === 'rename') void promptName(t('Rename Feature'), f.label, t('Rename')).then((name) => { if (name && name !== f.label) void partStore.run((id) => part.edit(id, fid, { label: name })); });
        else if (act === 'delete') void removeFeature(f);
      });

      async function removeFeature(f: Feature): Promise<void> {
        const kids = f.children.map((c) => partStore.find(c)?.label ?? c);
        const text = kids.length
          ? `${f.label} is used by ${kids.join(', ')}. Deleting it also deletes those features.`
          : `Delete ${f.label}? You can undo this.`;
        if (!(await confirmAction(t('Delete Feature'), t(text), t(kids.length ? 'Delete All' : 'Delete'), true))) return;
        void partStore.run((id) => part.remove(id, f.id, kids.length > 0));
      }

      document.addEventListener('formcad:part-select', (e) => {
        partStore.selected = (e as CustomEvent<string | null>).detail;
        paint();
      });

      let lastSig = '';
      partStore.onChange(() => {
        if (dragging) return;
        const sig = JSON.stringify([partStore.tree?.rev, partStore.tree?.rollback, partStore.features.map((f) => [f.id, f.label, f.state.status, f.state.message, f.suppressed, f.rolled])]);
        const ctrlSel = partStore.selected;
        if (sig === lastSig && ctrlSel === (list.querySelector('.is-selected') as HTMLElement | null)?.dataset.id) return;
        lastSig = sig;
        paint();
      });
      paint();
      return { show: paint };
    },
  };
}

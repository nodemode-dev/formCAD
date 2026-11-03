import { events } from '../io/events';
import type { DockPanel } from '../ui/dock';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { gate, MODEL } from '../ui/panel-gate';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import { part, type RefGeoItem } from './api';
import { messageOf } from './store';

const KIND_ICON: Record<string, string> = { plane: 'ftPlane', axis: 'ftAxis', point: 'point', cs: 'ftCs' };

let items: RefGeoItem[] = [];
let doc = '';
let timer = 0;
let seq = 0;
const watchers = new Set<() => void>();

function push(): void {
  const vp = view3d()?.vp;
  if (vp) vp.setReference(items);
  else window.setTimeout(() => { view3d()?.vp?.setReference(items); }, 600);
}

export async function loadReference(): Promise<void> {
  const id = docStore.activeId;
  const n = ++seq;
  if (!id) { items = []; doc = ''; push(); for (const w of watchers) w(); return; }
  try {
    const list = await part.refgeo(id);
    if (n !== seq || id !== docStore.activeId) return;
    items = list.items;
    doc = id;
  } catch {
    items = [];
  }
  push();
  for (const w of watchers) w();
}

export const referenceItems = (): RefGeoItem[] => items;

const refAllow = gate(['refgeo', 'features'], MODEL, () => later());

function later(): void {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => { if (refAllow()) void loadReference(); }, 140);
}

export function watchReference(): void {
  events.on('doc', (e) => { if (e.id === docStore.activeId) later(); });
  let last = docStore.activeId;
  docStore.onChange(() => { if (docStore.activeId !== last) { last = docStore.activeId; later(); } });
  document.addEventListener('formcad:view3d', later);
  later();
}

export function refGeoPanel(): DockPanel {
  return {
    id: 'refgeo',
    label: 'Reference Geometry',
    icon: 'ftPlane',
    order: -0.4,
    build: (body) => {
      body.appendChild(el('<div class="rg"><div class="rg-list"></div><p class="rg-empty"></p></div>'));
      const list = q(body, '.rg-list');
      const empty = q(body, '.rg-empty');
      setText(empty, t('No planes, axes, points or coordinate systems yet.'));
      const paint = (): void => {
        patchList<RefGeoItem>(list, items, {
          key: (i) => i.name,
          create: (i) => {
            const n = el<HTMLElement>(`<div class="rg-row"><span class="rg-ico"></span><span class="rg-name"></span><button class="rg-eye" type="button" aria-label="Show or hide"></button></div>`);
            q(n, '.rg-eye').addEventListener('click', () => {
              const id = docStore.activeId;
              const cur = items.find((x) => x.name === i.name);
              if (!id || !cur) return;
              part.refgeoEdit(id, cur.name, { visible: !cur.visible }).then(() => later()).catch((e: unknown) => toast(messageOf(e), 'error'));
            });
            return n;
          },
          update: (n, i) => {
            const ico = q(n, '.rg-ico');
            if (ico.dataset.k !== i.kind) { ico.dataset.k = i.kind; ico.innerHTML = icon(KIND_ICON[i.kind] ?? 'ftPlane', 16); }
            setText(q(n, '.rg-name'), i.name);
            const eye = q(n, '.rg-eye');
            const key = `${i.visible}`;
            if (eye.dataset.v !== key) { eye.dataset.v = key; eye.innerHTML = icon(i.visible ? 'eye' : 'eyeOff', 14); }
            n.title = i.status && i.status !== 'ok' ? (i.message ?? i.status) : `${i.kind} · ${i.method}`;
            setClass(n, 'is-error', i.status === 'error');
            setClass(n, 'is-hidden', !i.visible);
          },
        });
        setClass(empty, 'is-on', items.length === 0);
      };
      watchers.add(paint);
      paint();
      return { show: paint };
    },
  };
}

export const referenceDoc = (): string => doc;

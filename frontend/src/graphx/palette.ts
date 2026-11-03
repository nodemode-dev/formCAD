import { patchList, el, q, setClass, setHidden, setText, store, stored } from '../ui/dom';
import { hasIcon, icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { graphEditor, registerNodeIcons } from '../graph';
import type { CatalogueEntry } from '../graph';

export const CATEGORY_ICONS: Record<string, string> = {
  Params: 'gcParams', Maths: 'gcMaths', Lists: 'gcLists', Sets: 'gcSets', Trees: 'gcTrees', Vector: 'gcVector', Point: 'gcPoint', Plane: 'gcPlane',
  Curve: 'gcCurve', Surface: 'surface', Solid: 'cube', Intersect: 'gcIntersect', Transform: 'gcTransform', Document: 'gcDocument', Loops: 'gcLoops',
  Optimize: 'gcOptimize', Plugins: 'gcPlugins', Domain: 'gcDomain', Display: 'eye', Colour: 'gradient', Flow: 'gcLoops',
};

const TYPE_ICONS: Record<string, string> = {
  'input.slider': 'sliders', 'input.panel': 'gcPanel', 'input.toggle': 'gcToggle', 'input.button': 'gcButton', 'input.value_list': 'gcValueList',
};

export const categoryIcon = (category: string): string => {
  const name = CATEGORY_ICONS[category] ?? (category ? 'graph' : 'graph');
  return hasIcon(name) ? name : 'graph';
};

export function registerIcons(): void {
  registerNodeIcons({ ...CATEGORY_ICONS, ...TYPE_ICONS });
}

interface Section { category: string; entries: CatalogueEntry[] }

const OPEN_KEY = 'formCAD.graphx.paletteClosed';

function sectionsOf(list: CatalogueEntry[]): Section[] {
  const by = new Map<string, CatalogueEntry[]>();
  for (const e of list) {
    if (e.obsolete) continue;
    const key = e.category || 'Other';
    let rows = by.get(key);
    if (!rows) { rows = []; by.set(key, rows); }
    rows.push(e);
  }
  const order = Object.keys(CATEGORY_ICONS);
  return [...by.entries()]
    .sort((a, b) => (order.indexOf(a[0]) + 1 || 99) - (order.indexOf(b[0]) + 1 || 99) || a[0].localeCompare(b[0]))
    .map(([category, entries]) => ({ category, entries: entries.sort((a, b) => (a.group ?? '').localeCompare(b.group ?? '') || a.name.localeCompare(b.name)) }));
}

export class NodePalette {
  readonly root: HTMLElement;
  private readonly search: HTMLInputElement;
  private readonly list: HTMLElement;
  private readonly empty: HTMLElement;
  private signature = '';
  private closed = new Set<string>(JSON.parse(stored(OPEN_KEY) ?? '[]') as string[]);

  constructor() {
    this.root = el(
      '<aside class="gp-palette" aria-label="Node palette" hidden><div class="gp-phead"><span class="gp-ptitle"></span></div>' +
      '<input class="cv-input gp-psearch" type="search" spellcheck="false" autocomplete="off">' +
      '<div class="gp-plist is-scroll"></div><p class="cv-note gp-pempty" hidden></p></aside>');
    this.search = q<HTMLInputElement>(this.root, '.gp-psearch');
    this.list = q(this.root, '.gp-plist');
    this.empty = q(this.root, '.gp-pempty');
    setText(q(this.root, '.gp-ptitle'), t('Nodes'));
    this.search.placeholder = t('Search nodes');
    setText(this.empty, t('No node matches.'));
    this.search.addEventListener('input', () => this.filter());
    this.search.addEventListener('keydown', (e) => { e.stopPropagation(); });
    this.list.addEventListener('click', (e) => {
      const head = (e.target as Element).closest<HTMLElement>('.gp-chead');
      if (head) this.fold(head.parentElement as HTMLElement);
    });
    this.list.addEventListener('dblclick', (e) => {
      const item = (e.target as Element).closest<HTMLElement>('.gp-item');
      if (item?.dataset.id) void graphEditor.addNode(item.dataset.id);
    });
    this.list.addEventListener('dragstart', (e) => {
      const item = (e.target as Element).closest<HTMLElement>('.gp-item');
      if (!item?.dataset.id || !e.dataTransfer) return;
      e.dataTransfer.setData('application/x-formcad-node', item.dataset.id);
      e.dataTransfer.effectAllowed = 'copy';
    });
    this.list.addEventListener('keydown', (e) => {
      const item = (e.target as Element).closest<HTMLElement>('.gp-item');
      if (item?.dataset.id && e.key === 'Enter') { e.preventDefault(); void graphEditor.addNode(item.dataset.id); }
    });
  }

  get shown(): boolean { return !this.root.hidden; }

  toggle(on?: boolean): void {
    setHidden(this.root, on === undefined ? !this.root.hidden : !on);
    if (this.shown) this.sync();
  }

  private fold(section: HTMLElement): void {
    const key = section.dataset.key ?? '';
    const open = this.closed.has(key);
    if (open) this.closed.delete(key); else this.closed.add(key);
    store(OPEN_KEY, JSON.stringify([...this.closed]));
    setClass(section, 'is-closed', !open);
  }

  sync(): void {
    const list = graphEditor.catalogue();
    const sig = list.map((e) => e.id).join('|');
    if (sig === this.signature) return;
    this.signature = sig;
    const sections = sectionsOf(list);
    patchList(this.list, sections, {
      key: (s) => s.category,
      create: (s) => {
        const node = el(
          `<section class="gp-cat"><button class="gp-chead" type="button">${icon('chevronDown', 14)}${icon(categoryIcon(s.category), 16)}<span class="gp-cname"></span><span class="gp-ccount"></span></button><div class="gp-citems"></div></section>`);
        setClass(node, 'is-closed', this.closed.has(s.category));
        return node;
      },
      update: (node, s) => {
        setText(q(node, '.gp-cname'), t(s.category));
        setText(q(node, '.gp-ccount'), String(s.entries.length));
        patchList(q(node, '.gp-citems'), s.entries, {
          key: (e) => e.id,
          create: (e) => {
            const item = el('<div class="gp-item" draggable="true" tabindex="0"><span class="gp-iname"></span><span class="gp-inick"></span></div>');
            item.dataset.id = e.id;
            return item;
          },
          update: (item, e) => {
            setText(q(item, '.gp-iname'), e.name);
            setText(q(item, '.gp-inick'), e.nick ?? '');
            item.title = e.description ? `${e.name}: ${e.description}` : e.name;
            item.dataset.search = `${e.name} ${e.nick ?? ''} ${e.group ?? ''} ${e.description ?? ''}`.toLowerCase();
          },
        });
      },
    });
    this.filter();
  }

  private filter(): void {
    const needle = this.search.value.trim().toLowerCase();
    let any = false;
    for (const sec of Array.from(this.list.children) as HTMLElement[]) {
      let hits = 0;
      for (const item of Array.from(q(sec, '.gp-citems').children) as HTMLElement[]) {
        const match = !needle || (item.dataset.search ?? '').includes(needle);
        setHidden(item, !match);
        if (match) hits++;
      }
      setHidden(sec, hits === 0);
      setClass(sec, 'is-found', needle !== '' && hits > 0);
      if (hits) any = true;
    }
    setHidden(this.empty, any || this.signature === '');
  }
}

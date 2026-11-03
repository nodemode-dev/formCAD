import { el, q, setClass, setHidden, setText, setTitle } from '../ui/dom';
import { icon } from '../ui/icons';
import { BODY_PAD, HEAD_H, nodeBox, PORT_INSET, PORT_PAD, ROW_H, type Box } from './geometry';
import { nodeIconName, widgetFactory, type NodeWidget, type NodeWidgetContext } from './widgets';
import type { CatalogueEntry, NodeRecord, NodeState, PortMods, PortRecord } from './types';

export interface WidgetHost {
  edit(nodeId: string, change: import('./types').NodeEdit, live: boolean): void;
  tree(nodeId: string, port: string, page: number): Promise<import('./types').TreePage>;
  settingsOf(nodeId: string): Record<string, unknown>;
  node(nodeId: string): NodeRecord | undefined;
}

const MOD_LETTERS: Array<[keyof PortMods, string]> = [['expression', 'X'], ['reverse', 'R'], ['flatten', 'F'], ['graft', 'G'], ['simplify', 'S'], ['principal', 'P'], ['invert', 'I']];

export function modText(mods: PortMods | undefined): string {
  if (!mods) return '';
  let s = '';
  for (const [k, l] of MOD_LETTERS) if (mods[k]) s += l;
  return s.length > 4 ? `${s.slice(0, 3)}+` : s;
}

export class NodeView {
  readonly el: HTMLElement;
  rec: NodeRecord;
  entry: CatalogueEntry | undefined;
  state: NodeState | undefined;
  box: Box;
  widget: NodeWidget | null = null;
  private readonly head: HTMLElement;
  private readonly title: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly iconHost: HTMLElement;
  private readonly rows: HTMLElement;
  private readonly body: HTMLElement;
  private readonly eye: HTMLButtonElement;
  private readonly power: HTMLButtonElement;
  private portKey = '';
  private widgetKind = '';
  private iconName = '';
  private stateName = '';
  private pos = '';
  private size = '';
  private linkKey = '';
  private lastRec: NodeRecord | null = null;
  private readonly dots = new Map<string, HTMLElement>();
  private readonly labels = new Map<string, HTMLElement>();
  private readonly mods = new Map<string, HTMLElement>();

  constructor(rec: NodeRecord, entry: CatalogueEntry | undefined, private readonly host: WidgetHost) {
    this.rec = rec;
    this.entry = entry;
    this.el = el(
      '<div class="gx-node">' +
      '<div class="gx-nh"><span class="gx-ni"></span><span class="gx-nt"></span><span class="gx-nm">' + icon('warning', 16) + '</span>' +
      '<button class="gx-tog gx-eye" type="button" data-act="preview">' + icon('eye', 16) + '</button>' +
      '<button class="gx-tog gx-pow" type="button" data-act="enable">' + icon('bulbOn', 16) + '</button></div>' +
      '<div class="gx-np"></div><div class="gx-nb" hidden></div></div>',
    );
    this.el.dataset.id = rec.id;
    this.head = q(this.el, '.gx-nh');
    this.title = q(this.el, '.gx-nt');
    this.msg = q(this.el, '.gx-nm');
    this.iconHost = q(this.el, '.gx-ni');
    this.rows = q(this.el, '.gx-np');
    this.body = q(this.el, '.gx-nb');
    this.eye = q<HTMLButtonElement>(this.el, '.gx-eye');
    this.power = q<HTMLButtonElement>(this.el, '.gx-pow');
    this.box = nodeBox(rec, null);
    this.patch(rec, entry);
  }

  patch(rec: NodeRecord, entry: CatalogueEntry | undefined): void {
    this.rec = rec;
    this.entry = entry;
    const shown = rec.nickname || entry?.name || rec.type;
    setText(this.title, shown);
    setTitle(this.head, entry?.description ?? '');
    const iconName = nodeIconName(rec.type, entry?.category ?? '') ?? (entry?.icon ?? '');
    if (iconName !== this.iconName) {
      this.iconName = iconName;
      this.iconHost.replaceChildren();
      if (iconName) this.iconHost.insertAdjacentHTML('beforeend', icon(iconName, 16));
    }
    this.buildPorts();
    this.paintMods();
    this.ensureWidget();
    setClass(this.eye, 'is-on', rec.preview);
    setClass(this.power, 'is-on', rec.enabled);
    this.paintState();
    this.place();
    if (this.widget && this.lastRec !== rec) this.widget.update(rec, this.state ?? { state: 'blank', messages: [], outputs: {} });
    this.lastRec = rec;
  }

  ensureWidget(): void {
    const kind = this.entry?.widget || this.rec.type;
    const factory = widgetFactory(kind);
    const key = factory ? kind : '';
    if (key === this.widgetKind) return;
    this.widget?.dispose?.();
    this.widget = null;
    this.body.replaceChildren();
    this.widgetKind = key;
    if (!factory) {
      setHidden(this.body, true);
      this.box = nodeBox(this.rec, null);
      this.applySize();
      return;
    }
    const id = this.rec.id;
    const ctx: NodeWidgetContext = {
      nodeId: id,
      typeId: this.rec.type,
      host: this.body,
      node: () => this.host.node(id) ?? this.rec,
      settings: () => this.host.settingsOf(id),
      persistent: (port) => {
        const n = this.host.node(id) ?? this.rec;
        const p = port ? n.inputs.find((i) => i.name === port) : n.inputs[0];
        return p?.persistent;
      },
      edit: (change, opts) => this.host.edit(id, change, opts?.live === true),
      tree: (port, page) => this.host.tree(id, port, page ?? 0),
      emit: (type, detail) => document.dispatchEvent(new CustomEvent('formcad:graph', { detail: { type, node: id, detail } })),
    };
    this.widget = factory(ctx);
    this.body.style.width = `${this.widget.size.w}px`;
    this.body.style.height = `${this.widget.size.h + BODY_PAD * 2}px`;
    setHidden(this.body, false);
    this.box = nodeBox(this.rec, this.widget.size);
    this.applySize();
    this.widget.update(this.rec, this.state ?? { state: 'blank', messages: [], outputs: {} });
  }

  private applySize(): void {
    const key = `${this.box.w}x${this.box.h}`;
    if (key === this.size) return;
    this.size = key;
    this.el.style.width = `${this.box.w}px`;
    this.el.style.height = `${this.box.h}px`;
  }

  place(): void {
    const key = `${this.rec.x},${this.rec.y}`;
    if (key === this.pos) return;
    this.pos = key;
    this.el.style.left = `${this.rec.x}px`;
    this.el.style.top = `${this.rec.y}px`;
  }

  private buildPorts(): void {
    const key = this.rec.inputs.map((p) => p.name).join('|') + '>' + this.rec.outputs.map((p) => p.name).join('|');
    if (key === this.portKey) { this.paintLabels(); return; }
    this.portKey = key;
    this.dots.clear();
    this.labels.clear();
    this.mods.clear();
    const n = Math.max(this.rec.inputs.length, this.rec.outputs.length, 1);
    const frag = document.createDocumentFragment();
    for (let i = 0; i < n; i++) {
      const row = el('<div class="gx-row"><div class="gx-pin"></div><div class="gx-pout"></div></div>');
      const pin = this.rec.inputs[i];
      const pout = this.rec.outputs[i];
      if (pin) this.fillPort(q(row, '.gx-pin'), pin, 'in');
      if (pout) this.fillPort(q(row, '.gx-pout'), pout, 'out');
      frag.appendChild(row);
    }
    this.rows.replaceChildren(frag);
    this.paintLabels();
    this.box = nodeBox(this.rec, this.widget ? this.widget.size : null);
    this.applySize();
  }

  private fillPort(cell: HTMLElement, p: PortRecord, side: 'in' | 'out'): void {
    const dot = el(`<span class="gx-dot" data-side="${side}" data-port="${p.name}"></span>`);
    const label = el('<span class="gx-pl"></span>');
    label.dataset.side = side;
    label.dataset.port = p.name;
    this.dots.set(`${side}:${p.name}`, dot);
    this.labels.set(`${side}:${p.name}`, label);
    if (side === 'in') {
      const mods = el('<span class="gx-pm"></span>');
      this.mods.set(p.name, mods);
      cell.append(dot, label, mods);
    } else {
      cell.append(label, dot);
    }
  }

  private paintLabels(): void {
    const eIn = this.entry?.inputs;
    const eOut = this.entry?.outputs;
    for (const p of this.rec.inputs) {
      const l = this.labels.get(`in:${p.name}`);
      const e = eIn?.find((x) => x.name === p.name);
      if (l) { setText(l, e?.nick || p.name); setTitle(l, e ? `${p.name} · ${e.kind}${e.description ? ` · ${e.description}` : ''}` : p.name); }
    }
    for (const p of this.rec.outputs) {
      const l = this.labels.get(`out:${p.name}`);
      const e = eOut?.find((x) => x.name === p.name);
      if (l) { setText(l, e?.nick || p.name); setTitle(l, e ? `${p.name} · ${e.kind}${e.description ? ` · ${e.description}` : ''}` : p.name); }
    }
  }

  private paintMods(): void {
    for (const p of this.rec.inputs) setText(this.mods.get(p.name) ?? null, modText(p.mods));
  }

  setLinks(ins: ReadonlySet<string>, outs: ReadonlySet<string>): void {
    const key = [...ins].sort().join(',') + '|' + [...outs].sort().join(',');
    if (key === this.linkKey) return;
    this.linkKey = key;
    for (const [k, d] of this.dots) setClass(d, 'is-linked', k.startsWith('in:') ? ins.has(k.slice(3)) : outs.has(k.slice(4)));
  }

  setState(state: NodeState | undefined): void {
    this.state = state;
    this.paintState();
    if (this.widget) this.widget.update(this.rec, state ?? { state: 'blank', messages: [], outputs: {} });
  }

  private paintState(): void {
    this.stateName = !this.rec.enabled ? 'disabled' : this.state?.state ?? 'blank';
    this.paintClass();
  }

  private paintClass(): void {
    const has = !!this.state && this.state.messages.length > 0 && this.rec.enabled;
    const next = `gx-node is-${this.stateName}${has ? ' has-msg' : ''}${this.rec.preview ? '' : ' is-nopreview'}${this.selected ? ' is-sel' : ''}`;
    if (this.el.className !== next) this.el.className = next;
  }

  private selected = false;

  setSelected(on: boolean): void {
    this.selected = on;
    this.paintClass();
  }

  inPoint(index: number): { x: number; y: number } {
    return { x: this.rec.x + PORT_INSET, y: this.rec.y + HEAD_H + PORT_PAD + index * ROW_H + ROW_H / 2 };
  }

  outPoint(index: number): { x: number; y: number } {
    return { x: this.rec.x + this.box.w - PORT_INSET, y: this.rec.y + HEAD_H + PORT_PAD + index * ROW_H + ROW_H / 2 };
  }

  dot(side: 'in' | 'out', name: string): HTMLElement | undefined { return this.dots.get(`${side}:${name}`); }

  dispose(): void {
    this.widget?.dispose?.();
    this.widget = null;
    this.el.remove();
  }
}

import { commands } from './commands';
import { docStore } from './doc-store';
import { el, q, setClass, setDisabled, setHidden, setText, setTitle, stored, store } from './dom';
import { onLanguage, t } from './i18n';
import { icon } from './icons';

export interface RailTool { cmd: string; icon: string; label: string }
export interface RailGroupSpec { id: string; name: string; cmds: string[] }

interface Slot {
  id: string;
  name: string;
  tools: RailTool[];
  node: HTMLButtonElement;
  faces: HTMLElement[];
  fly: HTMLElement;
  rows: HTMLButtonElement[];
  face: number;
}

const FACE_KEY = 'formCAD.railFaces';
const HOLD_MS = 350;

function readFaces(): Record<string, string> {
  try {
    const v: unknown = JSON.parse(stored(FACE_KEY) ?? '{}');
    return v && typeof v === 'object' ? (v as Record<string, string>) : {};
  } catch {
    return {};
  }
}

const keyOf = (cmd: string): string => {
  const c = commands.get(cmd);
  return c ? commands.keyLabel(c) : '';
};

export class ToolRail {
  private readonly slots: Slot[] = [];
  private readonly bySlotCmd = new Map<string, { slot: Slot; index: number }>();
  private open: Slot | null = null;
  private suppress = false;
  private lit: Slot | null = null;

  constructor(host: HTMLElement, clusters: RailGroupSpec[][], catalogue: RailTool[]) {
    const byCmd = new Map(catalogue.map((x) => [x.cmd, x]));
    const used = new Set<string>();
    const specs = clusters.map((c) => c.map((g) => ({ ...g, cmds: g.cmds.filter((cmd) => byCmd.has(cmd) && !used.has(cmd) && (used.add(cmd), true)) })).filter((g) => g.cmds.length));
    const rest = catalogue.filter((x) => !used.has(x.cmd)).map((x) => x.cmd);
    if (rest.length) specs.push([{ id: 'more', name: 'More Tools', cmds: rest }]);
    const faces = readFaces();
    const overlay = document.getElementById('overlay-root') ?? document.body;
    specs.filter((c) => c.length).forEach((cluster, ci) => {
      if (ci > 0) host.append(el('<span class="cv-rail-sep" role="separator"></span>'));
      for (const spec of cluster) {
        const tools = spec.cmds.map((cmd) => byCmd.get(cmd) as RailTool);
        const slot = this.build(spec, tools, Math.max(0, tools.findIndex((x) => x.cmd === faces[spec.id])));
        host.append(slot.node);
        overlay.append(slot.fly);
      }
    });
    document.addEventListener('pointerdown', (e) => {
      if (this.open && !this.open.fly.contains(e.target as Node) && !this.open.node.contains(e.target as Node)) this.close(false);
    }, true);
    document.addEventListener('keydown', (e) => {
      if (!this.open) return;
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(true); return; }
      if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !this.open.fly.contains(document.activeElement)) { e.preventDefault(); e.stopPropagation(); this.open.rows[this.open.face]?.focus(); }
    }, true);
    for (const name of ['formcad:command-state', 'formcad:cmdline-applied']) {
      document.addEventListener(name, (e) => {
        const st = (e as CustomEvent<{ state?: { active?: boolean; command?: string } }>).detail?.state;
        this.light(st?.active && st.command ? `x:${st.command.toLowerCase()}` : null);
      });
    }
    docStore.onChange(() => { if (!docStore.current()) this.light(null); });
    window.addEventListener('blur', () => this.close(false));
    this.paint();
    docStore.onChange(() => this.paint());
    onLanguage(() => this.paint());
  }

  private build(spec: RailGroupSpec, tools: RailTool[], face: number): Slot {
    const multi = tools.length > 1;
    const node = el<HTMLButtonElement>(`<button class="cv-tool cv-rail-slot" type="button" data-group="${spec.id}" aria-haspopup="${multi ? 'menu' : 'false'}" aria-expanded="false"></button>`);
    setClass(node, 'has-group', multi);
    const fly = el(`<div class="cv-flyout cv-rail-fly" role="menu" data-group="${spec.id}" hidden><div class="cv-rail-fly-title"></div></div>`);
    const slot: Slot = { id: spec.id, name: spec.name, tools, node, faces: [], fly, rows: [], face };
    this.slots.push(slot);
    tools.forEach((tool, i) => {
      const f = el(icon(tool.icon, 20));
      setHidden(f, i !== face);
      node.append(f);
      slot.faces.push(f);
      const row = el<HTMLButtonElement>(`<button class="cv-flyout-item" type="button" role="menuitemradio" tabindex="-1" aria-checked="false">${icon(tool.icon, 18)}<span class="cv-flyout-label"></span><span class="cv-flyout-key"></span></button>`);
      row.addEventListener('click', () => this.pick(slot, i));
      fly.append(row);
      slot.rows.push(row);
      this.bySlotCmd.set(tool.cmd, { slot, index: i });
    });
    node.addEventListener('mousedown', (e) => e.preventDefault());
    node.addEventListener('click', () => {
      if (this.suppress) { this.suppress = false; return; }
      if (this.open) this.close(false);
      commands.run(slot.tools[slot.face].cmd);
    });
    let hold = 0;
    node.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !multi) return;
      this.suppress = false;
      hold = window.setTimeout(() => { this.suppress = true; this.show(slot, false); }, HOLD_MS);
    });
    for (const ev of ['pointerup', 'pointerleave', 'pointercancel']) node.addEventListener(ev, () => window.clearTimeout(hold));
    node.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (multi && !node.disabled) this.show(slot, false);
    });
    node.addEventListener('keydown', (e) => {
      if (!multi) return;
      if (e.key === 'ArrowRight' || e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey)) { e.preventDefault(); this.show(slot, true); }
    });
    fly.addEventListener('keydown', (e) => this.flyKey(slot, e));
    return slot;
  }

  private flyKey(slot: Slot, e: KeyboardEvent): void {
    const at = slot.rows.indexOf(document.activeElement as HTMLButtonElement);
    const n = slot.rows.length;
    let to = -1;
    if (e.key === 'ArrowDown') to = (at + 1) % n;
    else if (e.key === 'ArrowUp') to = (at - 1 + n) % n;
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = n - 1;
    else if (e.key === 'ArrowLeft') { e.preventDefault(); this.close(true); return; }
    else if (e.key === 'Tab') { e.preventDefault(); this.close(true); return; }
    else return;
    e.preventDefault();
    e.stopPropagation();
    slot.rows[to]?.focus();
  }

  private show(slot: Slot, focus: boolean): void {
    if (this.open && this.open !== slot) this.close(false);
    slot.rows.forEach((row, i) => {
      const on = i === slot.face;
      setClass(row, 'is-active', on);
      if (row.getAttribute('aria-checked') !== String(on)) row.setAttribute('aria-checked', String(on));
      setText(q(row, '.cv-flyout-key'), keyOf(slot.tools[i].cmd));
    });
    const r = slot.node.getBoundingClientRect();
    const fly = slot.fly;
    fly.style.visibility = 'hidden';
    setHidden(fly, false);
    const h = fly.offsetHeight;
    fly.style.left = `${Math.round(r.right + 6)}px`;
    fly.style.top = `${Math.round(Math.max(4, Math.min(r.top - 4, window.innerHeight - h - 4)))}px`;
    fly.style.visibility = '';
    slot.node.setAttribute('aria-expanded', 'true');
    setClass(slot.node, 'is-open', true);
    this.open = slot;
    if (focus) slot.rows[slot.face]?.focus();
  }

  private close(refocus: boolean): void {
    const slot = this.open;
    if (!slot) return;
    this.open = null;
    setHidden(slot.fly, true);
    slot.node.setAttribute('aria-expanded', 'false');
    setClass(slot.node, 'is-open', false);
    if (refocus) slot.node.focus();
  }

  private pick(slot: Slot, i: number): void {
    this.close(false);
    this.setFace(slot, i);
    commands.run(slot.tools[i].cmd);
  }

  private setFace(slot: Slot, i: number): void {
    if (slot.face === i) return;
    setHidden(slot.faces[slot.face], true);
    setHidden(slot.faces[i], false);
    slot.face = i;
    const faces = readFaces();
    faces[slot.id] = slot.tools[i].cmd;
    store(FACE_KEY, JSON.stringify(faces));
    this.title(slot);
  }

  private light(cmd: string | null): void {
    const hit = cmd ? this.bySlotCmd.get(cmd) : undefined;
    if (hit) this.setFace(hit.slot, hit.index);
    const next = hit?.slot ?? null;
    if (next === this.lit) return;
    if (this.lit) setClass(this.lit.node, 'is-active', false);
    if (next) setClass(next.node, 'is-active', true);
    this.lit = next;
  }

  private title(slot: Slot): void {
    const tool = slot.tools[slot.face];
    const key = keyOf(tool.cmd);
    const label = t(tool.label);
    const base = key ? `${label} (${key})` : label;
    setTitle(slot.node, slot.tools.length > 1 ? `${base} · ${t(slot.name)}: ${t('hold or right-click for more tools')}` : base);
    if (slot.node.getAttribute('aria-label') !== label) slot.node.setAttribute('aria-label', label);
  }

  private paint(): void {
    const on = !!docStore.current();
    if (!on) this.close(false);
    for (const slot of this.slots) {
      setDisabled(slot.node, !on);
      this.title(slot);
      setText(q(slot.fly, '.cv-rail-fly-title'), t(slot.name));
      if (slot.fly.getAttribute('aria-label') !== t(slot.name)) slot.fly.setAttribute('aria-label', t(slot.name));
      slot.rows.forEach((row, i) => setText(q(row, '.cv-flyout-label'), t(slot.tools[i].label)));
    }
  }
}

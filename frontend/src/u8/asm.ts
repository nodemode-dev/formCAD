import * as THREE from 'three';
import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { view3d } from '../view3d/mount';
import { matrixOf } from './geo';
import { docUrl, EngineError, req } from './net';

export interface TreeNode {
  key: string;
  cid: string;
  depth: number;
  label: string;
  type: string;
  suppressed: boolean;
  visible: boolean;
  status: string;
  stale: boolean;
  lightweight?: boolean;
  world: number[];
  pattern: string | null;
  index: number;
  children: TreeNode[];
}

export interface MateRow {
  id: number;
  name: string;
  label: string;
  kind: string;
  suppressed: boolean;
  text: string;
  state: string;
  removes: number;
  redundant?: boolean;
  residual: number;
  reason?: string;
}

export interface Explanation {
  kind: string;
  message: string;
  mates: Array<{ id: number; name: string; text: string; new?: boolean }>;
  fixes: Array<{ id: number; name: string; text: string }>;
}

export interface MatesStatus {
  solved: boolean;
  state: string;
  dof: number;
  components: Record<string, { dof: number; state: string; modes: unknown[] }>;
  mates: MateRow[];
  conflict?: Explanation;
}

export interface ExplodeStep { id: number; name: string; comps: string[]; dir: number[]; dist: number }
export interface ExplodeList { active: string; views: Record<string, { name: string; steps: ExplodeStep[] }> }

export type Poses = Record<string, number[]>;

export const isAssembly = (): boolean => docStore.current()?.kind === 'assembly';

export function explanationOf(e: unknown): Explanation | null {
  if (!(e instanceof EngineError) || !e.detail || typeof e.detail !== 'object') return null;
  const d = e.detail as { explanation?: Explanation; message?: string };
  if (d.explanation && Array.isArray(d.explanation.mates)) return d.explanation;
  return null;
}

class AsmStore {
  tree: TreeNode[] = [];
  status: MatesStatus | null = null;
  explode: ExplodeList = { active: '', views: {} };
  selected = '';
  worlds = new Map<string, THREE.Matrix4>();
  private readonly subs = new Set<() => void>();
  private timer = 0;
  private busy = false;
  private again = false;

  onChange(fn: () => void): void { this.subs.add(fn); }
  private emit(): void { for (const f of this.subs) f(); }

  id(): string | null { return docStore.activeId; }

  schedule(delay = 150): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, delay);
  }

  async refresh(): Promise<void> {
    if (this.busy) { this.again = true; return; }
    const id = this.id();
    if (!id || !isAssembly()) { this.tree = []; this.status = null; this.explode = { active: '', views: {} }; this.worlds.clear(); this.emit(); return; }
    this.busy = true;
    try {
      do {
        this.again = false;
        const [tree, status, explode] = await Promise.all([
          req<{ tree: TreeNode[] }>('GET', docUrl(id, 'assembly/tree')),
          req<MatesStatus>('GET', docUrl(id, 'mates/status')).catch(() => null),
          req<ExplodeList>('GET', docUrl(id, 'mates/explode')).catch(() => ({ active: '', views: {} })),
        ]);
        if (id !== this.id()) break;
        this.tree = tree.tree;
        this.status = status;
        this.explode = explode;
        this.worlds.clear();
        const walk = (n: TreeNode): void => {
          if (n.depth === 0 && !n.index) this.worlds.set(n.cid, matrixOf(n.world));
          n.children.forEach(walk);
        };
        this.tree.forEach(walk);
        this.emit();
      } while (this.again);
    } finally {
      this.busy = false;
    }
  }

  flat(): TreeNode[] {
    const out: TreeNode[] = [];
    const walk = (n: TreeNode): void => { out.push(n); n.children.forEach(walk); };
    this.tree.forEach(walk);
    return out;
  }

  bodiesOf(cids: string[]): number[] {
    const vp = view3d()?.vp;
    if (!vp) return [];
    const want = new Set(cids);
    const out: number[] = [];
    for (const [bid, v] of vp.bodyViews) if (want.has(topOf(v.data.instance || v.data.component || ''))) out.push(bid);
    return out;
  }

  componentOfBody(bid: number): string {
    const v = view3d()?.vp?.bodyViews.get(bid);
    return v ? topOf(v.data.instance || v.data.component || '') : '';
  }

  select(cids: string[]): void {
    this.selected = cids[0] ?? '';
    view3d()?.vp?.setBodySelection(this.bodiesOf(cids));
    this.emit();
  }

  showPoses(poses: Poses | null): void {
    const vp = view3d()?.vp;
    if (!vp) return;
    if (!poses) { vp.setPoses(null); return; }
    const map = new Map<number, THREE.Matrix4 | null>();
    for (const [bid, v] of vp.bodyViews) {
      const top = topOf(v.data.instance || v.data.component || '');
      const next = poses[top];
      const old = this.worlds.get(top);
      if (next && old) map.set(bid, matrixOf(next).multiply(old.clone().invert()));
    }
    vp.setPoses(map);
  }

  showOffsets(offsets: Record<string, number[]> | null): void {
    const vp = view3d()?.vp;
    if (!vp) return;
    if (!offsets) { vp.setPoses(null); return; }
    const map = new Map<number, THREE.Matrix4 | null>();
    for (const [bid, v] of vp.bodyViews) {
      const o = offsets[topOf(v.data.instance || v.data.component || '')];
      if (o) map.set(bid, new THREE.Matrix4().makeTranslation(o[0], o[1], o[2]));
    }
    vp.setPoses(map);
  }
}

export const topOf = (instance: string): string => instance.split(/[/#]/)[0];

export const asm = new AsmStore();

events.on('doc', (e) => { if (e.id === docStore.activeId) asm.schedule(); });
docStore.onChange(() => asm.schedule(50));

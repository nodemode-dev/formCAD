import * as THREE from 'three';
import { tokenHex } from '../canvas/ink';
import { MEDIA } from '../canvas/media';
import { token } from '../io/api';
import type { ViewLayer } from '../view3d/layer';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { ec } from './store';

interface Parsed { geo: THREE.BufferGeometry; min: Vec3; max: Vec3; triangles: number }

function parse(buf: ArrayBuffer): Parsed {
  const dv = new DataView(buf);
  const u = (i: number): number => dv.getUint32(i * 4, true);
  if (u(0) !== 0x4d424346) throw new Error('The board mesh has the wrong header.');
  const nv = u(2), nt = u(3);
  const pos = new Float32Array(buf.slice(u(8), u(8) + nv * 12));
  const nor = new Float32Array(buf.slice(u(9), u(9) + nv * 12));
  const idx = new Uint32Array(buf.slice(u(10), u(10) + nt * 12));
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < pos.length; i += 3) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], pos[i + k]); max[k] = Math.max(max[k], pos[i + k]); }
  return { geo, min, max, triangles: nt };
}

async function fetchMesh(id: string, which: string): Promise<ArrayBuffer | null> {
  const headers: Record<string, string> = {};
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  const res = await fetch(`/api/docs/${encodeURIComponent(id)}/ecad/board3d/mesh?which=${which}`, { headers });
  if (!res.ok) return null;
  return res.arrayBuffer();
}

export class BoardLayer implements ViewLayer {
  readonly group = new THREE.Group();
  readonly stats = { board: 0, components: 0, loads: 0 };
  private readonly board = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshLambertMaterial());
  private readonly parts = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshLambertMaterial());
  private box: { min: Vec3; max: Vec3 } | null = null;
  private key = '';
  private busy = false;

  constructor(private readonly vp: Viewport3D) {
    this.group.add(this.board, this.parts);
    this.group.visible = false;
  }

  bounds(): { min: Vec3; max: Vec3 } | null { return this.group.visible ? this.box : null; }

  colors(host: HTMLElement): void {
    (this.board.material as THREE.MeshLambertMaterial).color.setHex(tokenHex('--ec-board', MEDIA.boardSubstrate, host));
    (this.parts.material as THREE.MeshLambertMaterial).color.setHex(tokenHex('--ec-comp', MEDIA.boardParts, host));
  }

  palette(): void { this.colors(document.body); }

  setShown(on: boolean): void {
    if (this.group.visible !== on) { this.group.visible = on; this.vp.invalidate(); }
  }

  setComponents(on: boolean): void { if (this.parts.visible !== on) { this.parts.visible = on; this.vp.invalidate(); } }

  async load(force = false): Promise<void> {
    const id = ec.docId;
    if (!id || this.busy) return;
    const key = `${id}:${ec.rev}`;
    if (!force && key === this.key) return;
    this.busy = true;
    try {
      const [b, c] = await Promise.all([fetchMesh(id, 'board'), fetchMesh(id, 'components')]);
      if (!b) return;
      const pb = parse(b);
      this.board.geometry.dispose();
      this.board.geometry = pb.geo;
      this.stats.board = pb.triangles;
      const min = [...pb.min] as Vec3, max = [...pb.max] as Vec3;
      if (c) {
        const pc = parse(c);
        this.parts.geometry.dispose();
        this.parts.geometry = pc.geo;
        this.stats.components = pc.triangles;
        for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], pc.min[k]); max[k] = Math.max(max[k], pc.max[k]); }
      }
      this.box = { min, max };
      this.stats.loads++;
      this.key = key;
      this.vp.invalidate();
    } finally {
      this.busy = false;
    }
  }

  dispose(): void { this.board.geometry.dispose(); this.parts.geometry.dispose(); }
}

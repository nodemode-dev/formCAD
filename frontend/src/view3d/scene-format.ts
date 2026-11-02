import { DEFAULT_BODY_COLOR } from './kit';
import type { BodyData, SnapKind, SnapPoint } from './types';

const MAGIC = 0x43534346;
const VERSION = 1;
const RECORD = 128;
const FLAG_VISIBLE = 1;
const FLAG_MESHED = 2;
const NO_COLOUR = 0xffffffff;
const SNAP_KINDS: SnapKind[] = ['vertex', 'midpoint', 'center'];

export interface ParsedScene {
  rev: number;
  delta: boolean;
  removed: number[];
  bodies: BodyData[];
  hidden: number[];
  mmPerUnit: number;
}

let crcTable: Uint32Array | null = null;

function crc32(bytes: Uint8Array): number {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) crc = crcTable[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

export class SceneFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SceneFormatError';
  }
}

function aligned(buf: ArrayBuffer, at: number, count: number, size: number): void {
  if (at % 4 !== 0 || at + count * size > buf.byteLength) throw new SceneFormatError('The 3D data has a section outside the buffer.');
}

export function parseScene(buf: ArrayBuffer, verify = true): ParsedScene {
  if (buf.byteLength < 64) throw new SceneFormatError('The 3D data is truncated.');
  const dv = new DataView(buf);
  const u = (i: number): number => dv.getUint32(i * 4, true);
  if (u(0) !== MAGIC) throw new SceneFormatError('The 3D data has the wrong header.');
  if (u(1) !== VERSION) throw new SceneFormatError('The 3D data has a version this build cannot read.');
  const total = u(3);
  if (total !== buf.byteLength) throw new SceneFormatError('The 3D data length does not match its header.');
  const head = u(2);
  const rev = u(4), rows = u(5), delta = u(6) === 1, removedCount = u(7);
  const tableAt = u(8), removedAt = u(9), metaAt = u(10), metaLen = u(11);
  const mm = dv.getFloat32(13 * 4, true);
  if (verify && crc32(new Uint8Array(buf, head)) !== u(12)) throw new SceneFormatError('The 3D data fails its checksum.');
  if (tableAt + rows * RECORD > buf.byteLength || removedAt + removedCount * 4 > buf.byteLength || metaAt + metaLen > buf.byteLength) throw new SceneFormatError('The 3D data tables are outside the buffer.');
  let names = new Map<number, string>();
  try {
    const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, metaAt, metaLen))) as { bodies?: Array<{ handle: number; name?: string }> };
    names = new Map((meta.bodies ?? []).map((b) => [b.handle, b.name ?? '']));
  } catch {
    names = new Map();
  }
  const removed: number[] = [];
  for (let i = 0; i < removedCount; i++) removed.push(dv.getUint32(removedAt + i * 4, true));
  const bodies: BodyData[] = [];
  const hidden: number[] = [];
  for (let r = 0; r < rows; r++) {
    const o = tableAt + r * RECORD;
    const w = (i: number): number => dv.getUint32(o + i * 4, true);
    const handle = w(0), flags = w(2), colour = w(3);
    if (!(flags & FLAG_VISIBLE) || !(flags & FLAG_MESHED)) { hidden.push(handle); continue; }
    const nv = w(4), nt = w(5), nf = w(6), ne = w(7), np = w(8), ns = w(9);
    const [oPos, oNor, oIdx, oTri, oFaces, oEdges, oEpos, oSnaps] = [w(10), w(11), w(12), w(13), w(14), w(15), w(16), w(17)];
    aligned(buf, oPos, nv * 3, 4); aligned(buf, oNor, nv * 3, 4); aligned(buf, oIdx, nt * 3, 4); aligned(buf, oTri, nt, 4);
    aligned(buf, oFaces, nf * 4, 4); aligned(buf, oEdges, ne * 4, 4); aligned(buf, oEpos, np * 3, 4); aligned(buf, oSnaps, ns * 8, 4);
    const positions = new Float32Array(buf, oPos, nv * 3);
    const normals = new Float32Array(buf, oNor, nv * 3);
    const indices = new Uint32Array(buf, oIdx, nt * 3);
    const localFace = new Uint32Array(buf, oTri, nt);
    const faceRows = new Uint32Array(buf, oFaces, nf * 4);
    const triFace = new Uint32Array(nt);
    const facePids = new Set<number>();
    for (let f = 0; f < nf; f++) facePids.add(faceRows[f * 4]);
    const useFacePid = facePids.size === nf;
    for (let t = 0; t < nt; t++) {
      const lf = localFace[t];
      triFace[t] = useFacePid && lf < nf ? faceRows[lf * 4] : lf;
    }
    const edgeRows = new Uint32Array(buf, oEdges, ne * 4);
    const edgePids = new Set<number>();
    for (let e = 0; e < ne; e++) edgePids.add(edgeRows[e * 4]);
    const useEdgePid = edgePids.size === ne;
    const epos = new Float32Array(buf, oEpos, np * 3);
    let segTotal = 0;
    for (let e = 0; e < ne; e++) segTotal += Math.max(0, edgeRows[e * 4 + 2] - 1);
    const segPos = new Float32Array(segTotal * 6);
    const segEdge = new Uint32Array(segTotal);
    let s = 0;
    for (let e = 0; e < ne; e++) {
      const pid = useEdgePid ? edgeRows[e * 4] : e, first = edgeRows[e * 4 + 1], n = edgeRows[e * 4 + 2];
      if ((first + n) * 3 > epos.length) throw new SceneFormatError('The 3D data has an edge outside its point list.');
      for (let i = 0; i + 1 < n; i++) {
        const a = (first + i) * 3;
        segPos.set(epos.subarray(a, a + 6), s * 6);
        segEdge[s++] = pid;
      }
    }
    const snaps: SnapPoint[] = [];
    const sv = new DataView(buf, oSnaps, ns * 32);
    for (let i = 0; i < ns; i++) {
      const k = sv.getUint32(i * 32 + 12, true);
      snaps.push({ kind: SNAP_KINDS[k] ?? 'other', p: [sv.getFloat32(i * 32, true), sv.getFloat32(i * 32 + 4, true), sv.getFloat32(i * 32 + 8, true)], body: handle, ref: sv.getUint32(i * 32 + 16, true) });
    }
    bodies.push({
      id: handle,
      name: names.get(handle) || `Body ${handle}`,
      color: colour === NO_COLOUR ? DEFAULT_BODY_COLOR : colour,
      positions, normals, indices, triFace,
      edges: { positions: segPos, segEdge },
      snaps,
    });
  }
  return { rev, delta, removed, bodies, hidden, mmPerUnit: mm };
}

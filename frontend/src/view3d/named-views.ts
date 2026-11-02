import { ApiError } from '../io/api';
import { cad, type ViewRow } from '../io/api-cad';
import type { CameraSpec } from './types';

export const VIEW_PREFIX = '3D ';

export interface NamedView3d { name: string; camera: CameraSpec }
type Row = ViewRow & { camera3d?: CameraSpec };

const valid = (c: unknown): c is CameraSpec => {
  const s = c as CameraSpec | undefined;
  return !!s && Array.isArray(s.position) && s.position.length === 3 && Array.isArray(s.target) && s.target.length === 3 && typeof s.height === 'number';
};

export async function listNamedViews(docId: string): Promise<NamedView3d[]> {
  const rows = (await cad.views(docId)).views as Row[];
  const out: NamedView3d[] = [];
  for (const r of rows) {
    if (r.name.startsWith(VIEW_PREFIX) && valid(r.camera3d)) out.push({ name: r.name.slice(VIEW_PREFIX.length), camera: r.camera3d });
  }
  return out;
}

export async function saveNamedView(docId: string, name: string, camera: CameraSpec): Promise<void> {
  await cad.viewAction(docId, { action: 'save', name: VIEW_PREFIX + name, snapshot: false, camera3d: camera });
}

export async function deleteNamedView(docId: string, name: string): Promise<void> {
  await cad.viewAction(docId, { action: 'delete', name: VIEW_PREFIX + name });
}

export const failure = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');

import { call } from '../io/api';
import type { ConstructionPlane, GridAsk, GridLines, PlaneSpec } from './types';

const enc = encodeURIComponent;

export async function fetchPlane(doc: string, spec: PlaneSpec): Promise<ConstructionPlane> {
  const res = await call<{ plane: ConstructionPlane }>('POST', `/api/docs/${enc(doc)}/plane`, spec);
  return res.plane;
}

export function fetchGrid(doc: string, ask: GridAsk): Promise<GridLines> {
  return call<GridLines>('POST', `/api/docs/${enc(doc)}/grid`, ask);
}

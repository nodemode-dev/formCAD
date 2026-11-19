import { call, type DocSummary } from '../io/api';

export type DemoId = 'drafting' | 'part' | 'graph';

export interface DemoInfo { id: DemoId; title: string; line: string; picture: string }

const BASE = `${import.meta.env.BASE_URL}demos/`;

export const DEMOS: readonly DemoInfo[] = [
  { id: 'drafting', title: '2D drafting', line: 'A dimensioned floor plan with layers, blocks, hatches and a title block on an A3 sheet.', picture: `${BASE}drafting.webp` },
  { id: 'part', title: 'Parametric part', line: 'A plate with a boss, a shell, a pocket, a hole pattern, fillets and a chamfer, with its feature tree.', picture: `${BASE}part.webp` },
  { id: 'graph', title: 'Node graph', line: 'A plate with a ring of bolt holes driven by a visual program.', picture: `${BASE}graph.webp` },
];

export const isDemo = (id: string | undefined): id is DemoId => DEMOS.some((d) => d.id === id);

export function openDemo(id: DemoId): Promise<DocSummary> {
  return call<DocSummary>('POST', `/api/demos/${encodeURIComponent(id)}/open`);
}

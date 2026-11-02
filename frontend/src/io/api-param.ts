import { ApiError, token } from './api';

const enc = encodeURIComponent;

export interface ExplainItem { id: number; kind: string; label: string; text: string; handles: number[]; new?: boolean }
export interface Explanation { kind: 'conflict' | 'redundant'; constraints: ExplainItem[]; new: number; minimal: boolean; message: string }
export interface ParamRow {
  name: string;
  expr: string;
  type: string;
  group: 'dimensional' | 'user';
  driving: boolean;
  constraint: number | null;
  sketch: string;
  unit: string;
  comment?: string;
  value: number | null;
  error: string;
  shown: string;
}
export interface ParamList { parameters: ParamRow[]; dimensional: ParamRow[]; user: ParamRow[] }
export interface ConstraintStatus {
  status: 'none' | 'under' | 'fully' | 'over';
  dof: number;
  entities: Record<string, { status: string; dof: number }>;
  redundant: ExplainItem[];
  conflicts: ExplainItem[];
  dangling: number[];
  constraints: number;
  ms: number;
  sketch: string;
}
export interface SketchInfo { name: string; status?: string; dof?: number; entities?: number[] | number; plane?: unknown }

export class Refusal extends ApiError {
  constructor(status: number, message: string, readonly explanation: Explanation | null) {
    super(status, message);
    this.name = 'Refusal';
  }
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, 'The engine is not reachable');
  }
  if (!res.ok) {
    let message = res.statusText || `Request failed (${res.status})`;
    let explanation: Explanation | null = null;
    try {
      const data = await res.json() as { detail?: unknown };
      const d = data.detail;
      if (typeof d === 'string') message = d;
      else if (d && typeof d === 'object') {
        const o = d as { message?: unknown; explanation?: unknown };
        if (typeof o.message === 'string') message = o.message;
        if (o.explanation && typeof o.explanation === 'object') explanation = o.explanation as Explanation;
      }
    } catch {
      message = res.statusText || message;
    }
    if (explanation) throw new Refusal(res.status, message, explanation);
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return await res.json() as T;
}

const base = (id: string): string => `/api/docs/${enc(id)}`;

export const param = {
  list: (id: string): Promise<ParamList> => send('GET', `${base(id)}/parameters`),
  add: (id: string, name: string, expr: string, unit?: string): Promise<unknown> => send('POST', `${base(id)}/parameters`, unit ? { name, expr, unit } : { name, expr }),
  edit: (id: string, name: string, body: { expr?: string; unit?: string; comment?: string; new_name?: string; driving?: boolean }): Promise<unknown> => send('PUT', `${base(id)}/parameters/${enc(name)}`, body),
  remove: (id: string, name: string): Promise<unknown> => send('DELETE', `${base(id)}/parameters/${enc(name)}`),
  status: (id: string, sketch = ''): Promise<ConstraintStatus> => send('GET', `${base(id)}/constraintstatus${sketch ? `?sketch=${enc(sketch)}` : ''}`),
  deleteConstraint: (id: string, cid: number): Promise<unknown> => send('DELETE', `${base(id)}/constraints/${cid}`),
  addConstraint: (id: string, body: Record<string, unknown>): Promise<unknown> => send('POST', `${base(id)}/constraints`, body),
  sketches: (id: string): Promise<{ sketches: SketchInfo[] }> => send('GET', `${base(id)}/sketches`),
};

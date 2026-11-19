import recording from '../recordings/part.json';
import { installReplay, type Recording, type ReplayRequest } from '../../../demo/src/shim/replay';

const rec = recording as unknown as Recording;

try { if (!localStorage.getItem('formCAD.workspace')) localStorage.setItem('formCAD.workspace', 'part'); } catch { void 0; }

interface Picked { handles: Array<string | number>; faces: unknown[]; edges: unknown[]; owners: unknown[] }

const held = new Map<string, Picked>();
const empty = (): Picked => ({ handles: [], faces: [], edges: [], owners: [] });

const selection = (req: ReplayRequest): unknown => {
  const m = /^\/api\/docs\/([^/]+)\/selection$/.exec(req.path);
  if (!m) return undefined;
  const doc = decodeURIComponent(m[1]);
  const now = held.get(doc) ?? empty();
  if (req.method === 'GET') return { ...now, pickfirst: true, rev: 0 };
  if (req.method !== 'PUT') return undefined;
  let ask: Partial<Picked> & { mode?: string } = {};
  try { ask = JSON.parse(req.body ?? '{}') as typeof ask; } catch { ask = {}; }
  const keep = ask.mode === 'add' || ask.mode === 'remove';
  const handles = new Set(keep ? now.handles : []);
  for (const h of ask.handles ?? []) { if (ask.mode === 'remove') handles.delete(h); else handles.add(h); }
  const next: Picked = {
    handles: [...handles],
    faces: ask.faces ?? (keep ? now.faces : []),
    edges: ask.edges ?? (keep ? now.edges : []),
    owners: ask.owners ?? (keep ? now.owners : []),
  };
  held.set(doc, next);
  return { ...next, pickfirst: true, rev: 0 };
};

const handle = installReplay(rec, {
  reads: [/\/snap3d$/, /\/scene-at$/],
  local: selection,
});

Object.assign(window, { formcadReplay: { document: rec.document, misses: handle.misses } });

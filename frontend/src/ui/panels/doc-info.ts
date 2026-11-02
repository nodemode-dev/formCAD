import type { DocSummary } from '../../io/api';
import type { DockPanel } from '../dock';
import { infoRow } from './pref-rows';

export interface DocInfoDeps {
  current: () => DocSummary | null;
  onDocs: (fn: () => void) => () => void;
  num: (name: string, fallback: number) => number;
  onVars: (fn: () => void) => () => void;
}

const LINEAR = ['', 'Scientific', 'Decimal', 'Engineering', 'Architectural', 'Fractional'];
const ANGULAR = ['Decimal degrees', 'Degrees, minutes, seconds', 'Gradians', 'Radians', 'Surveyor’s units'];

const stamp = (v: unknown): string => {
  if (typeof v !== 'string' || !v) return '';
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString();
};

export function docInfoPanel(deps: DocInfoDeps): DockPanel {
  return {
    id: 'doc-info',
    label: 'Document Info',
    icon: 'info',
    order: 10,
    build(body) {
      const rows = {
        name: infoRow('Name'),
        path: infoRow('Path'),
        status: infoRow('Status'),
        rev: infoRow('Revision'),
        space: infoRow('Space'),
        entities: infoRow('Objects'),
        units: infoRow('Units'),
        linear: infoRow('Linear format'),
        angular: infoRow('Angular format'),
        tolerance: infoRow('Tolerance'),
        created: infoRow('Created'),
      };
      body.classList.add('cv-docinfo');
      for (const r of Object.values(rows)) body.appendChild(r.el);
      const paint = (): void => {
        const d = deps.current();
        rows.name.set(d?.name ?? '');
        rows.path.set(d ? d.path ?? 'Not saved yet' : '');
        rows.status.set(d ? (d.dirty ? 'Unsaved changes' : 'Saved') : '');
        rows.rev.set(d ? String(d.rev) : '');
        rows.space.set(d?.space ?? '');
        rows.entities.set(d && d.entities !== undefined ? String(d.entities) : '');
        rows.units.set(d ? (d.metric === undefined ? '' : d.metric ? 'Metric (millimetres)' : 'Imperial (inches)') : '');
        const lunits = deps.num('LUNITS', 2), luprec = deps.num('LUPREC', 4), aunits = deps.num('AUNITS', 0), auprec = deps.num('AUPREC', 0);
        rows.linear.set(d ? `${LINEAR[lunits] ?? 'Decimal'}, ${luprec} places` : '');
        rows.angular.set(d ? `${ANGULAR[aunits] ?? 'Decimal degrees'}, ${auprec} places` : '');
        rows.tolerance.set(d ? `±${(0.5 * Math.pow(10, -luprec)).toFixed(Math.min(12, luprec + 1))}` : '');
        rows.created.set(d ? stamp(d.created) : '');
      };
      paint();
      deps.onDocs(paint);
      deps.onVars(paint);
    },
  };
}

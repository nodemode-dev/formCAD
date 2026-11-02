export const TYPE_ICON: Record<string, string> = {
  sketch: 'sketch',
  extrude: 'extrude',
  extrude_cut: 'ftExtrudeCut',
  revolve: 'revolve',
  revolve_cut: 'ftRevolveCut',
  fillet: 'fillet',
  chamfer: 'chamfer',
  shell: 'ftShell',
  draft: 'ftDraft',
  pattern: 'ftPattern',
  mirror: 'mirror',
  sweep: 'ftSweep',
  sweep_cut: 'ftSweep',
  loft: 'ftLoft',
  loft_cut: 'ftLoft',
  boundary_solid: 'ftBoundary',
  rib: 'ftRib',
  hole: 'ftHole',
};

export const iconFor = (type: string): string => TYPE_ICON[type] ?? 'part';

export interface CreateEntry { type: string; label: string; cmd: string; group: 'shape' | 'dressup' | 'pattern' }

export const CREATE: CreateEntry[] = [
  { type: 'extrude', label: 'Extrude', cmd: 'pt-extrude', group: 'shape' },
  { type: 'extrude_cut', label: 'Extruded Cut', cmd: 'pt-extrude-cut', group: 'shape' },
  { type: 'revolve', label: 'Revolve', cmd: 'pt-revolve', group: 'shape' },
  { type: 'revolve_cut', label: 'Revolved Cut', cmd: 'pt-revolve-cut', group: 'shape' },
  { type: 'sweep', label: 'Sweep', cmd: 'pt-sweep', group: 'shape' },
  { type: 'sweep_cut', label: 'Swept Cut', cmd: 'pt-sweep-cut', group: 'shape' },
  { type: 'loft', label: 'Loft', cmd: 'pt-loft', group: 'shape' },
  { type: 'loft_cut', label: 'Lofted Cut', cmd: 'pt-loft-cut', group: 'shape' },
  { type: 'boundary_solid', label: 'Boundary Solid', cmd: 'pt-boundary', group: 'shape' },
  { type: 'rib', label: 'Rib', cmd: 'pt-rib', group: 'shape' },
  { type: 'hole', label: 'Hole Builder', cmd: 'pt-hole', group: 'shape' },
  { type: 'fillet', label: 'Fillet', cmd: 'pt-fillet', group: 'dressup' },
  { type: 'chamfer', label: 'Chamfer', cmd: 'pt-chamfer', group: 'dressup' },
  { type: 'shell', label: 'Shell', cmd: 'pt-shell', group: 'dressup' },
  { type: 'draft', label: 'Draft', cmd: 'pt-draft', group: 'dressup' },
  { type: 'pattern', label: 'Pattern', cmd: 'pt-pattern', group: 'pattern' },
  { type: 'mirror', label: 'Mirror', cmd: 'pt-mirror', group: 'pattern' },
];

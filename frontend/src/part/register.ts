import { onShellMounted } from '../app';
import { registerDockPanel } from '../ui/dock';
import { commands } from '../ui/commands';
import { registerInterceptor } from '../ui/dialogs/intercept';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setDisabled, setTitle } from '../ui/dom';
import { onLanguage, t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { onView3d, view3d } from '../view3d/mount';
import { part } from './api';
import { configPanel, DesignTableDialog } from './config-ui';
import { FeatureEditor } from './feature-editor';
import { CREATE } from './kinds';
import { MassDialog, MaterialDialog } from './material-ui';
import { refGeoPanel, watchReference } from './refgeo-ui';
import { SketchEntry } from './sketch-entry';
import { messageOf, partStore } from './store';
import { featureTreePanel } from './tree-panel';

let editor: FeatureEditor | null = null;
let sketches: SketchEntry | null = null;
let table: DesignTableDialog | null = null;
let materials: MaterialDialog | null = null;
let mass: MassDialog | null = null;

const hasDoc = (): boolean => !!docStore.current();
const failed = (e: unknown): void => { toast(messageOf(e), 'error'); };

const TOOLBAR: Array<[string, string, string]> = [
  ['pt-sketch', 'sketch', 'Start Sketch'],
  ['pt-extrude', 'extrude', 'Extrude'],
  ['pt-extrude-cut', 'ftExtrudeCut', 'Extruded Cut'],
  ['pt-revolve', 'revolve', 'Revolve'],
  ['pt-sweep', 'ftSweep', 'Sweep'],
  ['pt-loft', 'ftLoft', 'Loft'],
  ['pt-hole', 'ftHole', 'Hole Builder'],
  ['pt-fillet', 'fillet', 'Fillet'],
  ['pt-chamfer', 'chamfer', 'Chamfer'],
  ['pt-shell', 'ftShell', 'Shell'],
  ['pt-draft', 'ftDraft', 'Draft'],
  ['pt-pattern', 'ftPattern', 'Pattern'],
  ['pt-mirror', 'mirror', 'Mirror'],
  ['pt-mass', 'ftMass', 'Mass Properties'],
];

function add(id: string, label: string, run: () => void, enabled: () => boolean = hasDoc): void {
  if (commands.get(id)) return;
  commands.add({ id, label, group: 'Part', run, enabled });
}

function registerCommands(): void {
  add('pt-sketch', 'Start Sketch', () => { void sketches?.start(); });
  add('pt-finish-sketch', 'Finish Sketch', () => { void sketches?.finish(); }, () => !!sketches && sketches.name !== '');
  add('pt-edit-sketch', 'Edit Selected Sketch', () => {
    const f = partStore.find(partStore.selected);
    if (f && f.type === 'sketch') void sketches?.edit(f.id);
    else toast(t('Select a sketch in the feature tree first.'));
  });
  for (const c of CREATE) add(c.cmd, c.label, () => { void editor?.openNew(c.type); });
  add('pt-edit', 'Edit Selected Feature', () => {
    const f = partStore.selected;
    if (f) void editor?.openEdit(f); else toast(t('Select a feature in the feature tree first.'));
  });
  add('pt-rebuild', 'Rebuild', () => { void partStore.run((id) => part.rebuild(id, false)); });
  add('pt-force-rebuild', 'Force Full Rebuild', () => { void partStore.run((id) => part.rebuild(id, true)); });
  add('pt-roll-end', 'Roll Forward to End', () => { void partStore.run((id) => part.rollback(id, null)); });
  add('pt-design-table', 'Design Table...', () => { void table?.showFor().catch(failed); });
  add('pt-materials', 'Materials...', () => { void materials?.showFor().catch(failed); });
  add('pt-mass', 'Mass Properties...', () => { void mass?.showFor().catch(failed); });
}

function buildToolbar(host: HTMLElement): void {
  const bar = el<HTMLElement>('<div class="pt-tools3d" role="toolbar" aria-label="Part tools"></div>');
  for (const [cmd, ic, label] of TOOLBAR) {
    const b = el<HTMLButtonElement>(`<button class="v3-btn" type="button" data-cmd="${cmd}">${icon(ic, 16)}</button>`);
    b.dataset.label = label;
    bar.appendChild(b);
  }
  host.appendChild(bar);
  const words = (): void => {
    for (const b of Array.from(bar.querySelectorAll<HTMLButtonElement>('button'))) setTitle(b, t(b.dataset.label ?? ''));
  };
  const state = (): void => {
    for (const b of Array.from(bar.querySelectorAll<HTMLButtonElement>('button'))) {
      const c = commands.get(b.dataset.cmd ?? '');
      setDisabled(b, !(c?.enabled?.() ?? true));
    }
  };
  words();
  state();
  onLanguage(words);
  docStore.onChange(state);
  partStore.onChange(state);
}

function autoEnter(): void {
  const seen = new Set<string>();
  const check = async (): Promise<void> => {
    const id = docStore.activeId;
    const c = view3d();
    const tree = partStore.tree;
    if (!id || !c || !tree || seen.has(id)) return;
    seen.add(id);
    let wanted = tree.features.length > 0;
    if (!wanted) {
      try { wanted = (await part.bodies(id)).some((b) => (b.summary.solids ?? 0) > 0); } catch { wanted = false; }
      if (docStore.activeId !== id) return;
    }
    const space = docStore.current()?.space ?? '';
    if (wanted && !c.on && !space.startsWith('sketch:')) await c.enter();
  };
  partStore.onChange(() => { void check(); });
  onView3d(() => { void check(); });
  void check();
}

registerInterceptor(['bodymass', 'massprops3d'], () => { if (!hasDoc()) return false; void mass?.showFor().catch(failed); return true; });
registerInterceptor(['material'], () => { if (!hasDoc()) return false; void materials?.showFor().catch(failed); return true; });
registerInterceptor(['designtable'], () => { if (!hasDoc()) return false; void table?.showFor().catch(failed); return true; });

onShellMounted((ctx) => {
  table = new DesignTableDialog();
  materials = new MaterialDialog();
  mass = new MassDialog();
  sketches = new SketchEntry(ctx.hosts.stage);
  registerCommands();
  registerDockPanel(featureTreePanel({ edit: (fid) => { void editor?.openEdit(fid); } }));
  registerDockPanel(configPanel(() => table as DesignTableDialog));
  registerDockPanel(refGeoPanel());
  watchReference();
  autoEnter();
  onView3d(() => {
    const host = q(ctx.hosts.stage, '.cv-view3d');
    editor = new FeatureEditor(host);
    buildToolbar(host);
    setClass(host, 'has-part', true);
  });
});

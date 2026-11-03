import { onShellMounted } from '../app';
import { messageOf } from '../part/store';
import { commands } from '../ui/commands';
import { registerDockPanel } from '../ui/dock';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setDisabled, setTitle } from '../ui/dom';
import { onLanguage, t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { onView3d, view3d } from '../view3d/mount';
import type { CameraSpec } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { cutListPanel } from './cutlist-panel';
import { FlatExportDialog } from './export-dialog';
import { FlatLayer } from './flat-layer';
import { RuleDialog } from './rule-dialog';
import { sheetStore } from './store';
import { TableDialog } from './table-dialog';

let rule: RuleDialog | null = null;
let tables: TableDialog | null = null;
let exporter: FlatExportDialog | null = null;
let layer: FlatLayer | null = null;
let lastOn = false;
let saved: CameraSpec | null = null;

const hasDoc = (): boolean => !!docStore.current();
const isSheet = (): boolean => sheetStore.isSheet;
const failed = (e: unknown): void => { toast(messageOf(e), 'error'); };
const ui = (action: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action } })); };

async function toggleFlat(): Promise<void> {
  const c = view3d();
  if (c && !c.on) await c.enter();
  await sheetStore.toggle();
}

function add(id: string, label: string, run: () => void, enabled: () => boolean): void {
  if (commands.get(id)) return;
  commands.add({ id, label, group: 'Sheet Metal', run, enabled });
}

function registerCommands(): void {
  add('sm-flat', 'Flat Pattern', () => { void toggleFlat(); }, isSheet);
  add('sm-flat-export', 'Export Flat Pattern...', () => { exporter?.showFor(); }, isSheet);
  add('sm-rule', 'Sheet Metal Rule...', () => { void rule?.showFor().catch(failed); }, isSheet);
  add('sm-tables', 'Bend Tables...', () => { void tables?.showFor().catch(failed); }, hasDoc);
  add('sm-cutlist', 'Cut List', () => { ui('panel:reveal:sm-cutlist'); sheetStore.refresh(0); }, isSheet);
}

function attach(vp: Viewport3D): void {
  if (layer) return;
  layer = new FlatLayer(vp);
  vp.addLayer(layer);
  paint();
}

function paint(): void {
  const c = view3d();
  const vp = c?.vp;
  if (!layer || !vp) return;
  const on = sheetStore.on && !!sheetStore.flat;
  layer.set(sheetStore.flat, on);
  vp.setBodiesHidden(on);
  if (on !== lastOn) {
    lastOn = on;
    if (on) {
      saved = vp.getCamera();
      vp.lookFrom([0, 0, 1], false);
      vp.fitLayers();
    } else if (saved) {
      vp.fitLayers();
      vp.setCamera(saved, true);
      saved = null;
    }
  }
}

function buildToolbar(host: HTMLElement): void {
  const bar = host.querySelector<HTMLElement>('.pt-tools3d');
  if (!bar) return;
  const defs: Array<[string, string, string]> = [['sm-flat', 'smFlat', 'Flat Pattern'], ['sm-rule', 'smRule', 'Sheet Metal Rule'], ['sm-cutlist', 'smCutList', 'Cut List']];
  bar.append(el('<span class="v3-sep"></span>'));
  const nodes: HTMLButtonElement[] = [];
  for (const [cmd, ic, label] of defs) {
    const b = el<HTMLButtonElement>(`<button class="v3-btn sm-v3" type="button" data-cmd="${cmd}">${icon(ic, 16)}</button>`);
    b.dataset.label = label;
    bar.appendChild(b);
    nodes.push(b);
  }
  const words = (): void => { for (const b of nodes) setTitle(b, t(b.dataset.label ?? '')); };
  const state = (): void => {
    for (const b of nodes) {
      setDisabled(b, !(commands.get(b.dataset.cmd ?? '')?.enabled?.() ?? true));
      if (b.dataset.cmd === 'sm-flat') {
        setClass(b, 'is-on', sheetStore.on);
        b.setAttribute('aria-pressed', sheetStore.on ? 'true' : 'false');
      }
    }
  };
  words();
  state();
  onLanguage(words);
  sheetStore.onChange(state);
  docStore.onChange(state);
}

registerDockPanel(cutListPanel({
  toggle: () => { void toggleFlat(); },
  exportDxf: () => { exporter?.showFor(); },
  rule: () => { void rule?.showFor().catch(failed); },
  tables: () => { void tables?.showFor().catch(failed); },
}));

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });

onShellMounted((ctx) => {
  rule = new RuleDialog();
  tables = new TableDialog();
  exporter = new FlatExportDialog();
  registerCommands();
  sheetStore.onChange(paint);
  onView3d((c) => {
    if (c.vp) attach(c.vp);
    const host = q(ctx.hosts.stage, '.cv-view3d');
    buildToolbar(host);
    paint();
  });
});

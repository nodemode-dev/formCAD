import { onShellMounted } from '../../app';
import { drawingCanvas } from '../../canvas/mount';
import { onRefusal } from '../../canvas/interact/constraint-layer';
import { Refusal, type Explanation } from '../../io/api-param';
import type { CommandLineState } from '../../io/api';
import { registerInterceptor } from '../dialogs/intercept';
import { docStore } from '../doc-store';
import { ConflictExplainer } from './explainer';
import { ParametersManager } from './parameters-manager';
import { ConstraintChip } from './status-chip';

let explainer: ConflictExplainer | null = null;
let manager: ParametersManager | null = null;
let shown = '';

const explain = (e: Refusal): void => {
  if (e.explanation) (explainer ??= new ConflictExplainer()).explain(e.explanation, e.message);
};

function refused(doc: string, state: CommandLineState): void {
  const res = (state as CommandLineState & { result?: { refused?: boolean; explanation?: Explanation } }).result;
  if (!res?.refused || !res.explanation) return;
  const key = `${doc}:${state.rev}:${res.explanation.new}:${res.explanation.constraints.length}`;
  if (key === shown) return;
  shown = key;
  (explainer ??= new ConflictExplainer()).explain(res.explanation, res.explanation.message);
}

registerInterceptor(['parameters', 'par', 'parametersmanager'], () => {
  if (!docStore.activeId) return false;
  void (manager ??= new ParametersManager(explain)).showFor();
  return true;
});
registerInterceptor(['parametersclose'], () => { manager?.close(); return true; });

onRefusal(explain);

onShellMounted((ctx) => {
  explainer ??= new ConflictExplainer();
  manager ??= new ParametersManager(explain);
  for (const name of ['formcad:command-state', 'formcad:cmdline-applied']) {
    document.addEventListener(name, (e) => {
      const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
      if (d?.state) refused(d.doc, d.state);
    });
  }
  const canvas = drawingCanvas();
  if (canvas) new ConstraintChip(ctx.hosts.status, canvas, () => { void manager?.showFor(); });
});

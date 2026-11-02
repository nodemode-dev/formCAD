import { api } from '../../io/api';
import { events } from '../../io/events';
import { fetchTolerance } from '../../view3d/nurbs-api';
import { docStore } from '../doc-store';
import { el, q, setText, setValue } from '../dom';
import { t } from '../i18n';
import { toast } from '../toast';
import { selection } from './selection-bus';

const show = (v: number): string => (v === 0 ? '0' : v < 1e-3 || v >= 1e4 ? v.toExponential(2) : String(Number(v.toPrecision(4))));

function field(label: string, tip: string): { root: HTMLElement; input: HTMLInputElement } {
  const root = el('<label class="cv-field u7-tol"><span></span><input class="cv-input" type="number" step="any" min="0"></label>');
  setText(q(root, 'span'), t(label));
  const input = q<HTMLInputElement>(root, 'input');
  input.title = t(tip);
  input.setAttribute('aria-label', t(label));
  return { root, input };
}

export function modelToleranceRows(): HTMLElement[] {
  const abs = field('Model tolerance', 'Largest gap, in drawing units, that surface, boolean and edge operations may leave or close');
  const ang = field('Model angle', 'Largest tangent angle, in radians, that counts as tangent continuous');
  let busy = false;
  let timer = 0;
  const load = async (): Promise<void> => {
    const id = docStore.activeId;
    if (!id) { setValue(abs.input, ''); setValue(ang.input, ''); return; }
    try {
      const v = await fetchTolerance(id);
      if (docStore.activeId !== id) return;
      setValue(abs.input, show(v.absolute_units));
      setValue(ang.input, show(v.angular));
      abs.input.title = `${t('Absolute tolerance')}: ${show(v.absolute_mm)} mm (${v.absolute_source})`;
      ang.input.title = `${t('Angular tolerance')}: ${show(v.angular)} rad (${v.angular_source})`;
    } catch {
      return;
    }
  };
  const later = (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { void load(); }, 150);
  };
  const apply = async (arg: Record<string, number>): Promise<void> => {
    const id = docStore.activeId;
    if (!id || busy) return;
    if (selection.commandActive) { toast(t('Finish the running command first.'), 'error'); void load(); return; }
    busy = true;
    try {
      const state = await api.runCommand(id, 'modeltol', arg);
      document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state } }));
      if (state.error) toast(state.error, 'error');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'The tolerance was not changed', 'error');
    } finally {
      busy = false;
      await load();
    }
  };
  const commit = (input: HTMLInputElement, key: string): void => {
    input.addEventListener('change', () => {
      const v = input.valueAsNumber;
      if (!Number.isFinite(v) || v <= 0) { void load(); return; }
      void apply({ [key]: v });
    });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  };
  commit(abs.input, 'absolute');
  commit(ang.input, 'angular');
  let last = docStore.activeId;
  docStore.onChange(() => { if (docStore.activeId !== last) { last = docStore.activeId; later(); } });
  events.on('doc', (e) => { if (e.id === docStore.activeId) later(); });
  later();
  return [abs.root, ang.root];
}

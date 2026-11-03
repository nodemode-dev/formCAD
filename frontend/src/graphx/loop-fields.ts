import { el, q, setClass, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import type { NodeWidget, NodeWidgetContext } from '../graph';
import { firstOf, scalar, stopAll } from './wutil';

const MAX_PASSES = 100000;

function field(label: string, control: string): HTMLElement {
  return el(`<label class="gp-lrow"><span class="gp-llabel">${label}</span>${control}</label>`);
}

export function loopFieldsWidget(end: boolean) {
  return (ctx: NodeWidgetContext): NodeWidget => {
    const root = el('<div class="gp-loop"></div>');
    ctx.host.appendChild(root);
    stopAll(root);
    const scopeRow = field(t('Scope'), '<input class="gp-linput" type="text" spellcheck="false" autocomplete="off" aria-label="Loop scope" placeholder="">');
    root.appendChild(scopeRow);
    const scope = q<HTMLInputElement>(scopeRow, 'input');
    scope.placeholder = t('Unscoped');
    let maxIn: HTMLInputElement | null = null;
    let collect: HTMLButtonElement | null = null;
    let collectOn = false;
    if (end) {
      const maxRow = field(t('Max passes'), '<input class="gp-linput" type="text" inputmode="numeric" autocomplete="off" aria-label="Maximum passes">');
      const colRow = el('<div class="gp-lrow"><span class="gp-llabel"></span><button class="gp-lcheck" type="button" role="switch" aria-checked="false" aria-label="Collect every pass"></button></div>');
      setText(q(colRow, '.gp-llabel'), t('Collect'));
      root.append(maxRow, colRow);
      maxIn = q<HTMLInputElement>(maxRow, 'input');
      maxIn.placeholder = '100';
      collect = q<HTMLButtonElement>(colRow, 'button');
      maxIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') maxIn?.blur(); });
      maxIn.addEventListener('blur', () => {
        const n = Math.round(Number(maxIn?.value));
        const cur = Number(firstOf(ctx.node().inputs.find((p) => p.name === 'max_iterations')?.persistent));
        if (!Number.isFinite(n) || n < 1) { if (maxIn) maxIn.value = Number.isFinite(cur) ? String(cur) : ''; return; }
        const next = Math.min(n, MAX_PASSES);
        if (maxIn) maxIn.value = String(next);
        if (next !== cur) ctx.edit({ persistent: { port: 'max_iterations', tree: scalar('integer', next) } });
      });
      collect.addEventListener('click', () => {
        collectOn = !collectOn;
        setClass(collect, 'is-on', collectOn);
        collect?.setAttribute('aria-checked', String(collectOn));
        ctx.edit({ settings: { collect: collectOn } });
      });
    }
    const commit = (): void => {
      const now = scope.value.trim();
      if (now !== String(ctx.settings().scope ?? '')) ctx.edit({ settings: { scope: now } });
    };
    scope.addEventListener('keydown', (e) => { if (e.key === 'Enter') scope.blur(); });
    scope.addEventListener('blur', commit);
    return {
      size: { w: 188, h: end ? 84 : 26 },
      update(node) {
        const s = String(node.settings.scope ?? '');
        if (document.activeElement !== scope && scope.value !== s) scope.value = s;
        if (maxIn && collect) {
          const v = firstOf(node.inputs.find((p) => p.name === 'max_iterations')?.persistent);
          const text = typeof v === 'number' ? String(v) : '';
          if (document.activeElement !== maxIn && maxIn.value !== text) maxIn.value = text;
          collectOn = node.settings.collect === true;
          setClass(collect, 'is-on', collectOn);
          collect.setAttribute('aria-checked', String(collectOn));
        }
      },
    };
  };
}

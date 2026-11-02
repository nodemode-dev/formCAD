import { onShellMounted } from '../app';
import { registerDockPanel } from './dock';
import { docStore } from './doc-store';
import { el, setClass, setTitle } from './dom';
import { icon } from './icons';
import { onLanguage, t } from './i18n';
import { ArrayBar } from './panels/array-bar';
import { FindDialog } from './panels/find-dialog';
import { propertiesPanel } from './panels/properties-panel';
import { flipQuickProps, QuickProperties, quickPropsOn } from './panels/quick-props';
import { QuickSelectDialog } from './panels/quick-select-dialog';
import { quickCalcPanel } from './panels/quickcalc-panel';
import { selection } from './panels/selection-bus';
import { sysvars } from './sysvar-store';

const ui = (action: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action } })); };

onShellMounted((ctx) => {
  const { hosts, commands } = ctx;
  const find = new FindDialog();
  const quickSelect = new QuickSelectDialog();
  const quick = new QuickProperties(hosts.stage, hosts.canvasHost);
  new ArrayBar(hosts.options);

  const hasDoc = (): boolean => !!docStore.activeId;
  const add = (cmd: Parameters<typeof commands.add>[0]): void => { if (!commands.get(cmd.id)) commands.add(cmd); };

  const existing = commands.get('win-properties');
  if (existing) {
    existing.run = () => ui('panel:toggle:properties');
  }
  add({ id: 'open-properties', label: 'Properties', icon: 'properties', group: 'Modify', run: () => ui('panel:reveal:properties') });
  add({
    id: 'win-quickcalc',
    label: 'QuickCalc',
    keys: ['Mod+8'],
    icon: 'calculator',
    group: 'Window',
    run: () => {
      ui('panel:toggle:quickcalc');
      requestAnimationFrame(() => document.dispatchEvent(new CustomEvent('formcad:quickcalc-focus')));
    },
  });
  add({ id: 'open-find', label: 'Find...', icon: 'search', group: 'Edit', enabled: hasDoc, run: () => find.show() });
  add({ id: 'open-quick-select', label: 'Quick Select...', icon: 'quickSelect', group: 'Edit', enabled: hasDoc, run: () => { void quickSelect.show(); } });
  add({ id: 'deselect-all', label: 'Deselect All', group: 'Edit', enabled: () => hasDoc() && selection.handles.length > 0, run: () => selection.select([]) });
  add({
    id: 'toggle-quickprops',
    label: 'Quick Properties',
    icon: 'quickProps',
    group: 'Window',
    enabled: () => sysvars.ready,
    checked: quickPropsOn,
    run: () => { void sysvars.set('QPMODE', flipQuickProps()); },
  });

  registerDockPanel(propertiesPanel());
  registerDockPanel(quickCalcPanel());

  const togs = hosts.status.querySelector('.cv-st-togs');
  if (togs) {
    const btn = el<HTMLButtonElement>(`<button class="cv-st-tog" type="button" data-cmd="toggle-quickprops" aria-pressed="false">${icon('quickProps', 14)}</button>`);
    togs.appendChild(btn);
    const label = (): void => {
      const text = t('Quick Properties');
      setTitle(btn, text);
      btn.setAttribute('aria-label', text);
    };
    const sync = (): void => {
      const on = sysvars.ready && quickPropsOn();
      setClass(btn, 'is-on', on);
      if (btn.getAttribute('aria-pressed') !== String(on)) btn.setAttribute('aria-pressed', String(on));
      if (btn.disabled !== !sysvars.ready) btn.disabled = !sysvars.ready;
    };
    label();
    sync();
    sysvars.onChange(sync);
    onLanguage(label);
  }
  quick.paint();
});

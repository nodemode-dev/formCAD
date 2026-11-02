import { api, type CommandLineState, type CommandMeta } from '../io/api';
import { events } from '../io/events';
import { onCapabilities, onShellMounted, type AppContext } from '../app';
import { BAR_H, CommandLine, LINE_H } from './command-line';
import { CommandPalette } from './command-palette';
import type { Command } from './commands';
import { Dock, registerDockPanel } from './dock';
import { docStore } from './doc-store';
import { setClass, setStyleVar } from './dom';
import { docInfoPanel } from './panels/doc-info';
import { sysvarPanel } from './panels/sysvar-panel';
import { applyLookPrefs, loadPrefs, updatePrefs, type Prefs } from './prefs';
import { PREF_SECTIONS, SettingsDialog } from './settings-dialog';
import { sysvars } from './sysvar-store';
import { readChoice, setTheme } from './themes';

const activeDoc = (): string | null => docStore.activeId;

const onActiveDoc = (fn: () => void): (() => void) => {
  let last = docStore.activeId;
  return docStore.onChange(() => {
    if (docStore.activeId === last) return;
    last = docStore.activeId;
    fn();
  });
};

function followSystemTheme(p: Prefs): void {
  if (p.themeMode !== 'system' || typeof matchMedia !== 'function') return;
  const id = matchMedia('(prefers-color-scheme: dark)').matches ? p.themeDark : p.themeLight;
  if (readChoice().theme !== id) setTheme(id);
}

function mount(ctx: AppContext): void {
  const { hosts, commands } = ctx;
  const root = document.documentElement;
  let engine: CommandMeta[] = [];

  const loadEngine = async (): Promise<void> => {
    try {
      engine = (await api.commands()).commands;
    } catch {
      return;
    }
  };

  const dock = new Dock(hosts.dock, {
    width: () => loadPrefs().dockWidth,
    preview: (px) => setStyleVar(root, '--cv-panel-w', `${px}px`),
    commit: (px) => { updatePrefs({ dockWidth: px }); },
  });
  registerDockPanel(docInfoPanel({ current: () => docStore.current(), onDocs: (fn) => docStore.onChange(fn), num: (n, d) => sysvars.num(n, d), onVars: (fn) => sysvars.onChange(fn) }));
  registerDockPanel(sysvarPanel({ activeDoc, onDoc: onActiveDoc }));

  const line = new CommandLine(hosts.cmdline, {
    activeDoc,
    onActiveDoc,
    engineCommands: () => engine,
    stage: hosts.stage,
    lines: () => loadPrefs().historyLines,
    setLines: (n) => { updatePrefs({ historyLines: n }); },
  });

  const settings = new SettingsDialog({ commands, capabilities: () => ctx.capabilities });
  const palette = new CommandPalette({
    commands,
    engineCommands: () => engine,
    refreshEngine: () => { void loadEngine(); },
    runEngine: (name) => { void line.run(name); },
  });

  const layout = (p: Prefs): void => {
    setClass(hosts.root, 'is-dock-hidden', !p.showDock);
    setClass(hosts.root, 'is-cmd-hidden', !p.showCommandLine);
    setStyleVar(root, '--cv-panel-w', `${p.dockWidth}px`);
    setStyleVar(root, '--cv-cmdline-h', `${BAR_H + p.historyLines * LINE_H}px`);
  };

  const apply = (): void => {
    const p = loadPrefs();
    applyLookPrefs(p);
    followSystemTheme(p);
    layout(p);
    line.refit();
  };

  document.addEventListener('formcad:command-state', (e) => {
    const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
    line.accept(d.doc, d.state);
  });
  document.addEventListener('formcad:ui', (e) => {
    const action = (e as CustomEvent<{ action: string }>).detail.action;
    if (action === 'palette:properties') dock.reveal('doc-info');
    else if (action === 'reset-palettes' || action === 'reset-layout') dock.resetLayout();
    else if (action === 'command-history') line.toggleHistory();
  });

  layout(loadPrefs());
  followSystemTheme(loadPrefs());
  document.addEventListener('formcad:prefs-changed', apply);
  if (typeof matchMedia === 'function') matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => followSystemTheme(loadPrefs()));

  const add = (cmd: Command): void => {
    if (!commands.get(cmd.id)) commands.add(cmd);
  };

  add({
    id: 'settings',
    label: 'Preferences...',
    keys: ['Mod+,'],
    icon: 'settings',
    group: 'Preferences',
    run: (params) => settings.show(typeof params?.section === 'string' ? params.section : undefined),
  });
  for (const [id, label, section] of PREF_SECTIONS) {
    add({ id: `prefs-${id}`, label: `${label} Preferences`, icon: 'settings', group: 'Preferences', run: () => settings.show(section) });
  }
  add({
    id: 'command-palette',
    label: 'Search Commands...',
    keys: ['Shift+Mod+P', 'Mod+K'],
    icon: 'search',
    group: 'Window',
    run: () => palette.show(),
  });
  add({
    id: 'focus-command-line',
    label: 'Focus Command Line',
    icon: 'cmdline',
    group: 'Window',
    run: () => {
      if (!loadPrefs().showCommandLine) updatePrefs({ showCommandLine: true });
      requestAnimationFrame(() => line.focus());
    },
  });
  add({
    id: 'toggle-command-line',
    label: 'Command Line',
    keys: ['Mod+9'],
    icon: 'cmdline',
    group: 'Window',
    checked: () => loadPrefs().showCommandLine,
    run: () => {
      const on = !loadPrefs().showCommandLine;
      updatePrefs({ showCommandLine: on });
      if (on) requestAnimationFrame(() => line.focus());
    },
  });
  add({
    id: 'command-history',
    label: 'Command History',
    keys: ['F2'],
    icon: 'history',
    group: 'Window',
    run: () => {
      if (!loadPrefs().showCommandLine) updatePrefs({ showCommandLine: true });
      line.toggleHistory();
    },
  });
  add({
    id: 'toggle-dock',
    label: 'Side Dock',
    keys: ['Shift+Mod+D'],
    icon: 'dock',
    group: 'Window',
    checked: () => loadPrefs().showDock,
    run: () => { updatePrefs({ showDock: !loadPrefs().showDock }); },
  });
  add({
    id: 'dock-reset',
    label: 'Reset Panels',
    icon: 'dock',
    group: 'Window',
    run: () => {
      dock.resetLayout();
      updatePrefs({ showDock: true });
    },
  });
  for (const [id, label] of [['doc-info', 'Document Info'], ['sysvars', 'System Variables']] as const) {
    add({
      id: `panel-${id}`,
      label,
      icon: id === 'doc-info' ? 'info' : 'sliders',
      group: 'Window',
      run: () => {
        if (!loadPrefs().showDock) updatePrefs({ showDock: true });
        dock.reveal(id);
      },
    });
  }

  onCapabilities((caps) => { if (caps) void loadEngine(); });
  events.onState((s) => { if (s === 'open') void loadEngine(); });
}

onShellMounted(mount);

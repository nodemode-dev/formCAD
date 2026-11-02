import { onCapabilities, onShellMounted, type AppContext } from '../app';
import { api, ApiError, type Capabilities, type CommandLineState } from '../io/api';
import { CaptionButtons, CUSTOM_TITLE_BAR_KEY, wantsCustomTitleBar } from './caption-buttons';
import { commands, type Command } from './commands';
import { docStore } from './doc-store';
import { watchExitRequests } from './exit-guard';
import { isMac, setClass, stored, store } from './dom';
import { onOpenPaths } from './file-dialogs';
import { HomeScreen, DropOverlay } from './home';
import { showAbout, showCommandReference } from './info-dialogs';
import { MenuBar, PopupMenu } from './menu';
import { buildMenus, ENGINE_COMMANDS, RECENT_SLOTS, registerEngineCatalogue } from './menu-spec';
import { MENUS_IN_WINDOW_KEY, menusInWindow, NativeMenus, textFieldFocused, wantsNativeMenus } from './native-menu';
import { loadPrefs, updatePrefs } from './prefs';
import { StatusBar } from './status';
import { DRAFT_TOGGLES, sysvars } from './sysvar-store';
import { JobTracker } from './jobs-list';
import { Tabs } from './tabs';
import { readChoice, setTheme, THEMES } from './themes';
import { toast } from './toast';
import { TitleTools, WORKSPACE_LOCK_KEY, WORKSPACES } from './titlebar-tools';
import { onLanguage } from './i18n';

const VIEW_KEY = 'formCAD.view';
const VIEW_FLAGS = ['tabs', 'status', 'options', 'rail', 'menubar'] as const;
type ViewFlag = (typeof VIEW_FLAGS)[number];

const NO_DOC = new Set(['newfromtemplate', 'import', 'opensample', 'checkupdates', 'appload', 'mouse3d', 'plottermanager', 'stylesmanager', 'aliasedit', 'recover', 'drawingrecovery', 'publish', 'sheetbooks']);

let caps: Capabilities | null = null;
let status: StatusBar | null = null;
let home: HomeScreen | null = null;
let tools: TitleTools | null = null;
let captions: CaptionButtons | null = null;
let root: HTMLElement | null = null;

const jobs = new JobTracker();
const hasDoc = (): boolean => !!docStore.current();
const ui = (action: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action } })); };

function addOnce(cmd: Command): void {
  if (!commands.get(cmd.id)) commands.add(cmd);
}

function viewFlags(): Record<ViewFlag, boolean> {
  const out = { tabs: false, status: false, options: false, rail: false, menubar: false };
  try {
    const v: unknown = JSON.parse(stored(VIEW_KEY) ?? '{}');
    if (v && typeof v === 'object') for (const k of VIEW_FLAGS) out[k] = (v as Record<string, unknown>)[k] === true;
  } catch {
    return out;
  }
  return out;
}

function applyView(): void {
  if (!root) return;
  const f = viewFlags();
  for (const k of VIEW_FLAGS) setClass(root, `is-${k}-hidden`, f[k]);
}

function flipView(k: ViewFlag): void {
  const f = viewFlags();
  f[k] = !f[k];
  store(VIEW_KEY, JSON.stringify(f));
  applyView();
}

function applyChrome(): void {
  if (!root) return;
  const p = loadPrefs();
  setClass(root, 'is-dock-hidden', !p.showDock);
  setClass(root, 'is-cmd-hidden', !p.showCommandLine);
}

function report(label: string, state: CommandLineState, doc: string): void {
  document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc, state } }));
  const last = state.history[state.history.length - 1] ?? '';
  if (/unknown command/i.test(last)) toast(`${label}: ${last}`, 'error');
}

async function runEngine(label: string, name: string, option?: string): Promise<void> {
  let doc = docStore.current();
  if (!doc) doc = await docStore.create();
  if (!doc) return;
  try {
    report(label, option ? await api.runCommand(doc.id, name, { option }) : await api.sendInput(doc.id, name), doc.id);
  } catch (e) {
    toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer', 'error');
  }
}

async function stepHistory(kind: 'undo' | 'redo'): Promise<void> {
  const doc = docStore.current();
  if (!doc) return;
  try {
    if (kind === 'undo') await api.undo(doc.id); else await api.redo(doc.id);
    void docStore.refresh();
  } catch (e) {
    toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer', 'error');
  }
}

function registerCommands(): void {
  const doc = (): boolean => hasDoc();
  const edit = (): boolean => hasDoc() && !textFieldFocused();
  const recentAt = (i: number) => docStore.recent[i];
  const list: Command[] = [
    { id: 'new', label: 'New Drawing...', keys: ['Mod+N'], icon: 'newFile', group: 'File', run: () => void docStore.create() },
    { id: 'open', label: 'Open...', keys: ['Mod+O'], icon: 'folderOpen', group: 'File', run: () => void docStore.openByPrompt() },
    { id: 'save', label: 'Save', keys: ['Mod+S'], icon: 'save', group: 'File', enabled: doc, run: () => void docStore.save() },
    { id: 'save-as', label: 'Save As...', keys: ['Shift+Mod+S'], icon: 'saveAs', group: 'File', enabled: doc, run: () => void docStore.saveAs() },
    { id: 'save-all', label: 'Save All', group: 'File', enabled: () => docStore.docs.some((d) => d.dirty), run: () => { void (async () => { for (const d of docStore.docs) if (d.dirty) await docStore.save(d.id); })(); } },
    { id: 'close', label: 'Close', keys: ['Mod+W'], group: 'File', enabled: doc, run: () => void docStore.close() },
    { id: 'close-all', label: 'Close All', group: 'File', enabled: doc, run: () => void docStore.closeAll() },
    { id: 'close-others', label: 'Close All Other Drawings', group: 'File', enabled: () => docStore.docs.length > 1, run: () => void docStore.closeAll(docStore.activeId ?? undefined) },
    { id: 'copy-path', label: 'Copy Full File Path', group: 'File', enabled: () => !!docStore.current()?.path, run: () => { void navigator.clipboard?.writeText(docStore.current()?.path ?? '').catch(() => undefined); } },
    { id: 'clear-recent', label: 'Clear Recent Files', group: 'File', enabled: () => docStore.recent.length > 0, run: () => docStore.clearRecent() },
    { id: 'undo', label: 'Undo', keys: ['Mod+Z'], icon: 'undo', group: 'Edit', enabled: edit, run: () => void stepHistory('undo') },
    { id: 'redo', label: 'Redo', keys: ['Shift+Mod+Z', 'Mod+Y'], icon: 'redo', group: 'Edit', enabled: edit, run: () => void stepHistory('redo') },
    { id: 'cut', label: 'Cut', keys: ['Mod+X'], icon: 'cut', group: 'Edit', enabled: edit, run: () => void runEngine('Cut', 'cutclip') },
    { id: 'copy', label: 'Copy', keys: ['Mod+C'], icon: 'duplicate', group: 'Edit', enabled: edit, run: () => void runEngine('Copy', 'copyclip') },
    { id: 'paste', label: 'Paste', keys: ['Mod+V'], icon: 'paste', group: 'Edit', enabled: edit, run: () => void runEngine('Paste', 'pasteclip') },
    { id: 'select-all', label: 'Select All', keys: ['Mod+A'], group: 'Edit', enabled: edit, run: () => void runEngine('Select All', 'selectall') },
    { id: 'language', label: 'Interface Language...', group: 'Edit', run: () => { if (!commands.run('settings', { section: 'language' })) toast('Preferences are not available yet', 'error'); } },
    { id: 'home', label: 'Start', icon: 'home', group: 'Window', run: () => { if (home?.isShown && docStore.docs.length) home.hide(); else home?.show(); } },
    { id: 'help', label: 'Command Reference', keys: ['F1'], icon: 'help', group: 'Help', run: () => showCommandReference(commands) },
    { id: 'about', label: 'About FormCAD', icon: 'info', group: 'Help', run: () => showAbout(caps?.version ?? null) },
    { id: 'jobs', label: 'Jobs', icon: 'viewList', group: 'Window', checked: () => !!status?.jobsOpen, run: () => status?.toggleJobs() },
    { id: 'install-kernel', label: 'Install Kernel...', icon: 'kernel', group: 'Model', enabled: () => !!caps && !caps.kernel.available, run: () => status?.installKernel() },
    { id: 'custom-title-bar', label: 'Custom Title Bar', group: 'View', enabled: wantsCustomTitleBar, checked: () => stored(CUSTOM_TITLE_BAR_KEY) === '1', run: () => { store(CUSTOM_TITLE_BAR_KEY, stored(CUSTOM_TITLE_BAR_KEY) === '1' ? '0' : '1'); captions?.sync(); } },
    { id: 'menus-in-window', label: 'Menus in Window', group: 'View', enabled: () => '__TAURI_INTERNALS__' in window && isMac, checked: menusInWindow, run: () => { const keep = !menusInWindow(); store(MENUS_IN_WINDOW_KEY, keep ? '1' : '0'); toast(keep ? 'The menus stay in the window from the next start.' : 'The menus go to the menu bar from the next start.'); } },
    { id: 'theme-system', label: 'Use System Setting', group: 'View', checked: () => loadPrefs().themeMode === 'system', run: () => { updatePrefs({ themeMode: 'system' }); const p = loadPrefs(); setTheme(matchMedia('(prefers-color-scheme: dark)').matches ? p.themeDark : p.themeLight); } },
    { id: 'theme-light', label: 'Light', group: 'View', checked: () => loadPrefs().themeMode === 'fixed' && !!THEMES[readChoice().theme]?.light, run: () => { const p = updatePrefs({ themeMode: 'fixed' }); setTheme(p.themeLight); } },
    { id: 'theme-dark', label: 'Dark', group: 'View', checked: () => loadPrefs().themeMode === 'fixed' && !THEMES[readChoice().theme]?.light, run: () => { const p = updatePrefs({ themeMode: 'fixed' }); setTheme(p.themeDark); } },
    { id: 'anim-system', label: 'Use System Setting', group: 'View', checked: () => loadPrefs().animations && loadPrefs().reduceMotion === matchMedia('(prefers-reduced-motion: reduce)').matches, run: () => { updatePrefs({ animations: true, reduceMotion: matchMedia('(prefers-reduced-motion: reduce)').matches }); } },
    { id: 'anim-on', label: 'On', group: 'View', checked: () => loadPrefs().animations && !loadPrefs().reduceMotion, run: () => { updatePrefs({ animations: true, reduceMotion: false }); } },
    { id: 'anim-off', label: 'Off', group: 'View', checked: () => !loadPrefs().animations, run: () => { updatePrefs({ animations: false }); } },
    { id: 'win-toolsets', label: 'Tool Sets', keys: ['Mod+3'], group: 'Window', checked: () => !viewFlags().rail, run: () => flipView('rail') },
    { id: 'win-properties', label: 'Properties Inspector', keys: ['Mod+1'], group: 'Window', checked: () => loadPrefs().showDock, run: () => { updatePrefs({ showDock: !loadPrefs().showDock }); applyChrome(); ui('palette:properties'); } },
    { id: 'win-layers', label: 'Layers Palette', group: 'Window', run: () => { updatePrefs({ showDock: true }); applyChrome(); ui('palette:properties'); } },
    { id: 'win-toolbar', label: 'Tool Bar', group: 'Window', checked: () => !viewFlags().options, run: () => flipView('options') },
    { id: 'win-filetabs', label: 'File Tab', group: 'Window', checked: () => !viewFlags().tabs, run: () => flipView('tabs') },
    { id: 'win-statusbar', label: 'Status Bar', group: 'Window', checked: () => !viewFlags().status, run: () => flipView('status') },
    { id: 'win-cmdline', label: 'Command Line', keys: ['Mod+9'], group: 'Window', checked: () => loadPrefs().showCommandLine, run: () => { updatePrefs({ showCommandLine: !loadPrefs().showCommandLine }); applyChrome(); } },
    { id: 'win-cmdhistory', label: 'Command History', keys: ['F2'], group: 'Window', run: () => ui('command-history') },
    { id: 'win-menubar', label: 'In-window Menu Bar', group: 'Window', checked: () => !viewFlags().menubar, run: () => flipView('menubar') },
    { id: 'win-hide-palettes', label: 'Hide Palettes', group: 'Window', run: () => { updatePrefs({ showDock: false }); applyChrome(); } },
    { id: 'win-reset-palettes', label: 'Reset Palettes', group: 'Window', run: () => { store(VIEW_KEY, '{}'); updatePrefs({ showDock: true, showCommandLine: true }); applyView(); applyChrome(); ui('reset-palettes'); } },
    { id: 'win-reset-layout', label: 'Reset Panel Layout', group: 'Window', run: () => { updatePrefs({ showDock: true }); applyChrome(); ui('reset-layout'); } },
  ];
  for (let i = 0; i < RECENT_SLOTS; i++) {
    list.push({ id: `recent-${i}`, label: () => recentAt(i)?.name ?? '', group: 'File', enabled: () => !!recentAt(i), run: () => { const r = recentAt(i); if (r) void docStore.openPath(r.path); } });
  }
  for (const w of WORKSPACES) {
    list.push({ id: `workspace-${w.id}`, label: w.label, group: 'Window', checked: () => tools?.currentId() === w.id, run: () => tools?.choose(w.id) });
  }
  for (const x of DRAFT_TOGGLES) {
    list.push({
      id: x.id, label: x.label, keys: x.keys, icon: x.icon, group: 'Drafting',
      enabled: () => sysvars.ready,
      checked: () => sysvars.ready && x.on(sysvars.num(x.name, x.fallback)),
      run: () => { void sysvars.set(x.name, x.flip(sysvars.num(x.name, x.fallback))); },
    });
  }
  registerEngineCatalogue();
  for (const e of ENGINE_COMMANDS.values()) {
    list.push({
      id: e.id, label: e.label, keys: e.keys, group: e.group,
      enabled: NO_DOC.has(e.name) ? undefined : doc,
      run: () => void runEngine(e.label, e.name, e.option),
    });
  }
  for (const cmd of list) addOnce(cmd);
}

function mount(ctx: AppContext): void {
  const { hosts } = ctx;
  root = hosts.root;
  registerCommands();
  applyView();
  applyChrome();
  document.addEventListener('formcad:prefs-changed', applyChrome);

  const menus = buildMenus(() => docStore.recent.length);
  new MenuBar(hosts.menubar, commands, menus);
  if (wantsNativeMenus()) {
    const native = new NativeMenus(commands, () => menus);
    void native.build().catch(() => undefined);
    let sig = '';
    docStore.onChange(() => {
      native.refresh();
      const now = docStore.recent.map((r) => r.path).join('|');
      if (now !== sig) { sig = now; void native.build().catch(() => undefined); }
    });
    onLanguage(() => { void native.build().catch(() => undefined); });
  }

  tools = new TitleTools(hosts.titlebar, {
    commands,
    arrange: (w) => { hosts.root.dataset.workspace = w.id; },
    locked: () => stored(WORKSPACE_LOCK_KEY) === '1',
    setLocked: (on) => {
      store(WORKSPACE_LOCK_KEY, on ? '1' : '0');
      setClass(hosts.root, 'is-workspace-locked', on);
    },
  });
  hosts.root.dataset.workspace = tools.currentId();
  setClass(hosts.root, 'is-workspace-locked', stored(WORKSPACE_LOCK_KEY) === '1');
  captions = new CaptionButtons(hosts.titlebar, () => stored(CUSTOM_TITLE_BAR_KEY) === '1');

  const tabMenu = new PopupMenu(commands, null, true);
  tabMenu.setItems(['new', 'open', '-', 'save', 'save-as', 'save-all', '-', 'close', 'close-others', '-', 'copy-path']);
  const tabs = new Tabs(hosts.tabStrip, {
    docs: docStore,
    close: (id) => void docStore.close(id),
    menu: (_id, x, y) => tabMenu.openAt(x, y),
    docTitle: hosts.titleDoc,
  });

  home = new HomeScreen(hosts.stage, {
    docs: docStore,
    autoShow: () => loadPrefs().autoShowHome,
    afterClose: () => loadPrefs().homeOnLastClose,
    newFromTemplate: (template) => void docStore.create(template),
    openPath: (path) => void docStore.openPath(path),
  });
  home.onVisibility((shown) => tabs.setHome(shown));
  tabs.setHome(home.isShown);
  new DropOverlay(hosts.stage, (path) => void docStore.openPath(path));

  status = new StatusBar(hosts.status, { commands, sysvars, docs: docStore, jobs });
  docStore.onChange(() => status?.syncToggles());
}

onShellMounted(mount);

onCapabilities((c) => {
  caps = c;
  status?.setCapabilities(c);
  if (c) {
    void docStore.refresh();
    void docStore.refreshRecent();
    void sysvars.load();
    void watchExitRequests().then(() => onOpenPaths((paths) => { void (async () => { for (const p of paths) await docStore.openPath(p); })(); }));
  }
});

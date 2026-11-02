import { api, type Capabilities } from './io/api';
import { events } from './io/events';
import { comboOf, commands, type Commands } from './ui/commands';
import { mountOnce, q, revealApp } from './ui/dom';
import { enhanceAllSelects } from './ui/dropdown';
import { icon } from './ui/icons';
import { installNumberFields } from './ui/number-fields';
import { anyDialogOpen } from './ui/dialogs';
import { applyLookPrefs, loadPrefs } from './ui/prefs';
import { applyTheme } from './ui/themes';

const SHELL = `<div class="cv-app">
<header class="cv-titlebar">
<nav class="cv-menubar" aria-label="Main menu"></nav>
<div class="cv-tb-doc"></div>
<div class="cv-tb-app">FormCAD 2026</div>
<div class="cv-zoom">
<button class="cv-tt-btn" type="button" data-cmd="settings" title="Preferences" aria-label="Preferences">${icon('settings', 16)}</button>
</div>
</header>
<div class="cv-main">
<div class="cv-doc-tabs">
<button class="cv-brand" type="button" data-cmd="home" title="Home" aria-label="Home">${icon('home', 18)}</button>
<div class="cv-tabs"><div class="cv-tab-strip" role="tablist"></div><button class="cv-icon-btn" type="button" data-cmd="new" title="New" aria-label="New">${icon('add', 16)}</button></div>
</div>
<div class="cv-options" aria-label="Tool options"></div>
<aside class="cv-rail" aria-label="Tools"></aside>
<main class="cv-stage"><div class="cv-canvas-host" aria-label="Drawing area"></div></main>
<section class="cv-dock" aria-label="Panels"></section>
<section class="cv-cmdline" aria-label="Command line"></section>
</div>
<footer class="cv-status"></footer>
</div>`;

export interface ShellHosts {
  root: HTMLElement;
  titlebar: HTMLElement;
  menubar: HTMLElement;
  titleDoc: HTMLElement;
  titleApp: HTMLElement;
  titleTools: HTMLElement;
  main: HTMLElement;
  docTabs: HTMLElement;
  brand: HTMLButtonElement;
  tabStrip: HTMLElement;
  newDocButton: HTMLButtonElement;
  options: HTMLElement;
  rail: HTMLElement;
  stage: HTMLElement;
  canvasHost: HTMLElement;
  dock: HTMLElement;
  cmdline: HTMLElement;
  status: HTMLElement;
}

export interface AppContext {
  hosts: ShellHosts;
  commands: Commands;
  capabilities: Capabilities | null;
}

export function mountShell(appHost: HTMLElement): ShellHosts {
  mountOnce(appHost, SHELL);
  const root = q(appHost, '.cv-app');
  return {
    root,
    titlebar: q(root, '.cv-titlebar'),
    menubar: q(root, '.cv-menubar'),
    titleDoc: q(root, '.cv-tb-doc'),
    titleApp: q(root, '.cv-tb-app'),
    titleTools: q(root, '.cv-zoom'),
    main: q(root, '.cv-main'),
    docTabs: q(root, '.cv-doc-tabs'),
    brand: q<HTMLButtonElement>(root, '.cv-brand'),
    tabStrip: q(root, '.cv-tab-strip'),
    newDocButton: q<HTMLButtonElement>(root, '.cv-tabs > .cv-icon-btn'),
    options: q(root, '.cv-options'),
    rail: q(root, '.cv-rail'),
    stage: q(root, '.cv-stage'),
    canvasHost: q(root, '.cv-canvas-host'),
    dock: q(root, '.cv-dock'),
    cmdline: q(root, '.cv-cmdline'),
    status: q(root, '.cv-status'),
  };
}

let context: AppContext | null = null;
const mountHooks: Array<(ctx: AppContext) => void> = [];
const engineHooks: Array<(caps: Capabilities | null) => void> = [];

export const appContext = (): AppContext | null => context;

export function onShellMounted(fn: (ctx: AppContext) => void): void {
  if (context) fn(context);
  else mountHooks.push(fn);
}

export function onCapabilities(fn: (caps: Capabilities | null) => void): void {
  engineHooks.push(fn);
  if (context) fn(context.capabilities);
}

function bootLook(): void {
  applyTheme();
  applyLookPrefs(loadPrefs());
  installNumberFields();
  enhanceAllSelects();
}

function bindCommandButtons(root: HTMLElement): void {
  root.addEventListener('click', (e) => {
    const target = e.target instanceof Element ? e.target.closest<HTMLElement>('[data-cmd]') : null;
    if (target?.dataset.cmd) commands.run(target.dataset.cmd);
  });
}

function bindShortcuts(): void {
  window.addEventListener('keydown', (e) => {
    if (anyDialogOpen() || e.defaultPrevented) return;
    const t = e.target;
    const typing = t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    const combo = comboOf(e);
    const cmd = commands.forCombo(combo);
    if (!cmd || (typing && !combo.includes('Mod+'))) return;
    if (commands.run(cmd.id)) e.preventDefault();
  });
}

async function connectEngine(ctx: AppContext): Promise<void> {
  try {
    ctx.capabilities = await api.capabilities();
  } catch {
    ctx.capabilities = null;
  }
  for (const fn of engineHooks) fn(ctx.capabilities);
  events.connect();
}

function reveal(): void {
  const fonts = (document as Document & { fonts?: { ready: Promise<unknown> } }).fonts;
  const settled = fonts ? Promise.race([fonts.ready, new Promise((r) => setTimeout(r, 2500))]) : Promise.resolve();
  void settled.then(revealApp);
}

export function startApp(): void {
  const appHost = document.getElementById('app');
  if (!appHost) return;
  bootLook();
  const hosts = mountShell(appHost);
  commands.applyOverrides(loadPrefs().shortcuts);
  context = { hosts, commands, capabilities: null };
  bindCommandButtons(hosts.root);
  bindShortcuts();
  for (const fn of mountHooks.splice(0)) fn(context);
  void connectEngine(context);
  reveal();
}

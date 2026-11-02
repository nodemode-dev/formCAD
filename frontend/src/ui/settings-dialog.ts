import { api, type Capabilities, type KernelStatus } from '../io/api';
import { events } from '../io/events';
import { toolList } from '../extensions/registry';
import type { Commands } from './commands';
import { confirmAction, Dialog } from './dialogs';
import { el, patchList, q, setClass, setHidden, setText, setValue, store, stored } from './dom';
import { icon } from './icons';
import { isLang, languages, onLanguage, setLanguage, t } from './i18n';
import { checkRow, colorRow, numberRow, selectRow, sliderRow, toggleRow, type Row } from './panels/controls';
import { aciRow, buttonRow, colorDefaultRow, enable, infoRow, pathRow, radioRow, textRow } from './panels/pref-rows';
import {
  ANGLE_UNITS, ANIMATION_MODES, DEFAULT_PREFS, DRAW_UNITS, SAVE_VERSIONS, loadPrefs, updatePrefs, type Prefs,
} from './prefs';
import { dwgRows } from './output/dwg-prefs';
import { sysvars } from './sysvar-store';
import { DEFAULT_ACCENT, DEFAULT_THEME, STORAGE_KEY, THEMES, readChoice, setAccent, setIntensity, setTheme, themeSwatchesHtml } from './themes';
import { toast } from './toast';

export interface SettingsDeps {
  commands: Commands;
  capabilities: () => Capabilities | null;
}

export const PREF_SECTIONS: ReadonlyArray<readonly [string, string, string]> = [
  ['general', 'General', 'General'],
  ['interface', 'Interface', 'Interface'],
  ['workspace', 'Workspace', 'Workspace'],
  ['display', 'Display', 'Display'],
  ['drafting', 'Drafting', 'Drafting'],
  ['selection', 'Selection', 'Selection'],
  ['snaps', 'Snaps and Tracking', 'Snaps and Tracking'],
  ['units', 'Units and Precision', 'Units and Precision'],
  ['files', 'Open and Save', 'Open and Save'],
  ['plot', 'Plot and Publish', 'Plot and Publish'],
  ['user', 'User Preferences', 'User Preferences'],
  ['profiles', 'Profiles', 'Profiles'],
  ['modeling', 'Modeling', 'Modeling'],
  ['graph', 'Graph', 'Graph'],
  ['performance', 'Performance', 'Performance'],
  ['plugins', 'Plugins', 'Plugins'],
  ['agents', 'Agents', 'Agents'],
];

const RAIL_ICONS: Record<string, string> = {
  'General': 'pfGeneral', 'Interface': 'pfInterface', 'Workspace': 'pfWorkspace', 'Display': 'pfDisplay', 'Drafting': 'pfDrafting',
  'Selection': 'pfSelection', 'Snaps and Tracking': 'pfSnaps', 'Units and Precision': 'pfUnits', 'Open and Save': 'pfFile',
  'Plot and Publish': 'pfPlot', 'User Preferences': 'pfLanguage', 'Profiles': 'pfHistory', 'Modeling': 'pfModeling', 'Graph': 'pfGraph',
  'Performance': 'pfPerformance', 'Plugins': 'pfPlugins', 'Agents': 'pfAgents',
};

type VarValue = number | string | number[];

const DEFAULTS: Record<string, VarValue> = {
  OSMODE: 4133, OSNAPHATCH: 0, ORTHOMODE: 0, POLARMODE: 0, POLARANG: 90, POLARADDANG: '', POLARDIST: 0, SNAPTYPE: 0, AUTOSNAP: 61,
  GRIDMODE: 1, SNAPMODE: 0, SNAPSTYL: 0, SNAPUNIT: [0.5, 0.5], GRIDUNIT: [0.5, 0.5], GRIDMAJOR: 5,
  DYNMODE: 1, DYNPROMPT: 1, DYNPIFORMAT: 0, DYNPICOORDS: 0,
  PICKBOX: 3, APERTURE: 10, PICKFIRST: 1, PICKADD: 1, PICKDRAG: 2, PICKSTYLE: 1, SELECTIONPREVIEW: 3, PREVIEWFILTER: 3,
  GRIPS: 1, GRIPOBJLIMIT: 100, GRIPSIZE: 5, SELECTIONAREA: 1, WINDOWAREACOLOR: 150, CROSSINGAREACOLOR: 100, SELECTIONAREAOPACITY: 25,
  QPMODE: 0, CURSORSIZE: 5, ZOOMFACTOR: 60, LWDISPLAY: 0, TRANSPARENCYDISPLAY: 1, FILLMODE: 1,
  PLOTTRANSPARENCYOVERRIDE: 1, TEXTFILL: 1, PSLTSCALE: 1,
  MEASUREINIT: 0, MAXARRAY: 100000, SAVETIME: 10, ISAVEBAK: 1, SAVEFILEPATH: '',
  LUNITS: 2, LUPREC: 4, AUNITS: 0, AUPREC: 0, ANGBASE: 0, ANGDIR: 0,
};

const OSNAP_ROWS: ReadonlyArray<readonly [string, number]> = [
  ['Endpoint', 1], ['Midpoint', 2], ['Center', 4], ['Geometric Center', 1024], ['Node', 8], ['Quadrant', 16], ['Intersection', 32],
  ['Extension', 4096], ['Insertion', 64], ['Perpendicular', 128], ['Tangent', 256], ['Nearest', 512], ['Apparent Intersection', 2048], ['Parallel', 8192],
];

const FILTER_ROWS: ReadonlyArray<readonly [string, number]> = [
  ['Objects on locked layers', 1], ['Xrefs', 2], ['Tables', 4], ['Groups', 32], ['Multiline text', 8], ['Hatches', 16],
];

const POLAR_ANGLES: ReadonlyArray<readonly [string, string]> = [['90', '90'], ['45', '45'], ['30', '30'], ['22.5', '22.5'], ['18', '18'], ['15', '15'], ['10', '10'], ['5', '5']];
const SCALES: ReadonlyArray<readonly [string, string]> = ['75', '100', '125', '150', '175', '200', '250', '300'].map((n) => [n, `${n} %`] as const);
const LINEAR_UNITS: ReadonlyArray<readonly [string, string]> = [['1', 'Scientific'], ['2', 'Decimal'], ['3', 'Engineering'], ['4', 'Architectural'], ['5', 'Fractional']];
const ANGULAR_UNITS: ReadonlyArray<readonly [string, string]> = [['0', 'Decimal degrees'], ['1', 'Degrees, minutes, seconds'], ['2', 'Gradians'], ['3', 'Radians'], ['4', 'Surveyor’s units']];

type Keys<T> = { [K in keyof Prefs]: Prefs[K] extends T ? K : never }[keyof Prefs];

const asNum = (v: unknown, d: number): number => {
  const n = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : typeof v === 'boolean' ? Number(v) : NaN;
  return Number.isFinite(n) ? n : d;
};

const tokenColor = (name: string, fallback: string): string => {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9a-f]{6}$/i.test(v) ? v : fallback;
};

const systemLanguage = (): string => {
  const primary = (navigator.language || 'en').split(/[-_]/)[0].toLowerCase();
  return isLang(primary) ? primary : 'en';
};

export class SettingsDialog extends Dialog {
  private prefs: Prefs = loadPrefs();
  private readonly sections = new Map<string, HTMLElement>();
  private readonly nav = el('<div class="cv-prefs-nav" role="tablist"></div>');
  private readonly syncs: Array<() => void> = [];
  private readonly pending = new Map<string, VarValue>();
  private readonly timers = new Map<string, number>();
  private readonly grid = el('<div class="nm-theme-grid" role="group" aria-label="Theme"></div>');
  private readonly toolList = el('<div class="cv-prefs-list" role="list"></div>');
  private readonly kernelNote = el('<p class="cv-note cv-prefs-reserve" role="status"></p>');
  private pagesEl: HTMLElement;
  private shell: { frame: HTMLElement; rail: HTMLElement; port: HTMLElement; shade: SVGPathElement; line: SVGPathElement };
  private kernel: KernelStatus | null = null;
  private current = '';
  private spyRaf = 0;
  private wireRaf = 0;
  private syncRaf = 0;
  private spyMuted = 0;
  private wireD = '';
  private portY = -1;

  constructor(private readonly deps: SettingsDeps) {
    super('Preferences', 840);
    const grp = (label: string, ...content: HTMLElement[]): HTMLElement => {
      const g = el('<section class="cv-prefs-group"><h3 class="cv-prefs-label"></h3></section>');
      const h = q(g, '.cv-prefs-label');
      setText(h, t(label));
      onLanguage(() => setText(h, t(label)));
      g.append(...content);
      return g;
    };
    const nt = (text: string): HTMLElement => { const n = el('<p class="cv-note"></p>'); setText(n, text); return n; };
    const cols = (...content: HTMLElement[]): HTMLElement => { const c = el('<div class="cv-prefs-cols"></div>'); c.append(...content); return c; };
    const pages = el('<div class="cv-prefs-pages"></div>');
    const add = (name: string, ...groups: HTMLElement[]): void => {
      const label = el('<span class="cv-prefs-tablabel"></span>');
      const tab = el<HTMLButtonElement>(`<button class="cv-prefs-railtab" type="button" role="tab"><span class="cv-prefs-tabicon">${icon(RAIL_ICONS[name] ?? 'pfGeneral', 18)}</span></button>`);
      tab.append(label);
      tab.dataset.section = name;
      const paint = (): void => { setText(label, t(name)); tab.title = t(name); };
      paint();
      onLanguage(paint);
      tab.addEventListener('click', () => this.showSection(name, 'smooth'));
      this.nav.appendChild(tab);
      const card = el(`<section class="cv-prefs-page cv-prefs-sec" role="tabpanel" data-section="${name}"><button class="cv-prefs-sechead" type="button" aria-expanded="true"><span class="cv-prefs-secicon">${icon(RAIL_ICONS[name] ?? 'pfGeneral', 16)}</span><span class="cv-prefs-seclabel"></span><span class="cv-prefs-chev">${icon('chevronDown', 14)}</span></button><div class="cv-prefs-secbody"></div></section>`);
      const head = q(card, '.cv-prefs-seclabel');
      const paintHead = (): void => setText(head, t(name));
      paintHead();
      onLanguage(paintHead);
      q(card, '.cv-prefs-sechead').addEventListener('click', () => this.foldSection(name));
      q(card, '.cv-prefs-secbody').append(...groups);
      pages.appendChild(card);
      this.sections.set(name, card);
    };

    add('General',
      grp('Startup',
        this.pToggle('Show Home at launch', 'autoShowHome'),
        this.pToggle('Show Home when the last drawing closes', 'homeOnLastClose'),
        this.pToggle('Restore the last session', 'restoreSession')),
      grp('Behavior',
        this.pSlider('Recent files listed', 'recentFileCount', 0, 100, 1, DEFAULT_PREFS.recentFileCount),
        nt('How many recent files Home and the File menu list. Zero lists none.')),
      grp('Settings Storage', this.dataFolderRows(), nt('Window preferences, theme and panel layout stay in this window’s own storage. Sessions, autosaves and the modeling kernel live in the data folder.')),
      grp('Reset', buttonRow('Reset all preferences', 'Reset All Preferences...', () => { void this.resetAll(); }, 'danger').el, nt('Removes every saved preference, the theme and the panel layout, then reloads the window. Drawings are not touched.')));

    add('Interface',
      grp('Theme',
        this.grid,
        this.accentRow(),
        this.bindP(sliderRow('Accent intensity', 0, 1.5, 0.05, (v) => { setIntensity(v); }, { def: 1 }), () => readChoice().intensity ?? 1),
        this.pToggleRaw('Match system appearance', (p) => p.themeMode === 'system', (on) => { this.change({ themeMode: on ? 'system' : 'fixed' }); this.queueSync(); }),
        this.pairSelect('Light theme', true, 'themeLight'),
        this.pairSelect('Dark theme', false, 'themeDark')),
      grp('Language, Text and Scale', this.languageRow(), this.textSizeRow(), this.scaleRow()),
      grp('Motion and Notices', this.animationRow(), this.pSlider('Notice duration (seconds, 0 stays)', 'noticeSeconds', 0, 60, 1, DEFAULT_PREFS.noticeSeconds)));

    add('Workspace',
      grp('Panels',
        this.pToggle('Show command line', 'showCommandLine'),
        this.pToggle('Show side dock', 'showDock'),
        this.pSlider('Dock width', 'dockWidth', 240, 560, 4, DEFAULT_PREFS.dockWidth),
        buttonRow('Panel layout', 'Reset Panels', () => { deps.commands.run('dock-reset'); }, 'ghost').el),
      grp('Command line', this.historyRow(), nt('F2 opens the full command history. Ctrl+9 shows or hides the command line; typing anywhere still reaches it.')));

    add('Display',
      grp('Interface', this.themeModeRow(), this.animationRow(), this.scaleRow()),
      grp('Drawing area',
        this.canvasColorRow('Model background', 'modelBackground', () => tokenColor('--canvas-bg-model', '#22282f')),
        this.canvasColorRow('Layout paper', 'layoutPaper', () => tokenColor('--canvas-paper', '#ffffff')),
        this.vSlider('Crosshair size (%)', 'CURSORSIZE', 1, 100, 1),
        this.historyRow(),
        this.pCheck('Keep the system cursor visible over the drawing area', 'systemCursor'),
        nt('Turn this on when a screen magnifier, reader or recorder follows the system cursor.')));

    const aperture = this.vSlider('Object snap aperture (px)', 'APERTURE', 1, 50, 1);
    add('Drafting',
      grp('Object snap',
        this.pSlider('Object snap marker size', 'snapMarkerSize', 5, 31, 1, DEFAULT_PREFS.snapMarkerSize),
        aperture,
        nt('The aperture is how near the cursor must come to a point for an object snap to find it.')),
      grp('Snap, grid, polar tracking and Dynamic Input', buttonRow('Settings', 'Drafting Settings...', () => this.showSection('Snaps and Tracking', 'smooth'), 'ghost').el));

    const grips = this.vCheck('Show grips', 'GRIPS');
    const gripLimit = this.vNumber('Object selection limit for display of grips', 'GRIPOBJLIMIT', 0, 32767, 1);
    this.syncs.push(() => enable(gripLimit, this.num('GRIPS') !== 0));
    const area = this.vCheck('Indicate selection area', 'SELECTIONAREA');
    const windowColor = this.vAci('Window selection color', 'WINDOWAREACOLOR');
    const crossColor = this.vAci('Crossing selection color', 'CROSSINGAREACOLOR');
    const opacity = this.vSlider('Selection area opacity (%)', 'SELECTIONAREAOPACITY', 0, 100, 1);
    this.syncs.push(() => { for (const r of [windowColor, crossColor, opacity]) enable(r, this.num('SELECTIONAREA') !== 0); });
    add('Selection',
      cols(
        grp('Selection modes',
          this.vSlider('Pickbox size (px)', 'PICKBOX', 0, 50, 1),
          this.vCheck('Select objects first, then choose a command', 'PICKFIRST'),
          this.vCheck('Hold Shift to add to the selection', 'PICKADD', { on: 0, off: 1 }),
          this.vCheck('Select using two clicks only', 'PICKDRAG', { on: 0, off: 2 }),
          this.vBit('Object grouping', 'PICKSTYLE', 1),
          this.vCheck('Show Quick Properties for selected objects', 'QPMODE', { on: -1, off: 0 }),
          this.canvasColorRow('Selection effect color', 'selectionColor', () => '#4a8fff')),
        grp('Grips and preview',
          this.vSlider('Grip size (px)', 'GRIPSIZE', 1, 20, 1),
          grips,
          gripLimit,
          this.vBit('Preview when a command is active', 'SELECTIONPREVIEW', 2),
          this.vBit('Preview when no command is active', 'SELECTIONPREVIEW', 1))),
      grp('Visual Effect Settings',
        area, windowColor, crossColor, opacity,
        nt('Exclude from the selection preview:'),
        ...FILTER_ROWS.map(([label, mask]) => this.vBit(label, 'PREVIEWFILTER', mask))));

    const polarOn = this.vBit('Polar tracking on', 'AUTOSNAP', 8);
    const addAngles = this.vBit('Additional angles', 'POLARMODE', 4);
    const addText = this.vText('Additional angle list (degrees, separated by semicolons)', 'POLARADDANG');
    this.syncs.push(() => enable(addText, (this.num('POLARMODE') & 4) !== 0));
    const osOn = this.bindV(checkRow('Object snap on', (on) => this.setVar('OSMODE', on ? this.num('OSMODE') & ~16384 : this.num('OSMODE') | 16384)), () => (this.num('OSMODE') & 16384) === 0);
    const dynOn = this.vCheck('Enable Dynamic Input', 'DYNMODE');
    const dynRows = [
      this.vSelect('Second and next points: format', 'DYNPIFORMAT', [['0', 'Polar (distance < angle)'], ['1', 'Cartesian (x, y)']]),
      this.vSelect('Second and next points: reference', 'DYNPICOORDS', [['0', 'Relative'], ['1', 'Absolute']]),
      this.vCheck('Show command prompting near the crosshairs', 'DYNPROMPT'),
    ];
    this.syncs.push(() => { for (const r of dynRows) enable(r, this.num('DYNMODE') !== 0); });
    const polarDist = this.vNumber('Polar distance', 'POLARDIST', 0, 1e12 - 1, 0.01);
    this.syncs.push(() => enable(polarDist, this.num('SNAPTYPE') === 1));
    add('Snaps and Tracking',
      grp('Snap and Grid',
        this.vCheck('Snap on', 'SNAPMODE'),
        this.vSelect('Snap style', 'SNAPSTYL', [['0', 'Rectangular snap'], ['1', 'Isometric snap']]),
        this.vPoint('Snap X spacing', 'SNAPUNIT', 0),
        this.vPoint('Snap Y spacing', 'SNAPUNIT', 1),
        this.vSelect('Snap type', 'SNAPTYPE', [['0', 'Grid snap'], ['1', 'PolarSnap']]),
        polarDist,
        this.vCheck('Grid on', 'GRIDMODE'),
        this.vPoint('Grid X spacing', 'GRIDUNIT', 0),
        this.vPoint('Grid Y spacing', 'GRIDUNIT', 1),
        this.vNumber('Major line every', 'GRIDMAJOR', 1, 100, 1)),
      grp('Polar Tracking',
        polarOn,
        this.vSelect('Increment angle', 'POLARANG', POLAR_ANGLES),
        addAngles,
        addText,
        this.vSelect('Object snap tracking settings', 'POLARMODE', [['0', 'Track orthogonally only'], ['2', 'Track using all polar angle settings']], 2),
        this.vSelect('Polar angle measurement', 'POLARMODE', [['0', 'Absolute'], ['1', 'Relative to last segment']], 1),
        this.vBit('Object snap tracking on', 'AUTOSNAP', 16)),
      grp('Object Snap',
        osOn,
        cols(...OSNAP_ROWS.map(([label, mask]) => this.vBit(label, 'OSMODE', mask))),
        this.vCheck('Object snaps find hatch objects', 'OSNAPHATCH'),
        this.vBit('Show snap marker', 'AUTOSNAP', 1),
        this.vBit('Show snap tooltip', 'AUTOSNAP', 4),
        this.vBit('Show tracking tooltip', 'AUTOSNAP', 32)),
      grp('Dynamic Input', dynOn, ...dynRows),
      grp('Ortho', this.vCheck('Ortho on', 'ORTHOMODE'), nt('Holding Shift flips Ortho while it is held.')));

    add('Units and Precision',
      grp('Display units',
        this.pSelect('Length unit', 'units', DRAW_UNITS),
        this.pSlider('Decimal places', 'precision', 0, 8, 1, DEFAULT_PREFS.precision),
        this.pSelect('Angle unit', 'angleUnit', ANGLE_UNITS),
        nt('Used by the status bar and readouts.')),
      grp('Current drawing',
        this.vSelect('Linear format', 'LUNITS', LINEAR_UNITS),
        this.vSlider('Linear precision', 'LUPREC', 0, 8, 1),
        this.vSelect('Angular format', 'AUNITS', ANGULAR_UNITS),
        this.vSlider('Angular precision', 'AUPREC', 0, 8, 1),
        this.vNumber('Angle zero direction (degrees)', 'ANGBASE', -360, 360, 0.1),
        this.vSelect('Positive angle direction', 'ANGDIR', [['0', 'Counter-clockwise'], ['1', 'Clockwise']]),
        nt('These belong to the active drawing and are saved with it.')));

    add('Open and Save',
      grp('New drawings',
        this.bindP(radioRow('Save new drawings as', [['dxf', 'DXF'], ['dwg', 'DWG']], (v) => this.change({ saveFormat: v === 'dwg' ? 'dwg' : 'dxf' })), (p) => p.saveFormat),
        this.pSelect('Default save version', 'saveVersion', SAVE_VERSIONS),
        this.bindV(radioRow('Units of new drawings', [['0', 'Imperial (inches)'], ['1', 'Metric (millimetres)']], (v) => this.setVar('MEASUREINIT', Number(v))), () => String(this.num('MEASUREINIT'))),
        nt('New drawings and the first drawing at startup use these units unless a default template is set. A drawing opened from a file keeps that file’s format, and drawings with no file yet are saved in the default version.')),
      grp('Autosave and backup',
        this.vNumber('Automatic save every (minutes, 0 is off)', 'SAVETIME', 0, 600, 1),
        this.vCheck('Create backup copy with each save', 'ISAVEBAK'),
        this.vText('Automatic save file location', 'SAVEFILEPATH', 'Folder chosen by the app'),
        nt('The backup keeps the previous file as name.bak.')),
      grp('DWG files', ...dwgRows((fn) => this.syncs.push(fn))));

    add('Plot and Publish',
      grp('Plotting',
        this.vSelect('Plot transparency', 'PLOTTRANSPARENCYOVERRIDE', [['0', 'Never plot transparency'], ['1', 'Follow page setup'], ['2', 'Always plot transparency']]),
        this.vCheck('Fill TrueType text in plots', 'TEXTFILL'),
        this.vCheck('Scale linetypes in paper space', 'PSLTSCALE'),
        nt('Page setups and plot styles are edited in the Plot dialog.')));

    add('User Preferences',
      grp('Interface language', this.languageRow()),
      grp('Limits and clicks',
        this.vNumber('Largest array (objects)', 'MAXARRAY', 100, 10000000, 1),
        nt('An array that would create more objects than this is refused.'),
        this.pCheck('Time-sensitive right-click', 'timeRightClick'),
        nt('A quick right-click is Enter and holding opens the menu. Turned off, a right-click while a command runs always opens the shortcut menu.')));

    add('Profiles',
      grp('Profile',
        nt('FormCAD keeps these preferences, object snap modes and drafting toggles for your account and restores them at start.'),
        buttonRow('Defaults', 'Reset to Defaults', () => { void this.resetProfile(); }, 'danger').el,
        buttonRow('Report', 'Copy as JSON', () => { void this.copyReport(); }, 'ghost').el,
        nt('Reset keeps the interface language.')));

    const kStatus = infoRow('Status');
    const kVersion = infoRow('Version');
    const kPath = infoRow('Location');
    const install = buttonRow('Kernel', 'Install the modeling kernel', () => { void this.installKernel(); });
    this.syncs.push(() => {
      const k = this.kernel ?? this.deps.capabilities()?.kernel ?? null;
      const live = this.kernel;
      kStatus.set(live?.installing ? `Installing ${Math.round(live.progress)} %` : k?.available ? 'Available' : 'Not installed');
      kVersion.set(k?.version ?? '');
      kPath.set((this.deps.capabilities()?.kernel.path) ?? '');
      setText(this.kernelNote, live?.message || (k?.available ? 'Solid modeling is ready.' : 'Drawing and editing in 2D work without the kernel.'));
      install.button.disabled = !!(k?.available || live?.installing);
    });
    add('Modeling', grp('Kernel', kStatus.el, kVersion.el, kPath.el, install.el, this.kernelNote));

    add('Graph', grp('Graph editor', nt('Options for the node graph editor appear here when a graph is open.')));

    const platform = infoRow('Platform');
    const version = infoRow('Engine version');
    this.syncs.push(() => { const c = this.deps.capabilities(); platform.set(c?.platform ?? 'Engine offline'); version.set(c?.version ?? ''); });
    add('Performance',
      grp('Display',
        this.vSlider('Wheel zoom strength', 'ZOOMFACTOR', 3, 100, 1),
        this.vCheck('Show lineweights on screen', 'LWDISPLAY'),
        this.vCheck('Show transparency on screen', 'TRANSPARENCYDISPLAY'),
        this.vCheck('Fill solids and hatches', 'FILLMODE'),
        nt('Switching these off speeds up large drawings.')),
      grp('Engine', platform.el, version.el));

    add('Plugins', grp('Registered tools', this.toolList, nt('Tools added by plugins appear here and in the tool rail.')));

    const address = pathRow('MCP address', () => { void this.copy(`${location.origin}/mcp`); });
    address.set(`${location.origin}/mcp`);
    const tokenFile = pathRow('Token file', () => { void this.copy(this.tokenPath()); });
    this.syncs.push(() => tokenFile.set(this.tokenPath()));
    add('Agents',
      grp('Outside agents', address.el, tokenFile.el, nt('An outside agent connects to the address above and sends the token from the file in the X-FormCAD-Token header. The token changes every time the engine starts.')));

    this.body.appendChild(el('<div class="cv-prefs"></div>'));
    q(this.body, '.cv-prefs').append(pages);
    this.pagesEl = pages;
    const frame = q<HTMLElement>(this.scrim, '.cv-dialog');
    frame.classList.add('cv-prefs-dlg');
    q(this.scrim, '.cv-dialog-head').prepend(el(`<span class="cv-prefs-headicon">${icon('settings', 16)}</span>`));
    let collapsed = stored('formCAD.prefsRailCollapsed') === '1';
    const fold = el<HTMLButtonElement>(`<button class="cv-prefs-fold" type="button">${icon('pfFold', 16)}</button>`);
    const paintRail = (): void => {
      setClass(frame, 'is-rail-collapsed', collapsed);
      fold.title = t(collapsed ? 'Expand tabs' : 'Collapse tabs');
      fold.setAttribute('aria-label', fold.title);
      fold.setAttribute('aria-expanded', String(!collapsed));
    };
    fold.addEventListener('click', () => {
      collapsed = !collapsed;
      store('formCAD.prefsRailCollapsed', collapsed ? '1' : '0');
      paintRail();
      this.queueWire();
    });
    paintRail();
    onLanguage(paintRail);
    const rail = el('<div class="cv-prefs-rail"></div>');
    rail.append(this.nav, fold);
    const wire = el<HTMLElement>('<svg class="cv-prefs-wire" aria-hidden="true"><path class="cv-prefs-wire-shade"></path><path class="cv-prefs-wire-line"></path></svg>') as unknown as SVGSVGElement;
    const port = el('<span class="cv-prefs-port" aria-hidden="true"></span>');
    frame.append(rail, wire, port);
    this.shell = { frame, rail, port, shade: q<SVGPathElement>(wire, '.cv-prefs-wire-shade'), line: q<SVGPathElement>(wire, '.cv-prefs-wire-line') };
    pages.addEventListener('scroll', () => this.queueSpy(), { passive: true });
    new ResizeObserver(() => this.queueWire()).observe(frame);
    window.addEventListener('resize', () => this.queueWire());
    this.button('Done', 'primary', () => this.close());

    this.grid.innerHTML = themeSwatchesHtml();
    this.grid.addEventListener('click', (e) => {
      const id = (e.target as HTMLElement).closest<HTMLElement>('[data-theme-id]')?.dataset.themeId;
      if (!id) return;
      const theme = THEMES[id];
      this.change({ themeMode: 'fixed', ...(theme?.light ? { themeLight: id } : { themeDark: id }) });
      setTheme(id);
      this.queueSync();
    });
    document.addEventListener('nm:ui-settings-changed', () => { if (this.isOpen) this.queueSync(); });
    document.addEventListener('formcad:prefs-changed', () => { if (this.isOpen) { this.prefs = loadPrefs(); this.queueSync(); } });
    sysvars.onChange(() => { if (this.isOpen) this.queueSync(); });
    events.on('kernel', (e) => {
      this.kernel = { available: !!e.available, version: e.version ?? null, installing: !!e.installing, progress: e.progress ?? 0, message: e.message ?? '' };
      if (this.isOpen) this.queueSync();
    });
    this.showSection('General');
  }

  show(section?: string): void {
    this.prefs = loadPrefs();
    this.sync();
    if (!this.isOpen) {
      void sysvars.load();
      void api.kernelStatus().then((s) => { this.kernel = s; this.queueSync(); }, () => undefined);
      this.open();
    }
    if (section && this.sections.has(section)) {
      this.showSection(section);
      this.scrollToSection(section, 'auto');
    }
    this.queueWire();
  }

  private change(patch: Partial<Prefs>): void {
    this.prefs = updatePrefs(patch);
  }

  private value(name: string): unknown {
    return this.pending.has(name) ? this.pending.get(name) : (sysvars.get(name) ?? DEFAULTS[name]);
  }

  private num(name: string): number {
    const d = DEFAULTS[name];
    return asNum(this.value(name), typeof d === 'number' ? d : 0);
  }

  private setVar(name: string, value: VarValue, delay = 0): void {
    this.pending.set(name, value);
    window.clearTimeout(this.timers.get(name));
    this.timers.set(name, window.setTimeout(() => {
      this.timers.delete(name);
      void sysvars.set(name, value).finally(() => {
        if (this.pending.get(name) === value) this.pending.delete(name);
        this.queueSync();
      });
    }, delay));
  }

  private bindP<T>(row: Row<T>, read: (p: Prefs) => T): HTMLElement {
    this.syncs.push(() => row.set(read(this.prefs)));
    return row.el;
  }

  private bindV<T>(row: Row<T>, read: () => T): HTMLElement {
    this.syncs.push(() => row.set(read()));
    return row.el;
  }

  private pToggle(label: string, key: Keys<boolean>): HTMLElement {
    return this.bindP(toggleRow(label, (v) => this.change({ [key]: v } as Partial<Prefs>)), (p) => p[key] as boolean);
  }

  private pToggleRaw(label: string, read: (p: Prefs) => boolean, write: (on: boolean) => void): HTMLElement {
    return this.bindP(toggleRow(label, write), read);
  }

  private pCheck(label: string, key: Keys<boolean>): HTMLElement {
    return this.bindP(checkRow(label, (v) => this.change({ [key]: v } as Partial<Prefs>)), (p) => p[key] as boolean);
  }

  private pSlider(label: string, key: Keys<number>, min: number, max: number, step: number, def: number): HTMLElement {
    return this.bindP(sliderRow(label, min, max, step, (v) => this.change({ [key]: v } as Partial<Prefs>), { def }), (p) => p[key] as number);
  }

  private pSelect(label: string, key: Keys<string>, options: ReadonlyArray<readonly [string, string]>): HTMLElement {
    return this.bindP(selectRow(label, options, (v) => this.change({ [key]: v } as Partial<Prefs>)), (p) => p[key] as string);
  }

  private pairSelect(label: string, light: boolean, key: 'themeLight' | 'themeDark'): HTMLElement {
    const options = Object.entries(THEMES).filter(([, th]) => !!th.light === light).map(([id, th]) => [id, th.label] as const);
    const row = selectRow(label, options, (v) => {
      this.change({ [key]: v } as Partial<Prefs>);
      if (this.prefs.themeMode === 'fixed' && !!THEMES[readChoice().theme]?.light === light) setTheme(v);
      this.queueSync();
    });
    return this.bindP(row, (p) => p[key]);
  }

  private accentRow(): HTMLElement {
    const row = colorRow('Accent color', (hex) => { setAccent(hex); this.queueSync(); });
    this.syncs.push(() => row.set(readChoice().accentColor));
    return row.el;
  }

  private themeModeRow(): HTMLElement {
    const row = selectRow('Interface theme', [['system', 'Use System Setting'], ['light', 'Light'], ['dark', 'Dark']], (v) => {
      if (v === 'system') this.change({ themeMode: 'system' });
      else {
        this.change({ themeMode: 'fixed' });
        setTheme(v === 'light' ? this.prefs.themeLight : this.prefs.themeDark);
      }
      this.queueSync();
    });
    return this.bindV(row, () => (this.prefs.themeMode === 'system' ? 'system' : THEMES[readChoice().theme]?.light ? 'light' : 'dark'));
  }

  private animationRow(): HTMLElement {
    const row = selectRow('Animation effects', ANIMATION_MODES, (v) => this.change({ animationMode: v === 'on' || v === 'off' ? v : 'system', animations: v !== 'off', reduceMotion: false }));
    return this.bindP(row, (p) => p.animationMode as string);
  }

  private scaleRow(): HTMLElement {
    return this.bindP(selectRow('Interface scale', SCALES, (v) => this.change({ uiScale: Number(v) })), (p) => String(p.uiScale));
  }

  private textSizeRow(): HTMLElement {
    return this.pSlider('Text size', 'fontSize', 10, 16, 1, DEFAULT_PREFS.fontSize);
  }

  private historyRow(): HTMLElement {
    const row = numberRow('Command line history (lines)', { min: 0, max: 12, step: 1 }, (v) => this.change({ historyLines: Math.round(v) }));
    return this.bindP(row, (p) => p.historyLines);
  }

  private languageRow(): HTMLElement {
    const options: Array<readonly [string, string]> = [['auto', 'Auto (system language)'], ...languages()];
    const row = selectRow('Interface language', options, (v) => {
      if (v === 'auto') {
        this.change({ languageAuto: true });
        void setLanguage(systemLanguage());
      } else {
        this.change({ languageAuto: false, language: v });
        void setLanguage(v);
      }
      this.queueSync();
    });
    return this.bindP(row, (p) => (p.languageAuto ? 'auto' : p.language));
  }

  private canvasColorRow(label: string, key: 'modelBackground' | 'layoutPaper' | 'selectionColor', fallback: () => string): HTMLElement {
    return this.bindP(colorDefaultRow(label, fallback, (hex) => this.change({ [key]: hex } as Partial<Prefs>)), (p) => p[key]);
  }

  private vSlider(label: string, name: string, min: number, max: number, step: number): HTMLElement {
    return this.bindV(sliderRow(label, min, max, step, (v) => this.setVar(name, v, 120), { def: DEFAULTS[name] as number }), () => this.num(name));
  }

  private vNumber(label: string, name: string, min: number, max: number, step: number): HTMLElement {
    return this.bindV(numberRow(label, { min, max, step }, (v) => this.setVar(name, v)), () => this.num(name));
  }

  private vCheck(label: string, name: string, map: { on: number; off: number } = { on: 1, off: 0 }): HTMLElement {
    const row = checkRow(label, (v) => this.setVar(name, v ? map.on : map.off));
    return this.bindV(row, () => this.num(name) !== map.off);
  }

  private vBit(label: string, name: string, mask: number): HTMLElement {
    const row = checkRow(label, (v) => {
      const cur = this.num(name) | 0;
      this.setVar(name, v ? cur | mask : cur & ~mask);
    });
    return this.bindV(row, () => ((this.num(name) | 0) & mask) !== 0);
  }

  private vSelect(label: string, name: string, options: ReadonlyArray<readonly [string, string]>, mask = 0): HTMLElement {
    if (mask) {
      const row = selectRow(label, options, (v) => {
        const cur = this.num(name) | 0;
        this.setVar(name, (cur & ~mask) | Number(v));
      });
      return this.bindV(row, () => String((this.num(name) | 0) & mask));
    }
    const row = selectRow(label, options, (v) => this.setVar(name, Number(v)));
    return this.bindV(row, () => {
      const cur = String(this.num(name));
      return options.some(([k]) => k === cur) ? cur : (options[0]?.[0] ?? '');
    });
  }

  private vText(label: string, name: string, placeholder = ''): HTMLElement {
    const row = textRow(label, (v) => this.setVar(name, v), placeholder);
    return this.bindV(row, () => String(this.value(name) ?? ''));
  }

  private vPoint(label: string, name: string, axis: number): HTMLElement {
    const read = (): number[] => {
      const v = this.value(name);
      return Array.isArray(v) && v.length >= 2 ? [asNum(v[0], 0.5), asNum(v[1], 0.5)] : [0.5, 0.5];
    };
    const row = numberRow(label, { min: 0, step: 0.01 }, (v) => {
      const p = read();
      p[axis] = v;
      this.setVar(name, p);
    });
    return this.bindV(row, () => read()[axis] ?? 0.5);
  }

  private vAci(label: string, name: string): HTMLElement {
    return this.bindV(aciRow(label, (n) => this.setVar(name, n)), () => this.num(name));
  }

  private tokenPath(): string {
    const c = this.deps.capabilities();
    if (!c?.dataDir) return '';
    return `${c.dataDir}${c.platform.toLowerCase().startsWith('win') ? '\\' : '/'}session.token`;
  }

  private dataFolderRows(): HTMLElement {
    const path = pathRow('Data folder', () => { void this.copy(this.deps.capabilities()?.dataDir ?? ''); });
    const source = infoRow('Chosen by');
    this.syncs.push(() => {
      const c = this.deps.capabilities();
      path.set(c?.dataDir ?? '');
      source.set(c?.dataDirSource ?? (c ? '' : 'Engine offline'));
    });
    const box = el('<div class="cv-panel-section"></div>');
    box.append(path.el, source.el);
    return box;
  }

  private async copy(text: string): Promise<void> {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied', 'info');
    } catch {
      toast('The clipboard is not available', 'error');
    }
  }

  private async copyReport(): Promise<void> {
    const vars: Record<string, unknown> = {};
    for (const name of Object.keys(DEFAULTS)) vars[name] = this.value(name);
    await this.copy(JSON.stringify({ preferences: loadPrefs(), theme: readChoice(), variables: vars }, null, 2));
  }

  private async resetProfile(): Promise<void> {
    if (!(await confirmAction('Reset to Defaults', 'Every drafting, selection and interface preference returns to its default. The interface language is kept.', 'Reset', true))) return;
    for (const [name, value] of Object.entries(DEFAULTS)) this.setVar(name, value);
    const keep = loadPrefs();
    this.prefs = updatePrefs({ ...DEFAULT_PREFS, language: keep.language, languageAuto: keep.languageAuto, shortcuts: keep.shortcuts });
    setTheme(DEFAULT_THEME);
    setAccent(DEFAULT_ACCENT);
    setIntensity(1);
    this.queueSync();
  }

  private async resetAll(): Promise<void> {
    if (!(await confirmAction('Reset All Preferences', 'This removes every saved preference, the theme and the panel layout, then reloads the window.', 'Reset', true))) return;
    try {
      const keys: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && (k.startsWith('formCAD.') || k === STORAGE_KEY)) keys.push(k);
      }
      for (const k of keys) localStorage.removeItem(k);
    } catch {
      return;
    }
    location.reload();
  }

  private async installKernel(): Promise<void> {
    try {
      this.kernel = await api.kernelInstall();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'The kernel could not be installed', 'error');
    }
    this.queueSync();
  }

  private queueSync(): void {
    if (this.syncRaf) return;
    this.syncRaf = requestAnimationFrame(() => { this.syncRaf = 0; this.sync(); });
  }

  private sync(): void {
    for (const fn of this.syncs) fn();
    const c = readChoice();
    for (const b of Array.from(this.grid.querySelectorAll<HTMLElement>('[data-theme-id]'))) {
      const id = b.dataset.themeId ?? '';
      const active = id === c.theme;
      setClass(b, 'is-active', active);
      const border = active ? c.accentColor : THEMES[id]?.vars['--border-color'] ?? '';
      if (b.dataset.border !== border) { b.dataset.border = border; b.style.borderColor = border; }
      const title = THEMES[id]?.label ?? id;
      if (b.title !== title) b.title = title;
    }
    patchList(this.toolList, toolList(), {
      key: (tool) => tool.id,
      create: (tool) => {
        const row = el('<div class="cv-list-row" role="listitem"><span class="cv-list-icon"></span><span class="cv-list-name"></span><span class="cv-list-meta"></span></div>');
        q(row, '.cv-list-icon').innerHTML = tool.icon();
        return row;
      },
      update: (node, tool) => {
        setText(q(node, '.cv-list-name'), tool.label);
        setText(q(node, '.cv-list-meta'), tool.plugin ?? tool.key);
      },
    });
  }

  private showSection(name: string, scroll: ScrollBehavior | null = null): void {
    if (!this.sections.has(name)) return;
    this.markSection(name);
    if (scroll) this.scrollToSection(name, scroll);
  }

  private markSection(name: string): void {
    if (this.current === name) return;
    this.current = name;
    for (const [n, page] of this.sections) setClass(page, 'is-current', n === name);
    for (const tab of Array.from(this.nav.children) as HTMLElement[]) {
      const on = tab.dataset.section === name;
      setClass(tab, 'is-active', on);
      tab.setAttribute('aria-selected', String(on));
    }
    this.queueWire();
  }

  private scrollToSection(name: string, behavior: ScrollBehavior): void {
    const sec = this.sections.get(name);
    if (!sec) return;
    if (sec.classList.contains('is-folded')) this.foldSection(name);
    const top = sec.getBoundingClientRect().top - this.pagesEl.getBoundingClientRect().top + this.pagesEl.scrollTop - 12;
    this.spyMuted = performance.now() + 700;
    this.pagesEl.scrollTo({ top, behavior });
  }

  private foldSection(name: string): void {
    const sec = this.sections.get(name);
    if (!sec) return;
    const folded = !sec.classList.contains('is-folded');
    setClass(sec, 'is-folded', folded);
    setHidden(q(sec, '.cv-prefs-secbody'), folded);
    q(sec, '.cv-prefs-sechead').setAttribute('aria-expanded', String(!folded));
    this.queueWire();
    this.queueSpy();
  }

  private queueSpy(): void {
    if (this.spyRaf) return;
    this.spyRaf = requestAnimationFrame(() => {
      this.spyRaf = 0;
      const pages = this.pagesEl;
      if (!pages.clientHeight || performance.now() < this.spyMuted) return;
      const edge = pages.getBoundingClientRect().top + 24;
      const names = Array.from(this.sections.keys());
      let best = '', bestD = Infinity;
      if (pages.scrollHeight > pages.clientHeight + 4 && pages.scrollTop + pages.clientHeight >= pages.scrollHeight - 2) best = names[names.length - 1] ?? '';
      else {
        for (const [n, sec] of this.sections) {
          const top = sec.getBoundingClientRect().top, d = top <= edge ? edge - top : top - edge + 100000;
          if (d < bestD) { bestD = d; best = n; }
        }
      }
      if (best) this.markSection(best);
    });
  }

  private queueWire(): void {
    if (this.wireRaf) return;
    this.wireRaf = requestAnimationFrame(() => { this.wireRaf = 0; this.drawWire(); });
  }

  private drawWire(): void {
    const s = this.shell;
    if (this.scrim.hidden) return;
    const F = s.frame.getBoundingClientRect();
    const tab = this.nav.querySelector<HTMLElement>('.cv-prefs-railtab.is-active');
    const head = s.frame.querySelector<HTMLElement>('.cv-dialog-head');
    if (!F.width || !tab || !head) return;
    const N = this.nav.getBoundingClientRect();
    let T = tab.getBoundingClientRect();
    if (T.top < N.top || T.bottom > N.bottom) {
      this.nav.scrollTop += T.top < N.top ? T.top - N.top - 6 : T.bottom - N.bottom + 6;
      T = tab.getBoundingClientRect();
    }
    const R = s.rail.getBoundingClientRect(), H = head.getBoundingClientRect();
    const portY = Math.round(H.bottom - F.top), sx = Math.round(T.right - F.left), ty = Math.round(T.top - F.top + T.height / 2);
    const rr = R.right - F.left, trunk = Math.round(rr - rr * 0.45), dy = portY - ty, r = 10, dir = dy > 0 ? 1 : -1;
    const d = Math.abs(dy) < 2 * r
      ? `M ${sx} ${ty} H ${trunk} V ${portY} H -7`
      : `M ${sx} ${ty} H ${trunk - r} a ${r} ${r} 0 0 ${dir > 0 ? 1 : 0} ${r} ${dir * r} V ${portY - dir * r} a ${r} ${r} 0 0 ${dir > 0 ? 0 : 1} ${r} ${dir * r} H -7`;
    if (d !== this.wireD) { this.wireD = d; s.shade.setAttribute('d', d); s.line.setAttribute('d', d); }
    if (portY !== this.portY) { this.portY = portY; s.port.style.transform = `translateY(${portY}px)`; }
  }
}

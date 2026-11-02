import { auto } from '../../io/api-auto';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setValue } from '../dom';
import { pickPath, type FileKind } from '../file-dialogs';
import { icon } from '../icons';
import { t } from '../i18n';

const LSP: FileKind = { name: 'LISP application', extensions: ['lsp'] };
const STARTUP = [
  { file: 'acad.lsp', note: 'Runs once, in the first drawing of the session.' },
  { file: 'acaddoc.lsp', note: 'Runs in every drawing that is opened or created.' },
];

export class AppLoadDialog extends Dialog {
  private readonly path: HTMLInputElement;
  private readonly load: HTMLButtonElement;
  private readonly msg: HTMLElement;
  private readonly loadedList: HTMLElement;
  private readonly cmdList: HTMLElement;
  private readonly startList: HTMLElement;
  private readonly folderList: HTMLElement;
  private readonly saveFolders: HTMLButtonElement;
  private folders: string[] = [];
  private saved: string[] = [];
  private loaded: string[] = [];
  private commands: string[] = [];
  private found: Record<string, string> = {};

  constructor() {
    super('Load Application', 620);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="al"><section class="al-sec"><h4>Load a LISP file</h4><div class="al-load"><input class="cv-input al-path" type="text" spellcheck="false" autocomplete="off" aria-label="LISP file">' +
      '<button class="cv-btn al-browse" type="button">Browse...</button><button class="cv-btn cv-btn-primary al-go" type="button">Load</button></div><p class="al-msg" role="status"></p></section>' +
      '<section class="al-sec"><h4>Loaded in this drawing</h4><div class="al-list al-loaded"></div><div class="al-chips al-cmds"></div></section>' +
      '<section class="al-sec"><h4>Startup files</h4><div class="al-list al-start"></div></section>' +
      '<section class="al-sec"><h4>Support folders</h4><div class="al-list al-folders"></div><div class="al-row"><button class="cv-btn al-addf" type="button">Add Folder</button><button class="cv-btn al-savef" type="button">Save Folders</button></div>' +
      '<p class="cv-note al-note"></p></section></div>'));
    for (const h of Array.from(this.body.querySelectorAll('h4'))) setText(h, t(h.textContent ?? ''));
    this.path = q<HTMLInputElement>(this.body, '.al-path');
    this.load = q<HTMLButtonElement>(this.body, '.al-go');
    this.msg = q(this.body, '.al-msg');
    this.loadedList = q(this.body, '.al-loaded');
    this.cmdList = q(this.body, '.al-cmds');
    this.startList = q(this.body, '.al-start');
    this.folderList = q(this.body, '.al-folders');
    this.saveFolders = q<HTMLButtonElement>(this.body, '.al-savef');
    this.path.placeholder = t('Name or full path of a .lsp file');
    setText(q(this.body, '.al-browse'), t('Browse...'));
    setText(this.load, t('Load'));
    setText(q(this.body, '.al-addf'), t('Add Folder'));
    setText(this.saveFolders, t('Save Folders'));
    setText(q(this.body, '.al-note'), t('Routines can read and write files only inside these folders. Startup files are read from the first one.'));
    this.button('Close', 'primary', () => this.close());
    q(this.body, '.al-browse').addEventListener('click', () => { void this.browse(); });
    this.load.addEventListener('click', () => { void this.go(); });
    this.path.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void this.go(); } });
    q(this.body, '.al-addf').addEventListener('click', () => { this.folders.push(''); this.paintFolders(); const last = this.folderList.lastElementChild?.querySelector('input'); last?.focus(); });
    this.saveFolders.addEventListener('click', () => { void this.saveSupport(); });
  }

  async showFor(): Promise<void> {
    await this.pull();
    if (!this.isOpen) this.open(this.path);
  }

  private async pull(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const [sup, ld, cm] = await Promise.all([auto.support(id), auto.loaded(id), auto.commands(id)]);
      this.folders = sup.folders;
      this.saved = [...sup.folders];
      this.loaded = ld.loaded;
      this.commands = cm.commands;
      for (const s of STARTUP) {
        const r = await auto.lisp(id, `(findfile "${s.file}")`);
        this.found[s.file] = r.value && r.value !== 'nil' ? r.value.replace(/^"|"$/g, '') : '';
      }
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
    this.paint();
  }

  private say(text: string, bad = false): void {
    setText(this.msg, text);
    setClass(this.msg, 'is-bad', bad);
  }

  private paint(): void {
    patchList(this.loadedList, this.loaded.map((p) => ({ p })), {
      key: (r) => r.p,
      create: (r) => { const n = el<HTMLElement>('<div class="al-item"></div>'); setText(n, r.p); n.title = r.p; return n; },
      update: (n, r) => setText(n, r.p),
    });
    if (this.loaded.length === 0 && !this.loadedList.querySelector('.al-empty')) this.loadedList.appendChild(el('<p class="al-empty"></p>'));
    const empty = this.loadedList.querySelector('.al-empty');
    if (empty) { setText(empty, t('Nothing loaded yet.')); setHidden(empty as HTMLElement, this.loaded.length > 0); }
    patchList(this.cmdList, this.commands.map((c) => ({ c })), {
      key: (r) => r.c,
      create: (r) => { const n = el<HTMLElement>('<span class="al-chip"></span>'); setText(n, r.c); return n; },
      update: (n, r) => setText(n, r.c),
    });
    patchList(this.startList, STARTUP, {
      key: (s) => s.file,
      create: (s) => {
        const n = el<HTMLElement>('<div class="al-start-row"><span class="al-dot"></span><span class="al-start-name"></span><span class="al-start-note"></span></div>');
        setText(q(n, '.al-start-name'), s.file);
        setText(q(n, '.al-start-note'), t(s.note));
        return n;
      },
      update: (n, s) => {
        const have = !!this.found[s.file];
        setClass(n, 'is-found', have);
        n.title = have ? this.found[s.file] : t('Not in the first support folder');
      },
    });
    this.paintFolders();
  }

  private paintFolders(): void {
    patchList(this.folderList, this.folders.map((p, i) => ({ p, i })), {
      key: (r) => String(r.i),
      create: (r) => {
        const n = el<HTMLElement>(`<div class="al-frow"><input class="cv-input" type="text" spellcheck="false" autocomplete="off" aria-label="Support folder"><button class="cv-icon-btn" type="button" aria-label="Remove folder">${icon('delete', 14)}</button></div>`);
        const input = q<HTMLInputElement>(n, 'input');
        input.addEventListener('input', () => { this.folders[Number(n.dataset.key)] = input.value; this.gate(); });
        q(n, 'button').addEventListener('click', () => { this.folders.splice(Number(n.dataset.key), 1); this.paintFolders(); });
        setValue(input, r.p);
        return n;
      },
      update: (n, r) => setValue(q<HTMLInputElement>(n, 'input'), r.p),
    });
    this.gate();
  }

  private gate(): void {
    const clean = this.folders.map((f) => f.trim()).filter(Boolean);
    setDisabled(this.saveFolders, clean.length === 0 || clean.join('\n') === this.saved.join('\n'));
  }

  private async browse(): Promise<void> {
    const p = await pickPath('open', 'Load Application', '', [LSP], 'Load');
    if (p) { this.path.value = p; void this.go(); }
  }

  private async go(): Promise<void> {
    const id = docStore.activeId;
    const path = this.path.value.trim();
    if (!id || !path) { this.say(t('Enter the name of a LISP file.'), true); return; }
    setDisabled(this.load, true);
    try {
      const r = await auto.appload(id, path);
      this.say(r.commands.length ? `${t('Loaded')} · ${t('commands')}: ${r.commands.join(', ')}` : t('Loaded.'), false);
      await this.pull();
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    } finally {
      setDisabled(this.load, false);
    }
  }

  private async saveSupport(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await auto.setSupport(id, this.folders.map((f) => f.trim()).filter(Boolean));
      this.folders = r.folders;
      this.saved = [...r.folders];
      this.say(t('Support folders saved.'), false);
      await this.pull();
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
  }
}

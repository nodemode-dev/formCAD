import { auto, type ScriptInfo } from '../../io/api-auto';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, q, setClass, setDisabled, setHidden, setStyleVar, setText } from '../dom';
import { pickPath, type FileKind } from '../file-dialogs';
import { t } from '../i18n';
import { watcher, type AutoSnapshot } from './watch';

const SCR: FileKind = { name: 'Script', extensions: ['scr'] };

export class ScriptDialog extends Dialog {
  private readonly path: HTMLInputElement;
  private readonly repeat: HTMLInputElement;
  private readonly times: HTMLInputElement;
  private readonly run: HTMLButtonElement;
  private readonly resume: HTMLButtonElement;
  private readonly stop: HTMLButtonElement;
  private readonly name: HTMLElement;
  private readonly bar: HTMLElement;
  private readonly stat: HTMLElement;
  private readonly msg: HTMLElement;
  private running = false;
  private was = false;
  private stopped = false;

  constructor() {
    super('Run Script', 520);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="sr"><div class="al-load"><input class="cv-input sr-path" type="text" spellcheck="false" autocomplete="off" aria-label="Script file"><button class="cv-btn sr-browse" type="button">Browse...</button></div>' +
      '<div class="sr-opts"><label class="cv-field cv-check"><span>Repeat the script</span><input class="sr-repeat" type="checkbox"></label>' +
      '<label class="cv-field sr-times"><span>Times (empty repeats until stopped)</span><input class="cv-input sr-n" type="number" min="1" step="1"></label></div>' +
      '<div class="sr-prog"><div class="sr-line"><span class="sr-name"></span><span class="sr-stat"></span></div><span class="sr-bar"><i></i></span></div>' +
      '<p class="al-msg sr-msg" role="status"></p></div>'));
    this.path = q<HTMLInputElement>(this.body, '.sr-path');
    this.repeat = q<HTMLInputElement>(this.body, '.sr-repeat');
    this.times = q<HTMLInputElement>(this.body, '.sr-n');
    this.name = q(this.body, '.sr-name');
    this.bar = q(this.body, '.sr-bar');
    this.stat = q(this.body, '.sr-stat');
    this.msg = q(this.body, '.sr-msg');
    this.path.placeholder = t('Path of a .scr file');
    setText(q(this.body, '.sr-browse'), t('Browse...'));
    this.stop = this.button('Stop', 'danger', () => { void this.cancel(); });
    this.resume = this.button('Resume', 'ghost', () => { void this.go(); });
    this.button('Close', 'ghost', () => this.close());
    this.run = this.button('Run', 'primary', () => { void this.start(); });
    q(this.body, '.sr-browse').addEventListener('click', () => { void this.browse(); });
    this.path.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void this.start(); } });
    this.repeat.addEventListener('change', () => this.gate());
    watcher.on((s) => this.show(s));
    this.gate();
    this.show(watcher.snap);
  }

  async showFor(): Promise<void> {
    watcher.start();
    await watcher.pull();
    this.show(watcher.snap);
    if (!this.isOpen) this.open(this.path);
  }

  private gate(): void {
    setDisabled(this.times, !this.repeat.checked);
  }

  private async browse(): Promise<void> {
    const p = await pickPath('open', 'Run Script', '', [SCR], 'Run');
    if (p) { this.path.value = p; void this.start(); }
  }

  private say(text: string, bad = false): void {
    setText(this.msg, text);
    setClass(this.msg, 'is-bad', bad);
  }

  private show(s: AutoSnapshot): void {
    const sc: ScriptInfo | null = s.script;
    setText(this.name, sc ? sc.name : t('No script is running.'));
    const pct = sc && sc.lines > 0 ? Math.round((sc.line / sc.lines) * 100) : 0;
    setStyleVar(this.bar, '--p', `${pct}%`);
    const paused = sc?.state === 'paused';
    setText(this.stat, sc ? `${sc.line} / ${sc.lines}${sc.repeat ? ` · ${t('pass')} ${sc.iteration}` : ''} · ${paused ? t('paused') : t('running')}` : '');
    if (sc?.note) this.say(sc.note, paused);
    else if (this.was && !sc && !this.stopped) this.say(t('Script finished.'), false);
    this.was = !!sc;
    if (sc) this.stopped = false;
    setHidden(this.stop, !sc);
    setHidden(this.resume, !paused);
    setDisabled(this.run, !!sc || this.running);
  }

  private async start(): Promise<void> {
    const id = docStore.activeId;
    const path = this.path.value.trim();
    if (!id) { this.say(t('Open or create a drawing first.'), true); return; }
    if (!path) { this.say(t('Enter the path of a script file.'), true); return; }
    const body: { path: string; repeat?: boolean; times?: number } = { path };
    if (this.repeat.checked) {
      body.repeat = true;
      const n = Number(this.times.value);
      if (Number.isFinite(n) && n >= 1) body.times = Math.floor(n);
    }
    await this.drive(() => auto.runScript(id, body), t('Script finished.'));
  }

  private async go(): Promise<void> {
    const id = docStore.activeId;
    if (id) await this.drive(() => auto.resumeScript(id), t('Script finished.'));
  }

  private async drive(job: () => Promise<unknown>, done: string): Promise<void> {
    this.running = true;
    setDisabled(this.run, true);
    this.say('', false);
    watcher.watching(true);
    try {
      await job();
      await watcher.pull();
      if (!watcher.snap.script) this.say(done, false);
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
      await watcher.pull();
    } finally {
      this.running = false;
      watcher.watching(false);
      this.show(watcher.snap);
    }
  }

  private async cancel(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      this.stopped = true;
      await auto.stopScript(id);
      this.say(t('Script stopped.'), false);
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
    await watcher.pull();
  }
}

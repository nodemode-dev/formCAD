import { auto, type MacroFile } from '../../io/api-auto';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setValue } from '../dom';
import { t } from '../i18n';
import { toast } from '../toast';
import { TrustPrompt } from './trust-prompt';
import { watcher, type AutoSnapshot } from './watch';

let prompt: TrustPrompt | null = null;

export async function playPython(name: string, doc: string): Promise<string> {
  const all = await auto.pyMacros();
  const m = all.macros.find((x) => x.name === name);
  if (!m) throw new Error(`${t('Cannot find')} ${name}.`);
  if (!m.trusted) {
    prompt ??= new TrustPrompt();
    const a = await prompt.ask(m.path, m.changedSinceTrust);
    if (!a) return '';
    await auto.trustMacro(m.path, true, a.grants, a.sha256);
  }
  const r = await auto.runMacro(m.path, doc);
  if (!r.ok) throw new Error((r.stderr || r.stdout || `${t('The macro stopped with exit code')} ${r.exit}`).trim().split('\n').slice(-3).join(' '));
  return (r.stdout || '').trim().split('\n').slice(-1)[0] || t('Macro finished.');
}

export class MacroRecorder extends Dialog {
  private readonly name: HTMLInputElement;
  private readonly format: HTMLSelectElement;
  private readonly state: HTMLElement;
  private readonly steps: HTMLElement;
  private readonly files: HTMLSelectElement;
  private readonly bRecord: HTMLButtonElement;
  private readonly bStop: HTMLButtonElement;
  private readonly bSave: HTMLButtonElement;
  private readonly bPlay: HTMLButtonElement;
  private readonly bLast: HTMLButtonElement;
  private readonly msg: HTMLElement;
  private recorded = false;
  private list: MacroFile[] = [];

  constructor() {
    super('Macro Recorder', 560);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="mr"><div class="mr-state"><i class="mr-dot"></i><span class="mr-text"></span></div>' +
      '<div class="mr-fields"><label class="cv-field"><span>Macro name</span><input class="cv-input mr-name" type="text" spellcheck="false" autocomplete="off"></label>' +
      '<label class="cv-field"><span>Save as</span><select class="cv-input mr-fmt"><option value="scr">Script (.scr)</option><option value="python">Python macro (.py)</option></select></label></div>' +
      '<div class="mr-steps" role="log" aria-label="Recorded steps"></div>' +
      '<div class="mr-btns"><button class="cv-btn mr-rec" type="button">Record</button><button class="cv-btn mr-stop" type="button">Stop</button><button class="cv-btn mr-save" type="button">Save</button></div>' +
      '<div class="mr-play"><select class="cv-input mr-files" aria-label="Saved macros"></select><button class="cv-btn mr-go" type="button">Play</button><button class="cv-btn mr-last" type="button">Play Last</button></div>' +
      '<p class="mr-msg" role="status"></p></div>'));
    this.name = q<HTMLInputElement>(this.body, '.mr-name');
    this.format = q<HTMLSelectElement>(this.body, '.mr-fmt');
    this.state = q(this.body, '.mr-state');
    this.steps = q(this.body, '.mr-steps');
    this.files = q<HTMLSelectElement>(this.body, '.mr-files');
    this.bRecord = q<HTMLButtonElement>(this.body, '.mr-rec');
    this.bStop = q<HTMLButtonElement>(this.body, '.mr-stop');
    this.bSave = q<HTMLButtonElement>(this.body, '.mr-save');
    this.bPlay = q<HTMLButtonElement>(this.body, '.mr-go');
    this.bLast = q<HTMLButtonElement>(this.body, '.mr-last');
    this.msg = q(this.body, '.mr-msg');
    this.name.value = 'macro';
    for (const [sel, text] of [['.mr-rec', 'Record'], ['.mr-stop', 'Stop'], ['.mr-save', 'Save'], ['.mr-go', 'Play'], ['.mr-last', 'Play Last']] as const) setText(q(this.body, sel), t(text));
    for (const [sel, text] of [['.mr-name', 'Macro name'], ['.mr-fmt', 'Save as']] as const) setText(q(this.body, sel).previousElementSibling, t(text));
    this.button('Close', 'primary', () => this.close());
    this.bRecord.addEventListener('click', () => { void this.record(); });
    this.bStop.addEventListener('click', () => { void this.stop(); });
    this.bSave.addEventListener('click', () => { void this.save(); });
    this.bPlay.addEventListener('click', () => { void this.play(this.files.value); });
    this.bLast.addEventListener('click', () => { void this.play('last'); });
    watcher.on((s) => this.show(s));
  }

  async showFor(): Promise<void> {
    watcher.start();
    await Promise.all([watcher.pull(), this.pullFiles()]);
    this.show(watcher.snap);
    if (!this.isOpen) this.open(this.name);
  }

  private async pullFiles(): Promise<void> {
    try {
      this.list = (await auto.macroFiles()).items;
    } catch {
      this.list = [];
    }
    const cur = this.files.value;
    const names = this.list.map((m) => m.name);
    const have = Array.from(this.files.options).map((o) => o.value);
    if (names.join('|') !== have.join('|')) {
      this.files.replaceChildren(...names.map((n) => { const o = document.createElement('option'); o.value = n; o.textContent = n; return o; }));
      if (names.includes(cur)) this.files.value = cur;
    }
    this.gate();
  }

  private say(text: string, bad = false): void {
    setText(this.msg, text);
    setClass(this.msg, 'is-bad', bad);
  }

  private show(s: AutoSnapshot): void {
    setClass(this.state, 'is-rec', s.recording);
    setText(q(this.state, '.mr-text'), s.recording ? `${t('Recording')} ${s.recordName} · ${s.steps} ${t('steps')}` : this.recorded ? t('Recorded. Save it or play it back.') : t('Not recording'));
    this.gate();
    if (this.isOpen || s.recording) void this.lines();
  }

  private gate(): void {
    const rec = watcher.snap.recording;
    setDisabled(this.bRecord, rec || !docStore.activeId);
    setDisabled(this.bStop, !rec);
    setDisabled(this.bSave, rec || !this.recorded);
    setDisabled(this.bPlay, rec || this.files.options.length === 0);
    setDisabled(this.bLast, rec || !this.recorded);
    setHidden(this.files, false);
  }

  private async lines(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const st = await auto.macroStatus(id);
      const rows = st.lines.slice(-200).map((l, i) => ({ l, i: st.lines.length - Math.min(200, st.lines.length) + i }));
      patchList(this.steps, rows, {
        key: (r) => String(r.i),
        create: (r) => { const n = el<HTMLElement>('<div class="mr-step"></div>'); setText(n, r.l); return n; },
        update: (n, r) => setText(n, r.l),
      });
      this.steps.scrollTop = this.steps.scrollHeight;
    } catch {
      return;
    }
  }

  private async record(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      await auto.macroStart(id, this.name.value.trim() || 'macro');
      this.recorded = false;
      this.say('', false);
      await watcher.pull();
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
  }

  private async stop(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await auto.macroStop(id);
      this.recorded = true;
      this.say(`${r.result.steps} ${t('steps recorded.')}`, false);
      await watcher.pull();
      void this.lines();
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
  }

  private async save(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const fmt = this.format.value;
    const base = this.name.value.trim() || 'macro';
    const named = /\.(scr|py)$/i.test(base) ? base : `${base}.${fmt === 'python' ? 'py' : 'scr'}`;
    try {
      const r = await auto.macroSave(id, named, fmt);
      this.say(`${t('Saved')} ${r.result.path}`, false);
      await this.pullFiles();
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
  }

  private async play(file: string): Promise<void> {
    const id = docStore.activeId;
    if (!id || !file) return;
    setDisabled(this.bPlay, true);
    try {
      if (/\.py$/i.test(file)) {
        const out = await playPython(file, id);
        if (out) this.say(out, false);
      } else {
        await auto.macroPlay(id, file);
        this.say(t('Macro played.'), false);
      }
      void docStore.refresh();
    } catch (e) {
      const m = e instanceof Error ? e.message : t('The engine did not answer');
      this.say(m, true);
      toast(m, 'error');
    } finally {
      this.gate();
    }
  }
}

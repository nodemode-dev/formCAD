import { onShellMounted } from '../../app';
import { registerInterceptor } from '../dialogs/intercept';
import { docStore } from '../doc-store';
import { el, setClass, setText } from '../dom';
import { t } from '../i18n';
import { AliasEditor } from './alias-editor';
import { AppLoadDialog } from './appload-dialog';
import { LispConsole } from './lisp-console';
import { MacroRecorder } from './macro-recorder';
import { ScriptDialog } from './script-dialog';
import { watcher, type AutoSnapshot } from './watch';

let lisp: LispConsole | null = null;
let load: AppLoadDialog | null = null;
let script: ScriptDialog | null = null;
let aliases: AliasEditor | null = null;
let recorder: MacroRecorder | null = null;

const openLisp = (): void => { (lisp ??= new LispConsole()).showFor(); };
const openLoad = (): void => { void (load ??= new AppLoadDialog()).showFor(); };
const openScript = (): void => { void (script ??= new ScriptDialog()).showFor(); };
const openAliases = (): void => { void (aliases ??= new AliasEditor()).showFor(); };
const openRecorder = (): void => { void (recorder ??= new MacroRecorder()).showFor(); };

const needDoc = (fn: () => void) => (): boolean => {
  if (!docStore.activeId) return false;
  fn();
  return true;
};

registerInterceptor(['lispconsole', 'vlide', 'lispide'], needDoc(openLisp));
registerInterceptor(['appload', 'ap'], needDoc(openLoad));
registerInterceptor(['script', 'scr', 'rscript'], needDoc(openScript));
registerInterceptor(['aliasedit', 'aliases'], needDoc(openAliases));
registerInterceptor(['macrorecorder', 'macros'], needDoc(openRecorder));

onShellMounted((ctx) => {
  const pill = el<HTMLButtonElement>('<button class="cv-st-auto" type="button" aria-live="polite"><i class="cv-st-auto-dot"></i><span class="cv-st-auto-text"></span></button>');
  const hint = ctx.hosts.status.querySelector('.cv-st-hint');
  ctx.hosts.status.insertBefore(pill, hint);
  let mode: 'rec' | 'run' | '' = '';
  pill.addEventListener('click', () => { if (mode === 'rec') openRecorder(); else if (mode === 'run') openScript(); });
  const paint = (s: AutoSnapshot): void => {
    mode = s.recording ? 'rec' : s.script ? 'run' : '';
    const text = s.recording ? `${t('REC')} ${s.steps}` : s.script ? `${t('Script')} ${s.script.line}/${s.script.lines}` : '';
    setText(pill.querySelector('.cv-st-auto-text'), text);
    setClass(pill, 'is-off', mode === '');
    setClass(pill, 'is-rec', mode === 'rec');
  };
  paint(watcher.snap);
  watcher.on(paint);
  watcher.start();
});

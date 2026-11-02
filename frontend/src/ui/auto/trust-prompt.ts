import { auto, type MacroGrants } from '../../io/api-auto';
import { Dialog } from '../dialogs';
import { el, q, setClass, setDisabled, setText } from '../dom';
import { t } from '../i18n';

export type TrustAnswer = { grants: Partial<MacroGrants>; sha256: string } | null;

export class TrustPrompt extends Dialog {
  private readonly lead: HTMLElement;
  private readonly code: HTMLElement;
  private readonly hash: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly net: HTMLInputElement;
  private readonly sub: HTMLInputElement;
  private readonly nat: HTMLInputElement;
  private readonly files: HTMLInputElement;
  private readonly go: HTMLButtonElement;
  private sha = '';
  private resolve: ((a: TrustAnswer) => void) | null = null;

  constructor() {
    super('Trust This Macro', 640);
    this.body.appendChild(el(
      '<div class="tp"><p class="tp-lead"></p><pre class="tp-code" tabindex="0" aria-label="Macro source"></pre><p class="tp-hash"></p>' +
      '<div class="tp-grants"><label class="cv-field cv-check"><span>Allow network access</span><input class="tp-net" type="checkbox"></label>' +
      '<label class="cv-field cv-check"><span>Allow starting other programs</span><input class="tp-sub" type="checkbox"></label>' +
      '<label class="cv-field cv-check"><span>Allow native code</span><input class="tp-nat" type="checkbox"></label>' +
      '<label class="cv-field"><span>Extra folders it may read (separated by semicolons)</span><input class="cv-input tp-files" type="text" spellcheck="false" autocomplete="off"></label></div>' +
      '<p class="tp-msg" role="alert"></p></div>'));
    this.lead = q(this.body, '.tp-lead');
    this.code = q(this.body, '.tp-code');
    this.hash = q(this.body, '.tp-hash');
    this.msg = q(this.body, '.tp-msg');
    this.net = q<HTMLInputElement>(this.body, '.tp-net');
    this.sub = q<HTMLInputElement>(this.body, '.tp-sub');
    this.nat = q<HTMLInputElement>(this.body, '.tp-nat');
    this.files = q<HTMLInputElement>(this.body, '.tp-files');
    this.button('Cancel', 'ghost', () => this.finish(null));
    this.go = this.button('Trust and Run', 'primary', () => this.finish({ grants: this.grants(), sha256: this.sha }));
    this.onClose = () => this.finish(null);
  }

  private grants(): Partial<MacroGrants> {
    return { network: this.net.checked, subprocess: this.sub.checked, native: this.nat.checked, files: this.files.value.split(';').map((s) => s.trim()).filter(Boolean) };
  }

  async ask(path: string, changed = false): Promise<TrustAnswer> {
    setText(this.msg, '');
    setDisabled(this.go, true);
    let src;
    try {
      src = await auto.pyMacroSource(path);
    } catch (e) {
      setText(this.msg, e instanceof Error ? e.message : t('The engine did not answer'));
      setClass(this.msg, 'is-bad', true);
      return null;
    }
    this.sha = src.sha256;
    this.setTitle(changed || src.changedSinceTrust ? 'Macro Changed' : 'Trust This Macro');
    setText(this.lead, `${src.name}: ${t('This macro runs as you, with limits. Read it before you allow it. It stays trusted only while the file is unchanged.')}`);
    setText(this.code, src.source);
    setText(this.hash, `SHA-256 ${src.sha256}`);
    this.net.checked = !!src.grants.network;
    this.sub.checked = !!src.grants.subprocess;
    this.nat.checked = !!src.grants.native;
    this.files.value = (src.grants.files ?? []).join('; ');
    setDisabled(this.go, false);
    this.open(this.scrim.querySelector<HTMLElement>('.cv-btn-ghost'));
    return new Promise<TrustAnswer>((r) => { this.resolve = r; });
  }

  private finish(a: TrustAnswer): void {
    const r = this.resolve;
    this.resolve = null;
    if (this.isOpen) this.close();
    r?.(a);
  }
}

import { auto, type AutomationStatus, type PluginRow, type PyMacro } from '../../io/api-auto';
import { confirmAction } from '../dialogs';
import { el, patchList, q, setClass, setDisabled, setText } from '../dom';
import { t } from '../i18n';
import { toggleOf } from '../panels/controls';
import { infoRow } from '../panels/pref-rows';
import { toast } from '../toast';
import { TrustPrompt } from './trust-prompt';

let prompt: TrustPrompt | null = null;

const STATE_TEXT: Record<PluginRow['state'], string> = {
  disabled: 'Off',
  enabled: 'On',
  loaded: 'Running',
  mismatch: 'Changed since you enabled it',
  invalid: 'Invalid',
  failed: 'Failed to load',
};

async function copyText(text: string): Promise<void> {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied', 'info');
  } catch {
    toast('The clipboard is not available', 'error');
  }
}

function note(text: string): HTMLElement {
  const n = el('<p class="cv-note"></p>');
  setText(n, t(text));
  return n;
}

function codeBlock(label: string): { el: HTMLElement; set(v: string): void } {
  const root = el('<div class="cv-field ap-code"><span></span><div class="ap-codebox"><pre class="ap-pre" tabindex="0"></pre><button class="cv-btn" type="button">Copy</button></div></div>');
  setText(q(root, 'span'), t(label));
  const pre = q(root, '.ap-pre');
  const btn = q<HTMLButtonElement>(root, 'button');
  setText(btn, t('Copy'));
  btn.addEventListener('click', () => { void copyText(pre.textContent ?? ''); });
  return { el: root, set(v) { setText(pre, v); setDisabled(btn, !v); } };
}

export function pluginRows(register: (sync: () => void) => void): HTMLElement[] {
  const list = el('<div class="ap-list" role="list"></div>');
  const folder = infoRow('Plugin folder');
  const msg = el('<p class="cv-note ap-msg" role="status"></p>');
  const toggle = async (p: PluginRow, on: boolean): Promise<void> => {
    try {
      await auto.enablePlugin(p.id, on, p.manifestSha256 ?? '');
      setText(msg, on ? t('Enabled.') : t('Disabled.'));
      setClass(msg, 'is-bad', false);
    } catch (e) {
      setText(msg, e instanceof Error ? e.message : t('The engine did not answer'));
      setClass(msg, 'is-bad', true);
    }
    void pull();
  };
  const build = (p: PluginRow): HTMLElement => {
    const n = el('<div class="ap-item" role="listitem"><div class="ap-head"><b class="ap-name"></b><span class="ap-state"></span></div><p class="ap-desc"></p><p class="ap-meta"></p></div>');
    const box = el<HTMLInputElement>('<input type="checkbox" aria-label="Enable plugin">');
    q(n, '.ap-head').appendChild(toggleOf(box));
    box.addEventListener('change', () => {
      const row = (n as unknown as { row: PluginRow }).row;
      if (!box.checked) { void toggle(row, false); return; }
      box.checked = false;
      void confirmAction('Enable Plugin', `${t('Plugins run inside the engine, with the same access as FormCAD. Enable only a plugin you trust.')} ${row.name} ${row.version}, SHA-256 ${(row.manifestSha256 ?? '').slice(0, 16)}`, 'Enable', false).then((ok) => { if (ok) void toggle(row, true); });
    });
    return n;
  };
  const paint = (n: HTMLElement, p: PluginRow): void => {
    (n as unknown as { row: PluginRow }).row = p;
    setText(q(n, '.ap-name'), `${p.name} ${p.version}`);
    setText(q(n, '.ap-state'), t(STATE_TEXT[p.state]));
    setClass(q(n, '.ap-state'), 'is-bad', p.state === 'failed' || p.state === 'invalid' || p.state === 'mismatch');
    setText(q(n, '.ap-desc'), p.description);
    const meta = [
      p.commands.length ? `${t('Commands')}: ${p.commands.join(', ')}` : '',
      p.permissions.length ? `${t('Permissions')}: ${p.permissions.join(', ')}` : '',
      p.manifestSha256 ? `SHA-256 ${p.manifestSha256.slice(0, 16)}` : '',
      ...p.problems,
      p.error,
    ].filter(Boolean).join(' · ');
    setText(q(n, '.ap-meta'), meta);
    const box = q<HTMLInputElement>(n, 'input');
    const on = p.enabled;
    if (box.checked !== on) box.checked = on;
    setDisabled(box, p.state === 'invalid');
  };
  const pull = async (): Promise<void> => {
    try {
      const r = await auto.plugins();
      folder.set(r.folder);
      patchList(list, r.plugins, { key: (p) => p.id, create: build, update: paint });
    } catch {
      folder.set(t('Engine offline'));
    }
  };
  register(() => { void pull(); });
  return [folder.el, list, msg, note('Plugins run inside the engine process, so turning one on is a trust decision. A plugin is held back if its files change after you enabled it.')];
}

export function macroRows(register: (sync: () => void) => void): HTMLElement[] {
  const list = el('<div class="ap-list" role="list"></div>');
  const folder = infoRow('Macro folder');
  const msg = el('<p class="cv-note ap-msg" role="status"></p>');
  const say = (text: string, bad: boolean): void => { setText(msg, text); setClass(msg, 'is-bad', bad); };
  const build = (): HTMLElement => {
    const n = el('<div class="ap-item" role="listitem"><div class="ap-head"><b class="ap-name"></b><span class="ap-state"></span><button class="cv-btn ap-rev" type="button">Revoke</button><button class="cv-btn ap-view" type="button">Review</button></div><p class="ap-meta"></p></div>');
    setText(q(n, '.ap-rev'), t('Revoke'));
    setText(q(n, '.ap-view'), t('Review'));
    q(n, '.ap-rev').addEventListener('click', () => {
      const m = (n as unknown as { row: PyMacro }).row;
      auto.trustMacro(m.path, false, {}, m.sha256).then(() => pull()).catch((e) => say(e instanceof Error ? e.message : t('The engine did not answer'), true));
    });
    q(n, '.ap-view').addEventListener('click', () => {
      const m = (n as unknown as { row: PyMacro }).row;
      prompt ??= new TrustPrompt();
      void prompt.ask(m.path, m.changedSinceTrust).then(async (a) => {
        if (!a) return;
        try { await auto.trustMacro(m.path, true, a.grants, a.sha256); await pull(); } catch (e) { say(e instanceof Error ? e.message : t('The engine did not answer'), true); }
      });
    });
    return n;
  };
  const paint = (n: HTMLElement, m: PyMacro): void => {
    (n as unknown as { row: PyMacro }).row = m;
    setText(q(n, '.ap-name'), m.name);
    setText(q(n, '.ap-state'), m.trusted ? t('Trusted') : m.changedSinceTrust ? t('Changed since trusted') : t('Not trusted'));
    setClass(q(n, '.ap-state'), 'is-bad', m.changedSinceTrust);
    setText(q(n, '.ap-meta'), `SHA-256 ${m.sha256.slice(0, 16)}`);
    setDisabled(q<HTMLButtonElement>(n, '.ap-rev'), !m.trusted);
  };
  const pull = async (): Promise<void> => {
    try {
      const r = await auto.pyMacros();
      folder.set(r.folder);
      patchList(list, r.macros, { key: (m) => m.path, create: build, update: paint });
    } catch {
      folder.set(t('Engine offline'));
    }
  };
  register(() => { void pull(); });
  return [folder.el, list, msg, note('A Python macro runs as you, with limits. It stays trusted only while its file is unchanged.')];
}

export function mcpRows(register: (sync: () => void) => void): HTMLElement[] {
  const addr = infoRow('Engine address');
  const tokenFile = infoRow('Token file');
  const header = infoRow('Token header');
  const tools = infoRow('Tools offered');
  const proto = infoRow('Protocols');
  const dev = codeBlock('Add to Claude Code');
  const live = codeBlock('Add and connect to the open window');
  const json = codeBlock('.mcp.json example');
  const apply = (s: AutomationStatus): void => {
    addr.set(s.mcp.httpEndpoint);
    tokenFile.set(s.mcp.tokenFile);
    header.set(s.mcp.tokenHeader);
    tools.set(String(s.mcp.tools));
    proto.set(s.mcp.protocols.join(', '));
    dev.set(s.mcp.headless.addLine);
    live.set(s.mcp.live.addLine);
    json.set(s.mcp.headless.mcpJson);
  };
  register(() => { auto.status().then(apply).catch(() => undefined); });
  return [addr.el, tokenFile.el, header.el, tools.el, proto.el, dev.el, live.el, json.el,
    note('These lines are for you to copy. FormCAD never writes your agent configuration files. The token changes every time the engine starts.')];
}

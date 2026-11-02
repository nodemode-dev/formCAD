import { VERSION } from '../version';
import type { Commands } from './commands';
import { el, patchList, q, setHidden, setText } from './dom';
import { Dialog } from './dialogs';
import { t } from './i18n';

interface RefRow { key: string; text: string; keys: string | null }

let about: Dialog | null = null;
let aboutEngine: HTMLElement | null = null;

export function showAbout(engineVersion: string | null): void {
  if (!about) {
    about = new Dialog('About FormCAD', 420);
    about.body.append(
      el('<p class="cv-about-name">FormCAD <span>by NodeMode</span></p>'),
      el('<p class="cv-note cv-about-line" data-line="app"></p>'),
      el('<p class="cv-note cv-about-line" data-line="engine"></p>'),
      el('<p class="cv-note">Parametric drafting and modeling.</p>'));
    aboutEngine = q(about.body, '[data-line="engine"]');
    setText(q(about.body, '[data-line="app"]'), `${t('Version')} ${VERSION}`);
    about.button('Close', 'primary', () => about?.close());
  }
  if (aboutEngine) {
    setText(aboutEngine, engineVersion ? `${t('Engine')} ${engineVersion}` : t('Engine offline'));
  }
  about.open();
}

let reference: Dialog | null = null;

export function showCommandReference(commands: Commands): void {
  if (!reference) {
    reference = new Dialog('Command Reference', 560);
    reference.body.append(
      el('<input class="cv-input cv-ref-filter" type="search" placeholder="Filter commands" aria-label="Filter commands" spellcheck="false">'),
      el('<div class="cv-ref-list" role="list"></div>'),
      el('<p class="cv-note cv-ref-empty" hidden>No command matches the filter.</p>'));
    reference.button('Close', 'primary', () => reference?.close());
    const filter = q<HTMLInputElement>(reference.body, '.cv-ref-filter');
    filter.addEventListener('input', () => paint(commands));
  }
  q<HTMLInputElement>(reference.body, '.cv-ref-filter').value = '';
  paint(commands);
  reference.open(q(reference.body, '.cv-ref-filter'));
}

function paint(commands: Commands): void {
  if (!reference) return;
  const list = q(reference.body, '.cv-ref-list');
  const needle = q<HTMLInputElement>(reference.body, '.cv-ref-filter').value.trim().toLowerCase();
  const shown = commands.all()
    .filter((c) => commands.label(c) && (!needle || t(commands.label(c)).toLowerCase().includes(needle)))
    .sort((a, b) => (a.group ?? '').localeCompare(b.group ?? '') || commands.label(a).localeCompare(commands.label(b)));
  const rows: RefRow[] = [];
  let group = '\u0000';
  for (const c of shown) {
    const g = c.group ?? 'General';
    if (g !== group) {
      group = g;
      rows.push({ key: `g:${g}`, text: t(g), keys: null });
    }
    rows.push({ key: `c:${c.id}`, text: t(commands.label(c)), keys: commands.keyLabel(c) });
  }
  const paintRow = (node: HTMLElement, r: RefRow): void => {
    if (r.keys === null) { setText(node, r.text); return; }
    setText(q(node, '.cv-ref-label'), r.text);
    setText(q(node, '.cv-ref-keys'), r.keys);
  };
  patchList(list, rows, {
    key: (r) => r.key,
    update: paintRow,
    create: (r) => {
      const node = r.keys === null
        ? el('<div class="cv-ref-group"></div>')
        : el('<div class="cv-ref-row" role="listitem"><span class="cv-ref-label"></span><span class="cv-ref-keys"></span></div>');
      paintRow(node, r);
      return node;
    },
  });
  setHidden(q(reference.body, '.cv-ref-empty'), shown.length > 0);
}

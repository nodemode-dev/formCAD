import { isAssembly } from '../u8/asm';
import { commands } from '../ui/commands';
import { registerDockPanel } from '../ui/dock';
import { storyboardPanel, exportReportLines, runExport, lastExport } from './panel';
import { story } from './store';

registerDockPanel(storyboardPanel());

const reveal = (): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: 'panel:reveal:an1-board' } })); };

commands.add(
  { id: 'an1-panel', label: 'Storyboard', group: 'Window', run: reveal, enabled: isAssembly },
  { id: 'an1-play', label: 'Play Storyboard', group: 'View', run: () => { reveal(); void story.play(); }, enabled: isAssembly },
  { id: 'an1-close', label: 'Close Storyboard Preview', group: 'View', run: () => { story.stop(); story.stage.hide(); story.emit(); }, enabled: isAssembly },
);

if (import.meta.env.DEV) Object.assign(window, { formcadAn1: { story, runExport, exportReportLines, last: () => lastExport } });

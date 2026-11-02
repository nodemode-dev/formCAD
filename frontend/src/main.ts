import { startApp } from './app';
import './ui/shell-part1';
import { startLanguage, startPageTranslator } from './ui/i18n';
import './ui/shell-part2';
import './ui/shell-part3';
import './canvas/mount';
import './ui/draw-rail';
import './ui/dialogs/register';

void startLanguage().finally(() => { startApp(); startPageTranslator(); });

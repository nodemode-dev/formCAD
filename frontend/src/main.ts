import { startApp } from './app';
import './ui/shell-part1';
import { startLanguage, startPageTranslator } from './ui/i18n';
import './ui/shell-part2';
import './ui/shell-part3';
import './canvas/mount';
import './ui/draw-rail';
import './ui/dialogs/register';
import './ui/u3-register';
import './ui/output/register';
import './ui/param/register';
import './ui/auto/register';
import './view3d/mount';

void startLanguage().finally(() => { startApp(); startPageTranslator(); });

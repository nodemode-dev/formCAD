import { startApp } from './app';
import './ui/shell-part1';
import { startLanguage, startPageTranslator } from './ui/i18n';
import './ui/shell-part2';

void startLanguage().finally(() => { startApp(); startPageTranslator(); });

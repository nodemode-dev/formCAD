import { fileURLToPath } from 'node:url';
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync } from 'node:fs';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const outDir = here('.');
const frontend = here('../../frontend');
const appPage = here('../../frontend/index.html');
const nm = `${frontend}/node_modules`;
const SHELL = `${outDir}/shell.html`;

const appShell = () => ({
  name: 'formcad-demo-page',
  enforce: 'pre',
  resolveId(source) {
    return source === 'shell.html' || source === SHELL ? SHELL : null;
  },
  load(id) {
    if (id !== SHELL) return null;
    return readFileSync(appPage, 'utf8')
      .replace('<script type="module" src="/src/main.ts"></script>', '<script type="module" src="./src/main.ts"></script>')
      .replace(/\s*<link rel="(?:icon|apple-touch-icon|preload)"[^>]*>/g, '')
      .replace(/href="\/src\/styles\//g, 'href="../../frontend/src/styles/')
      .replace(/<title>[^<]*<\/title>/, '<title>FormCAD demo: node graph</title>\n  <link rel="icon" href="favicon.png" type="image/png">');
  },
});

const symbol = (cp) => (cp >= 0x2600 && cp <= 0x27bf) || (cp >= 0x1f000 && cp <= 0x1faff);
const unit = (n) => `\\u${n.toString(16).toUpperCase().padStart(4, '0')}`;
const escapeSymbols = () => ({
  name: 'formcad-demo-escape-symbols',
  enforce: 'post',
  generateBundle(_options, bundle) {
    for (const file of Object.values(bundle)) {
      if (file.type !== 'chunk') continue;
      let out = '';
      for (const ch of file.code) {
        const cp = ch.codePointAt(0) ?? 0;
        out += !symbol(cp) ? ch : cp > 0xffff ? unit(0xd800 + ((cp - 0x10000) >> 10)) + unit(0xdc00 + ((cp - 0x10000) & 0x3ff)) : unit(cp);
      }
      file.code = out;
    }
  },
});

const classicScript = () => ({
  name: 'formcad-demo-classic-script',
  enforce: 'post',
  transformIndexHtml(html) {
    const tag = /<script type="module" crossorigin src="([^"]+)"><\/script>\s*/;
    const found = html.match(tag);
    if (!found) return html;
    return html.replace(tag, '').replace('</body>', `<script defer src="${found[1]}"></script>\n</body>`).replace(/ crossorigin(?=[ >])/g, '');
  },
});

const finish = () => ({
  name: 'formcad-demo-finish',
  apply: 'build',
  buildStart() {
    rmSync(`${outDir}/assets`, { recursive: true, force: true });
  },
  writeBundle() {
    if (existsSync(SHELL)) renameSync(SHELL, `${outDir}/index.html`);
    copyFileSync(`${frontend}/public/favicon.png`, `${outDir}/favicon.png`);
    const pictures = `${frontend}/public/demos`;
    if (existsSync(pictures)) {
      mkdirSync(`${outDir}/demos`, { recursive: true });
      for (const name of readdirSync(pictures)) if (/\.(webp|png|jpg)$/.test(name)) copyFileSync(`${pictures}/${name}`, `${outDir}/demos/${name}`);
    }
  },
});

export default {
  root: outDir,
  base: './',
  publicDir: false,
  json: { stringify: true },
  resolve: { alias: { '@fontsource': `${nm}/@fontsource` } },
  plugins: [appShell(), classicScript(), finish(), escapeSymbols()],
  server: { host: false, port: 5393, strictPort: true, fs: { allow: [here('../..')] } },
  preview: { host: false, port: 5493, strictPort: true },
  build: {
    outDir,
    emptyOutDir: false,
    target: 'es2022',
    sourcemap: false,
    cssCodeSplit: false,
    assetsInlineLimit: 0,
    modulePreload: false,
    chunkSizeWarningLimit: 12000,
    rollupOptions: {
      input: SHELL,
      output: {
        format: 'iife',
        inlineDynamicImports: true,
        entryFileNames: 'assets/formcad-demo.js',
        assetFileNames: (info) => (info.names?.some((n) => n.endsWith('.css')) ? 'assets/formcad-demo.css' : 'assets/[name][extname]'),
      },
    },
  },
};

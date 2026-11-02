import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, type Plugin } from 'vite';

const FRONTEND_PORT = 5290;
const BACKEND_PORT = Number(process.env.FORMCAD_BACKEND_PORT) || 8290;

function dataDir(): string {
  const override = process.env.FORMCAD_DATA_DIR;
  if (override) return override;
  if (process.platform === 'darwin') return join(homedir(), 'Library', 'Application Support', 'FormCAD');
  if (process.platform === 'win32') return join(process.env.APPDATA || join(homedir(), 'AppData', 'Roaming'), 'FormCAD');
  return join(process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share'), 'FormCAD');
}

function readToken(): string {
  try {
    return readFileSync(join(dataDir(), 'session.token'), 'utf8').trim();
  } catch {
    return '';
  }
}

const tokenMeta = (): Plugin => ({
  name: 'formcad-token-meta',
  apply: 'serve',
  transformIndexHtml: {
    order: 'pre',
    handler: (html) => {
      const token = readToken();
      return token ? html.replace('</head>', `  <meta name="formcad-token" content="${token}">\n</head>`) : html;
    },
  },
});

const proxy = {
  '/api': {
    target: `http://127.0.0.1:${BACKEND_PORT}`,
    changeOrigin: true,
    ws: true,
    configure: (node: { on: (event: string, fn: (req: { setHeader: (name: string, value: string) => void }) => void) => void }) => {
      const stamp = (req: { setHeader: (name: string, value: string) => void }): void => {
        const token = readToken();
        if (token) req.setHeader('X-FormCAD-Token', token);
      };
      node.on('proxyReq', stamp);
      node.on('proxyReqWs', stamp);
    },
  },
};

export default defineConfig({
  root: '.',
  publicDir: 'public',
  plugins: [tokenMeta()],
  server: {
    port: FRONTEND_PORT,
    host: false,
    strictPort: true,
    proxy,
  },
  preview: {
    port: FRONTEND_PORT + 1,
    host: false,
    strictPort: true,
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    target: 'es2022',
    chunkSizeWarningLimit: 1200,
  },
});

let box: HTMLElement | null = null;
let input: HTMLInputElement | null = null;
let label: HTMLElement | null = null;
let done: ((v: string | null) => void) | null = null;

function build(host: HTMLElement): void {
  if (box && box.parentElement === host) return;
  box = document.createElement('div');
  box.className = 'ec-ask';
  box.hidden = true;
  label = document.createElement('span');
  input = document.createElement('input');
  input.className = 'cv-input';
  input.type = 'text';
  input.spellcheck = false;
  input.autocomplete = 'off';
  box.append(label, input);
  host.appendChild(box);
  input.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); finish(input?.value.trim() ?? ''); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(null); }
  });
  input.addEventListener('blur', () => { if (done && box && !box.hidden) finish(null); });
}

function finish(v: string | null): void {
  const fn = done;
  done = null;
  if (box) box.hidden = true;
  fn?.(v && v.length ? v : null);
}

export function askText(host: HTMLElement, x: number, y: number, text: string, initial = ''): Promise<string | null> {
  build(host);
  if (done) finish(null);
  const b = box as HTMLElement;
  (label as HTMLElement).textContent = text;
  (input as HTMLInputElement).value = initial;
  b.style.setProperty('--ec-ask-x', `${Math.round(x)}px`);
  b.style.setProperty('--ec-ask-y', `${Math.round(y)}px`);
  b.hidden = false;
  return new Promise((resolve) => {
    done = resolve;
    window.setTimeout(() => { (input as HTMLInputElement).focus(); (input as HTMLInputElement).select(); }, 60);
  });
}

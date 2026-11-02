import { el, patchList, setClass, setHidden, setText } from './dom';
import { icon } from './icons';

interface Row { key: string; head?: string; opt?: HTMLOptionElement; hide: boolean }

export function enhanceSelect(select: HTMLSelectElement, opts: { search?: string; onHover?: (value: string | null) => void } = {}): void {
  const btn = el<HTMLButtonElement>(`<button class="cv-dd-btn" type="button" aria-haspopup="listbox"><span class="cv-dd-label"></span>${icon('chevronDown', 12)}</button>`);
  const pop = el(`<div class="cv-dd-pop" role="listbox" hidden>${opts.search ? '<input class="cv-dd-search" type="search">' : ''}<div class="cv-dd-list"></div></div>`);
  const list = pop.querySelector('.cv-dd-list') as HTMLElement;
  const search = pop.querySelector('.cv-dd-search') as HTMLInputElement | null;
  if (search) { search.placeholder = opts.search as string; search.setAttribute('aria-label', opts.search as string); }
  btn.setAttribute('aria-label', select.getAttribute('aria-label') ?? '');
  for (const c of Array.from(select.classList)) if (c !== 'cv-dd-native') btn.classList.add(c);
  new MutationObserver(() => label()).observe(select, { childList: true, subtree: true });
  btn.title = select.title;
  select.classList.add('cv-dd-native');
  select.after(btn);
  const host = document.getElementById('overlay-root');
  if (host) host.appendChild(pop); else document.body.appendChild(pop);
  let picked = 0;
  const label = (): void => { setText(btn.querySelector('.cv-dd-label') as HTMLElement, select.selectedOptions[0]?.textContent ?? ''); btn.disabled = select.disabled; };
  const proto = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value') as PropertyDescriptor;
  Object.defineProperty(select, 'value', { configurable: true, get() { return proto.get?.call(select); }, set(v) { proto.set?.call(select, v); label(); } });
  const disabled = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'disabled') as PropertyDescriptor;
  Object.defineProperty(select, 'disabled', { configurable: true, get() { return disabled.get?.call(select); }, set(v) { disabled.set?.call(select, v); label(); } });
  select.addEventListener('change', label);
  const refs = new WeakMap<HTMLElement, HTMLOptionElement>();
  const visibleItems = (): HTMLElement[] => Array.from(list.querySelectorAll<HTMLElement>('.cv-dd-item:not([hidden])'));
  const mark = (): void => { visibleItems().forEach((i, n) => setClass(i, 'is-picked', n === picked)); };
  const close = (): void => { setHidden(pop, true); btn.setAttribute('aria-expanded', 'false'); opts.onHover?.(null); };
  const fill = (): void => {
    const filter = search?.value.trim().toLowerCase() ?? '';
    const rows: Row[] = [];
    Array.from(select.children).forEach((node, gi) => {
      const group = node instanceof HTMLOptGroupElement ? node : null;
      const options = group ? Array.from(group.children) as HTMLOptionElement[] : [node as HTMLOptionElement];
      const fits = (o: HTMLOptionElement): boolean => !o.hidden && (!filter || (o.textContent ?? '').toLowerCase().includes(filter));
      if (group) rows.push({ key: `g${gi}`, head: group.label, hide: !!filter || !options.some(fits) });
      options.forEach((o, n) => rows.push({ key: `o${gi}.${n}`, opt: o, hide: !fits(o) }));
    });
    const paint = (node: HTMLElement, r: Row): void => {
      setHidden(node, r.hide);
      if (r.opt === undefined) { setText(node, r.head ?? ''); return; }
      refs.set(node, r.opt);
      setText(node.querySelector('span') as HTMLElement, r.opt.textContent ?? '');
      node.dataset.value = r.opt.value;
      const chosen = r.opt.value === select.value;
      setClass(node, 'is-chosen', chosen);
      node.setAttribute('aria-selected', String(chosen));
    };
    patchList(list, rows, {
      key: (r) => r.key,
      update: paint,
      create: (r) => {
        if (r.opt === undefined) { const head = el('<div class="cv-dd-head"></div>'); paint(head, r); return head; }
        const item = el<HTMLButtonElement>(`<button class="cv-dd-item" type="button" role="option"><span></span>${icon('check', 14)}</button>`);
        item.addEventListener('click', () => {
          const o = refs.get(item);
          if (!o) return;
          if (select.value !== o.value) { select.value = o.value; select.dispatchEvent(new Event('change', { bubbles: true })); }
          close();
        });
        item.addEventListener('pointerenter', () => { picked = visibleItems().indexOf(item); mark(); opts.onHover?.(refs.get(item)?.value ?? null); });
        paint(item, r);
        return item;
      },
    });
    const items = visibleItems();
    picked = Math.max(0, items.findIndex((i) => i.classList.contains('is-chosen')));
    if (filter) picked = 0;
    mark();
  };
  const open = (): void => {
    if (search) search.value = '';
    fill();
    setHidden(pop, false);
    btn.setAttribute('aria-expanded', 'true');
    const r = btn.getBoundingClientRect(), h = pop.offsetHeight;
    pop.style.minWidth = `${Math.round(r.width)}px`;
    pop.style.left = `${Math.round(Math.min(r.left, window.innerWidth - pop.offsetWidth - 4))}px`;
    pop.style.top = `${Math.round(r.bottom + 4 + h <= window.innerHeight - 4 ? r.bottom + 4 : Math.max(4, r.top - 4 - h))}px`;
    (search ?? (list.querySelector('.is-chosen') as HTMLElement | null) ?? btn).focus();
    (list.querySelector('.is-chosen') as HTMLElement | null)?.scrollIntoView({ block: 'nearest' });
  };
  btn.addEventListener('click', () => (pop.hidden ? open() : close()));
  search?.addEventListener('input', () => { fill(); opts.onHover?.(null); });
  list.addEventListener('pointerleave', () => opts.onHover?.(null));
  pop.addEventListener('keydown', (e) => {
    const items = visibleItems();
    if (e.key === 'Escape') { e.preventDefault(); close(); btn.focus(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (items.length) { picked = (picked + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length; mark(); items[picked].scrollIntoView({ block: 'nearest' }); opts.onHover?.(items[picked].dataset.value ?? null); }
      return;
    }
    if (e.key === 'Enter') { e.preventDefault(); items[picked]?.click(); }
  });
  document.addEventListener('pointerdown', (e) => { if (!pop.hidden && !pop.contains(e.target as Node) && !btn.contains(e.target as Node)) close(); }, true);
  label();
}

export function enhanceAllSelects(root: ParentNode = document): void {
  const eligible = (s: HTMLSelectElement): boolean => !s.classList.contains('cv-dd-native') && !s.multiple && !s.hasAttribute('size') && !s.hasAttribute('data-native');
  const pick = (n: ParentNode): void => {
    for (const s of Array.from(n.querySelectorAll<HTMLSelectElement>('select'))) if (eligible(s)) enhanceSelect(s);
  };
  pick(root);
  new MutationObserver((records) => {
    for (const r of records) for (const node of Array.from(r.addedNodes)) {
      if (!(node instanceof HTMLElement)) continue;
      if (node instanceof HTMLSelectElement) { if (eligible(node)) enhanceSelect(node); }
      else pick(node);
    }
  }).observe(document.body, { childList: true, subtree: true });
}

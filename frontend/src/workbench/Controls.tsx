import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, ReactNode, RefObject } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import './controls.css';

export type SelectOption = { value: string; label: string; description?: string; disabled?: boolean };
const Chevron = () => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
const Calendar = () => <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="3" y="4.5" width="14" height="13" rx="3" stroke="currentColor" strokeWidth="1.4"/><path d="M6.5 2.5v4M13.5 2.5v4M3 9h14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>;

function usePopover(open: boolean, trigger: RefObject<HTMLButtonElement | null>, panel: RefObject<HTMLDivElement | null>, dismiss: (restoreFocus?: boolean) => void, width: number, height: number) {
  const [position, setPosition] = useState<CSSProperties | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const viewportWidth = document.documentElement.clientWidth;
      const available = viewportWidth - 24;
      const menuWidth = Math.min(available, Math.max(rect.width, width));
      const below = window.innerHeight - rect.bottom - 20;
      const above = rect.top - 20;
      const up = below < Math.min(height, 220) && above > below;
      setPosition({ position: 'fixed', width: menuWidth, left: Math.max(12, Math.min(rect.left, viewportWidth - menuWidth - 12)),
        ...(up ? { bottom: window.innerHeight - rect.top + 8 } : { top: rect.bottom + 8 }),
        maxHeight: Math.max(100, up ? above : below) });
    }
    function outside(event: PointerEvent) {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !panel.current?.contains(target)) dismiss();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); dismiss(true); }
    }
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    document.addEventListener('pointerdown', outside, true);
    document.addEventListener('keydown', escape);
    const owner = trigger.current?.closest('[aria-hidden], .wb-canvas');
    const visibility = new MutationObserver(() => {
      if (owner?.getAttribute('aria-hidden') === 'true' || owner?.hasAttribute('inert')) dismiss();
    });
    if (owner) visibility.observe(owner, { attributes: true, attributeFilter: ['aria-hidden', 'inert'] });
    return () => {
      visibility.disconnect();
      window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true);
      document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', escape);
    };
  }, [open, trigger, panel, dismiss, width, height]);
  return position;
}

export function ChartHelp({ children }: { children: ReactNode }) {
  const id = useId(), [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null), panel = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const close = useCallback((restore = false) => { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); }, []);
  const position = usePopover(open, trigger, panel, close, 320, 240);
  useEffect(() => { if (open && position) panel.current?.focus({ preventScroll: true }); }, [open, !!position]);
  return <span className="wb-chart-help"><button ref={trigger} type="button" aria-haspopup="dialog" aria-expanded={open} aria-controls={id} onClick={() => setOpen(v => !v)}><span aria-hidden="true">?</span>读图帮助</button>{createPortal(<AnimatePresence>{open && position && <motion.div ref={panel} id={id} role="dialog" aria-label="读图帮助" tabIndex={-1} className="wb-popover wb-help-panel" style={position} initial={{ opacity: 0, y: reduced ? 0 : -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : .14 }}><div className="wb-help-heading"><strong>如何查看</strong><button type="button" aria-label="关闭读图帮助" onClick={() => close(true)}>×</button></div>{children}</motion.div>}</AnimatePresence>, document.body)}</span>;
}

export function Select({ label, value, defaultValue, name, options, onChange, searchable = false, searchPlaceholder = '搜索名称或编号', className = '' }: {
  label: string; value?: string | number; defaultValue?: string; name?: string; options: SelectOption[];
  onChange?: (value: string) => void; searchable?: boolean; searchPlaceholder?: string; className?: string;
}) {
  const id = useId();
  const [local, setLocal] = useState(defaultValue ?? options[0]?.value ?? '');
  const selected = String(value ?? local);
  const [open, setOpen] = useState(false), [search, setSearch] = useState(''), [active, setActive] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null), panel = useRef<HTMLDivElement>(null), list = useRef<HTMLDivElement>(null), input = useRef<HTMLInputElement>(null);
  const typeahead = useRef({ text: '', time: 0 });
  const reduced = useReducedMotion();
  const close = useCallback((restore = false) => { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); }, []);
  const position = usePopover(open, trigger, panel, close, searchable ? 292 : 210, 350);
  const filtered = options.filter(option => `${option.label} ${option.description ?? ''}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const current = options.find(option => option.value === selected);
  function show(last = false) {
    setSearch('');
    const index = options.findIndex(option => option.value === selected && !option.disabled);
    setActive(index >= 0 ? index : last ? options.map((option, i) => option.disabled ? -1 : i).filter(i => i >= 0).at(-1) ?? 0 : Math.max(0, options.findIndex(option => !option.disabled)));
    setOpen(true);
  }
  function choose(option: SelectOption | undefined) {
    if (!option || option.disabled) return;
    if (value === undefined) setLocal(option.value);
    onChange?.(option.value); close(true);
  }
  useEffect(() => { if (open && position) (searchable ? input.current : list.current)?.focus({ preventScroll: true }); }, [open, !!position, searchable]);
  useEffect(() => { if (open) document.getElementById(`${id}-option-${active}`)?.scrollIntoView({ block: 'nearest' }); }, [open, active, search, id]);
  function keys(event: KeyboardEvent<HTMLElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === 'Tab') { close(true); return; }
    const enabled = filtered.map((option, i) => option.disabled ? -1 : i).filter(i => i >= 0);
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      if (searchable && event.currentTarget === input.current && ['Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const index = enabled.indexOf(active);
      const next = event.key === 'Home' ? enabled[0] : event.key === 'End' ? enabled.at(-1)
        : enabled[(index + (event.key === 'ArrowDown' ? 1 : -1) + enabled.length) % enabled.length];
      if (next !== undefined) setActive(next);
    } else if (event.key === 'Enter' || event.key === ' ' && !searchable) {
      event.preventDefault(); choose(filtered[active]);
    } else if (!searchable && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      const now = Date.now();
      typeahead.current = { text: (now - typeahead.current.time < 700 ? typeahead.current.text : '') + event.key.toLocaleLowerCase(), time: now };
      const index = filtered.findIndex(option => !option.disabled && `${option.label} ${option.description ?? ''}`.toLocaleLowerCase().startsWith(typeahead.current.text));
      if (index >= 0) setActive(index);
    }
  }
  return <span className={`wb-select ${className}`}>
    {name && <input type="hidden" name={name} value={selected} />}
    <button ref={trigger} type="button" role="combobox" aria-label={label} aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-list`} className="wb-select-trigger" onClick={() => open ? close() : show()} onKeyDown={event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); show(event.key === 'ArrowUp'); }
    }}><span>{current?.label ?? '请选择'}</span><Chevron /></button>
    {createPortal(<AnimatePresence>{open && position && <motion.div ref={panel} key={id} className="wb-popover wb-select-menu" style={position} initial={{ opacity: 0, y: reduced ? 0 : -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reduced ? 0 : -3 }} transition={{ duration: reduced ? 0 : .14 }} inert={!open}>
      {searchable && <div className="wb-select-search"><svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" strokeWidth="1.5"/><path d="m13 13 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg><input ref={input} aria-label={`搜索${label}`} placeholder={searchPlaceholder} value={search} onChange={event => { setSearch(event.target.value); setActive(0); }} onKeyDown={keys} aria-controls={`${id}-list`} aria-activedescendant={filtered[active] ? `${id}-option-${active}` : undefined} autoComplete="off" /></div>}
      <div className="wb-select-menu-heading">{label}{searchable && <span>{filtered.length} 项</span>}</div>
      <div ref={list} id={`${id}-list`} className="wb-select-list" role="listbox" tabIndex={-1} aria-label={label} aria-activedescendant={filtered[active] ? `${id}-option-${active}` : undefined} onKeyDown={keys}>
        {filtered.map((option, index) => <div key={option.value} id={`${id}-option-${index}`} role="option" aria-selected={selected === option.value} aria-disabled={option.disabled || undefined} data-active={index === active} className="wb-select-option" onPointerMove={() => { if (!option.disabled) setActive(index); }} onClick={() => choose(option)}><span className="wb-select-option-copy"><span>{option.label}</span>{option.description && <small>{option.description}</small>}</span><span className="wb-select-check" aria-hidden="true">{selected === option.value ? '✓' : ''}</span></div>)}
        {!filtered.length && <p className="wb-select-empty">没有匹配项，试试名称或编号</p>}
      </div>
    </motion.div>}</AnimatePresence>, document.body)}
  </span>;
}

export function MonthPicker({ label, value, defaultValue = '2025-01', name, min = '2015-01', max = '2025-12', onChange, hint = '选择后立即生效' }: {
  label: string; value?: string; defaultValue?: string; name?: string; min?: string; max?: string; onChange?: (value: string) => void; hint?: string;
}) {
  const [local, setLocal] = useState(defaultValue);
  const selected = value ?? local;
  const [open, setOpen] = useState(false), [year, setYear] = useState(Number(selected.slice(0, 4))), [years, setYears] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null), panel = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const id = useId();
  const minYear = Number(min.slice(0, 4)), maxYear = Number(max.slice(0, 4));
  const close = useCallback((restore = false) => { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); }, []);
  const position = usePopover(open, trigger, panel, close, 292, 290);
  function show() { setYear(Math.min(maxYear, Math.max(minYear, Number(selected.slice(0, 4))))); setYears(false); setOpen(true); }
  useEffect(() => {
    if (open && position) (panel.current?.querySelector('.wb-calendar-grid [aria-pressed="true"]:not(:disabled)') ?? panel.current?.querySelector('.wb-calendar-grid button:not(:disabled)'))?.scrollIntoView({ block: 'nearest' });
  }, [open, !!position, year, years]);
  useEffect(() => {
    if (open && position) (panel.current?.querySelector<HTMLElement>('.wb-calendar-grid [aria-pressed="true"]:not(:disabled)') ?? panel.current?.querySelector<HTMLElement>('.wb-calendar-grid button:not(:disabled)'))?.focus({ preventScroll: true });
  }, [open, !!position, years]);
  function choose(month: string) { if (value === undefined) setLocal(month); onChange?.(month); close(true); }
  function keys(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Tab') { close(true); return; }
    const delta = ({ ArrowRight: 1, ArrowLeft: -1, ArrowDown: years ? 3 : 4, ArrowUp: years ? -3 : -4 } as Record<string, number>)[event.key];
    if (delta === undefined && !['Home', 'End'].includes(event.key)) return;
    const controls = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('.wb-calendar-grid button')];
    const at = controls.indexOf(event.target as HTMLButtonElement);
    if (at < 0) return;
    event.preventDefault();
    let next = event.key === 'Home' ? 0 : event.key === 'End' ? controls.length - 1 : Math.max(0, Math.min(controls.length - 1, at + delta));
    const direction = event.key === 'End' || delta < 0 ? -1 : 1;
    while (controls[next]?.disabled) next += direction;
    controls[next]?.focus();
  }
  return <span className="wb-month-picker">{name && <input type="hidden" name={name} value={selected} />}
    <button ref={trigger} type="button" className="wb-month-trigger" aria-label={label} aria-haspopup="dialog" aria-expanded={open} aria-controls={id} onClick={() => open ? close() : show()}><Calendar /><span>{selected.slice(0, 4)}年{Number(selected.slice(5, 7))}月</span><Chevron /></button>
    {createPortal(<AnimatePresence>{open && position && <motion.div ref={panel} key={id} id={id} className="wb-popover wb-calendar" role="dialog" aria-label={`${label}选择`} style={position} initial={{ opacity: 0, y: reduced ? 0 : -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reduced ? 0 : -3 }} transition={{ duration: reduced ? 0 : .14 }} onKeyDown={keys} inert={!open}>
      <div className="wb-calendar-caption">{label}</div><div className="wb-calendar-heading"><button type="button" aria-label={`${label}上一年`} disabled={year <= minYear || years} onClick={() => setYear(y => y - 1)}>‹</button><button type="button" className="wb-calendar-year" aria-label={`${label}选择年份`} aria-expanded={years} onClick={() => setYears(v => !v)}>{years ? `${minYear}—${maxYear}` : `${year} 年`}<Chevron /></button><button type="button" aria-label={`${label}下一年`} disabled={year >= maxYear || years} onClick={() => setYear(y => y + 1)}>›</button></div>
      <div className={`wb-calendar-grid${years ? ' is-years' : ''}`}>{years ? Array.from({ length: maxYear - minYear + 1 }, (_, i) => minYear + i).map(y => <button key={y} type="button" aria-pressed={y === year} onClick={() => { setYear(y); setYears(false); }}>{y}</button>) : Array.from({ length: 12 }, (_, i) => `${year}-${String(i + 1).padStart(2, '0')}`).map((month, i) => <button key={month} type="button" aria-label={`${year}年${i + 1}月`} disabled={month < min || month > max} aria-pressed={month === selected} onClick={() => choose(month)}>{i + 1}月</button>)}</div>
      <p className="wb-calendar-hint">{hint}</p>
    </motion.div>}</AnimatePresence>, document.body)}
  </span>;
}

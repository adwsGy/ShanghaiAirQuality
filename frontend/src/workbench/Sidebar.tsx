import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { motion, useReducedMotion } from 'motion/react';

export function Sidebar({ open, modal, close, children }: {
  open: boolean; modal: boolean; close: () => void; children: ReactNode;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (!open || !modal) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButton.current?.focus({ preventScroll: true });
    return () => { document.body.style.overflow = previous; };
  }, [open, modal]);
  return <div className="wb-sidebar-slot" data-open={open}>
    {modal && <motion.div className="wb-settings-backdrop" aria-hidden="true"
      inert={!open} onClick={close} initial={false}
      animate={{ opacity: open ? 1 : 0 }} transition={{ duration: reduced ? 0 : .2 }} />}
    <motion.aside id="wb-settings" className="wb-sidebar" data-open={open}
      role={modal ? 'dialog' : 'complementary'} aria-modal={modal && open ? true : undefined}
      aria-label="分析设置" aria-hidden={!open} inert={!open} initial={false}
      animate={{ x: open || reduced ? 0 : modal ? -40 : -16, opacity: open ? 1 : 0 }}
      transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 360, damping: 36, mass: .85, opacity: { duration: .18 } }}
      onKeyDown={event => {
        if ((event.target as HTMLElement).closest('.wb-popover')) return;
        if (event.key === 'Escape') { event.preventDefault(); close(); }
        if (modal && event.key === 'Tab') {
          const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button, input, select, summary, [tabindex="0"]')]
            .filter(el => !el.hasAttribute('disabled') && el.checkVisibility() && !el.closest('[inert]'));
          const first = controls[0], last = controls.at(-1);
          if (event.shiftKey && document.activeElement === first && last) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last && first) { event.preventDefault(); first.focus(); }
        }
      }}>
      <div className="wb-sidebar-heading"><h2>分析设置</h2><button ref={closeButton} type="button" aria-label="收起分析设置" onClick={close}>
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m12 5-5 5 5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button></div>
      <div className="wb-sidebar-body">{children}</div>
    </motion.aside>
  </div>;
}

export function TaskIcon({ task }: { task: string }) {
  return <svg width="19" height="19" viewBox="0 0 20 20" fill="none" aria-hidden="true" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    {task === 'trend' ? <><path d="M3 3v14h14" /><path d="m5 12 4-4 3 2 5-6" /></>
      : task === 'compare' ? <><path d="M4 5h12m-3-3 3 3-3 3M16 15H4m3-3-3 3 3 3" /><path d="M5 9v2m10-2v2" /></>
      : task === 'season' ? <><rect x="3" y="3" width="14" height="14" rx="2" /><path d="M3 8h14M3 12h14M8 3v14m4-14v14" /></>
      : <><path d="M6 16c-2 0-3-1.5-3-3.5S5 8 7 6m7 10c2 0 3-1.5 3-3.5S15 8 13 6" /><circle cx="10" cy="5" r="2" /><circle cx="6" cy="15" r="2" /><circle cx="14" cy="15" r="2" /><path d="m9 7-2 6m4-6 2 6" /></>}
  </svg>;
}

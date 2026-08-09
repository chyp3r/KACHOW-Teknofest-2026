import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { IconButton } from "./Button";
import { OverlayBackdrop } from "./Surface";

const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

function useOverlayFocus(
  open: boolean,
  containerRef: RefObject<HTMLElement | null>,
  initialFocusRef: RefObject<HTMLElement | null>,
  returnFocusRef: RefObject<HTMLElement | null> | undefined,
  onClose: () => void,
) {
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const returnTarget = returnFocusRef?.current ?? document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    initialFocusRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(containerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
      if (focusable.length === 0) { event.preventDefault(); containerRef.current?.focus(); return; }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      returnTarget?.focus();
    };
  }, [containerRef, initialFocusRef, onClose, open, returnFocusRef]);
}

export function Dialog({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  role = "dialog",
}: {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  role?: "dialog" | "alertdialog";
}) {
  const titleId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useOverlayFocus(open, containerRef, closeRef, undefined, onClose);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <div ref={containerRef} className="dialog" role={role} aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onMouseDown={(event) => event.stopPropagation()}>
        <header className="dialog-header"><div><h2 id={titleId}>{title}</h2>{description && <p>{description}</p>}</div><IconButton ref={closeRef} icon={<X />} aria-label="İletişim kutusunu kapat" onClick={onClose} /></header>
        {children && <div className="dialog-body">{children}</div>}
        {footer && <footer className="dialog-actions">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({
  open,
  id,
  title,
  children,
  footer,
  onClose,
  returnFocusRef,
  className = "",
  backdropClassName = "",
  headerClassName = "",
  bodyClassName = "",
  closeLabel = "Çekmeceyi kapat",
}: {
  open: boolean;
  id?: string;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
  className?: string;
  backdropClassName?: string;
  headerClassName?: string;
  bodyClassName?: string;
  closeLabel?: string;
}) {
  const titleId = useId();
  const containerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useOverlayFocus(open, containerRef, closeRef, returnFocusRef, onClose);
  if (!open) return null;
  return (
    <>
      <OverlayBackdrop className={backdropClassName} aria-label={closeLabel} onClick={onClose} />
      <aside ref={containerRef} id={id} className={`drawer ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className={headerClassName}><h2 id={titleId}>{title}</h2><IconButton ref={closeRef} icon={<X />} aria-label={closeLabel} onClick={onClose} /></header>
        <div className={bodyClassName}>{children}</div>
        {footer && <footer>{footer}</footer>}
      </aside>
    </>
  );
}

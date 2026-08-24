import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

export function Accordion({
  title,
  description,
  children,
  defaultOpen = false,
  trailing,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  trailing?: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();

  return (
    <section className={`accordion ${open ? "is-open" : ""} ${className}`.trim()}>
      <div className="accordion-heading">
        <button
          type="button"
          className="accordion-trigger"
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((current) => !current)}
        >
          <span className="accordion-trigger-copy">
            <strong>{title}</strong>
            {description && <small>{description}</small>}
          </span>
          <ChevronDown className="accordion-trigger-chevron" aria-hidden="true" />
        </button>
        {trailing && <div className="accordion-trailing">{trailing}</div>}
      </div>
      <div id={contentId} className="accordion-content" hidden={!open}>
        {children}
      </div>
    </section>
  );
}

import {
  Children,
  forwardRef,
  isValidElement,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "lucide-react";
import type { ControlSize } from "./Button";

export function FormField({
  label,
  htmlFor,
  description,
  helperText,
  error,
  required,
  counter,
  className = "",
  labelId,
  children,
}: {
  label: ReactNode;
  htmlFor: string;
  description?: ReactNode;
  helperText?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  counter?: ReactNode;
  className?: string;
  labelId?: string;
  children: ReactNode;
}) {
  return (
    <div className={`form-field ${error ? "form-field-error" : ""} ${className}`.trim()}>
      <div className="form-field-label-row">
        <label id={labelId} htmlFor={htmlFor}>{label}</label>
        {required && <span className="required-mark" aria-hidden="true">Gerekli</span>}
        {counter && <span className="field-counter">{counter}</span>}
      </div>
      {description && <p id={`${htmlFor}-description`} className="field-description">{description}</p>}
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} className="field-error" role="alert">{error}</p>
      ) : helperText ? (
        <p id={`${htmlFor}-helper`} className="field-helper">{helperText}</p>
      ) : null}
    </div>
  );
}

interface FieldProps {
  label?: ReactNode;
  description?: ReactNode;
  helperText?: ReactNode;
  error?: ReactNode;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  trailingAction?: ReactNode;
  controlSize?: ControlSize;
  fieldClassName?: string;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldProps>(function Input(
  { label, description, helperText, error, leadingIcon, trailingIcon, trailingAction, controlSize = "md", fieldClassName, id: providedId, required, className = "", ...props },
  ref,
) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  const describedBy = error ? `${id}-error` : helperText ? `${id}-helper` : description ? `${id}-description` : undefined;
  const control = (
    <span className={`field-control ${leadingIcon ? "has-leading-icon" : ""} ${trailingIcon || trailingAction ? "has-trailing-icon" : ""}`.trim()}>
      {leadingIcon && <span className="field-icon field-icon-leading" aria-hidden="true">{leadingIcon}</span>}
      <input ref={ref} id={id} required={required} aria-invalid={Boolean(error)} aria-describedby={describedBy} className={`input control-${controlSize} ${className}`.trim()} {...props} />
      {trailingIcon && <span className="field-icon field-icon-trailing" aria-hidden="true">{trailingIcon}</span>}
      {trailingAction && <span className="field-action field-action-trailing">{trailingAction}</span>}
    </span>
  );
  if (!label) return control;
  return <FormField label={label} htmlFor={id} description={description} helperText={helperText} error={error} required={required} className={fieldClassName}>{control}</FormField>;
});

export interface DropdownOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
}

interface DropdownProps extends Omit<FieldProps, "leadingIcon" | "trailingIcon"> {
  id?: string;
  className?: string;
  value: string;
  options?: readonly DropdownOption[];
  children?: ReactNode;
  onChange: (event: ChangeEvent<HTMLSelectElement>) => void;
  disabled?: boolean;
  placement?: "bottom" | "top";
  required?: boolean;
  name?: string;
  "aria-label"?: string;
}

function optionsFromChildren(children: ReactNode): DropdownOption[] {
  return Children.toArray(children).flatMap((child) => {
    if (!isValidElement<{ value?: string; disabled?: boolean; children?: ReactNode }>(child)) return [];
    return [{ value: child.props.value ?? "", label: child.props.children, disabled: child.props.disabled }];
  });
}

export const Dropdown = forwardRef<HTMLButtonElement, DropdownProps>(function Dropdown(
  { label, description, helperText, error, controlSize = "md", fieldClassName, id: providedId, required, className = "", value, options: providedOptions, children, onChange, disabled = false, placement = "bottom", name, "aria-label": ariaLabel },
  ref,
) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  const labelId = `${id}-label`;
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number; width: number } | null>(null);
  const options = providedOptions ?? optionsFromChildren(children);
  const selected = options.find((option) => option.value === value);
  const describedBy = error ? `${id}-error` : helperText ? `${id}-helper` : description ? `${id}-description` : undefined;

  useEffect(() => {
    const closeWhenClickingOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeWhenClickingOutside);
    return () => document.removeEventListener("mousedown", closeWhenClickingOutside);
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    const updateMenuPosition = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const width = Math.min(rect.width, window.innerWidth - 16);
      const left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
      if (placement === "top") {
        setMenuPosition({
          top: Math.max(8, rect.top - Math.min(240, options.length * 40 + 8) - 4),
          left,
          width,
        });
        return;
      }
      setMenuPosition({ top: rect.bottom + 4, left, width });
    };
    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
    };
  }, [open, options.length, placement]);

  const selectOption = (option: DropdownOption) => {
    if (option.disabled) return;
    onChange({ target: { value: option.value } } as ChangeEvent<HTMLSelectElement>);
    setOpen(false);
    triggerRef.current?.focus();
  };
  const moveFocus = (direction: 1 | -1) => {
    const enabledOptions = options.filter((option) => !option.disabled);
    if (!enabledOptions.length) return;
    const index = enabledOptions.findIndex((option) => option.value === value);
    selectOption(enabledOptions[(index + direction + enabledOptions.length) % enabledOptions.length]);
  };
  const control = (
    <div ref={rootRef} className={`dropdown control-${controlSize} ${open ? "is-open" : ""} ${className}`.trim()}>
      {name && <input type="hidden" name={name} value={value} required={required} />}
      <button
        ref={(element) => { triggerRef.current = element; if (typeof ref === "function") ref(element); }}
        id={id}
        type="button"
        className="dropdown-trigger"
        disabled={disabled}
        role="combobox"
        aria-label={ariaLabel}
        aria-labelledby={label ? labelId : undefined}
        aria-describedby={describedBy}
        aria-invalid={Boolean(error)}
        aria-valuetext={typeof selected?.label === "string" ? selected.label : undefined}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "Escape") { setOpen(false); return; }
          if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); if (open) moveFocus(event.key === "ArrowDown" ? 1 : -1); else setOpen(true); }
        }}
      >
        <span className="dropdown-value">{selected?.label}</span>
        <ChevronDown className="dropdown-indicator" aria-hidden="true" />
      </button>
      {open && menuPosition && createPortal(
        <ul className="dropdown-menu" role="listbox" aria-labelledby={label ? labelId : undefined} aria-label={ariaLabel} style={menuPosition}>
          {options.map((option) => (
            <li key={option.value} role="presentation">
              <button type="button" role="option" aria-selected={option.value === value} disabled={option.disabled} onClick={() => selectOption(option)}>{option.label}</button>
            </li>
          ))}
        </ul>,
        document.body,
      )}
    </div>
  );
  if (!label) return control;
  return <FormField label={label} labelId={labelId} htmlFor={id} description={description} helperText={helperText} error={error} required={required} className={fieldClassName}>{control}</FormField>;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & Omit<FieldProps, "leadingIcon" | "trailingIcon"> & { counter?: ReactNode; resize?: "none" | "vertical" | "both" }>(function Textarea(
  { label, description, helperText, error, controlSize = "md", fieldClassName, counter, resize = "vertical", id: providedId, required, className = "", ...props },
  ref,
) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  const describedBy = error ? `${id}-error` : helperText ? `${id}-helper` : description ? `${id}-description` : undefined;
  const control = <textarea ref={ref} id={id} required={required} aria-invalid={Boolean(error)} aria-describedby={describedBy} className={`textarea control-${controlSize} resize-${resize} ${className}`.trim()} {...props} />;
  if (!label) return control;
  return <FormField label={label} htmlFor={id} description={description} helperText={helperText} error={error} required={required} counter={counter} className={fieldClassName}>{control}</FormField>;
});

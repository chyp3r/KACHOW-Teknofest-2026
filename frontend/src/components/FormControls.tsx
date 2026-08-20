import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
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
  children: ReactNode;
}) {
  return (
    <div className={`form-field ${error ? "form-field-error" : ""} ${className}`.trim()}>
      <div className="form-field-label-row">
        <label htmlFor={htmlFor}>{label}</label>
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

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & Omit<FieldProps, "leadingIcon" | "trailingIcon">>(function Select(
  { label, description, helperText, error, controlSize = "md", fieldClassName, id: providedId, required, className = "", children, ...props },
  ref,
) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  const describedBy = error ? `${id}-error` : helperText ? `${id}-helper` : description ? `${id}-description` : undefined;
  const control = <select ref={ref} id={id} required={required} aria-invalid={Boolean(error)} aria-describedby={describedBy} className={`select control-${controlSize} ${className}`.trim()} {...props}>{children}</select>;
  if (!label) return control;
  return <FormField label={label} htmlFor={id} description={description} helperText={helperText} error={error} required={required} className={fieldClassName}>{control}</FormField>;
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

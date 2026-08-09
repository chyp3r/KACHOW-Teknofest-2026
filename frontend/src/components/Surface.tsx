import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import type { ButtonHTMLAttributes } from "react";

export type CardVariant = "default" | "interactive" | "selected" | "subtle" | "warning" | "error";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement> & { variant?: CardVariant; padding?: "compact" | "default" | "prominent" }>(function Card(
  { variant = "default", padding = "default", className = "", ...props },
  ref,
) {
  return <div ref={ref} className={`card card-${variant} card-padding-${padding} ${className}`.trim()} {...props} />;
});

export function CardHeader({ className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return <header className={`card-header ${className}`.trim()} {...props} />;
}

export function CardContent({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`card-content ${className}`.trim()} {...props} />;
}

export function CardFooter({ className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return <footer className={`card-footer ${className}`.trim()} {...props} />;
}

export function Alert({
  variant = "info",
  icon,
  title,
  children,
  action,
  className = "",
}: {
  variant?: "info" | "success" | "warning" | "error";
  icon?: ReactNode;
  title?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`alert alert-${variant} ${className}`.trim()} role={variant === "error" ? "alert" : "status"}>
      {icon && <span className="alert-icon" aria-hidden="true">{icon}</span>}
      <div className="alert-content">{title && <strong>{title}</strong>}<div>{children}</div></div>
      {action && <div className="alert-action">{action}</div>}
    </div>
  );
}

export function Divider({ orientation = "horizontal", className = "" }: { orientation?: "horizontal" | "vertical"; className?: string }) {
  return <div className={`divider divider-${orientation} ${className}`.trim()} role="separator" aria-orientation={orientation} />;
}

export function Skeleton({ className = "", lines = 1 }: { className?: string; lines?: number }) {
  return <div className={`skeleton ${className}`.trim()} aria-hidden="true">{Array.from({ length: lines }, (_, index) => <span key={index} />)}</div>;
}

export function Spinner({ size = "md", label = "Yükleniyor" }: { size?: "xs" | "sm" | "md" | "lg"; label?: string }) {
  return <span className={`spinner spinner-${size}`} role="status"><span className="sr-only">{label}</span></span>;
}

export function OverlayBackdrop({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { "aria-label": string }) {
  return <button type="button" className={`overlay-backdrop ${className}`.trim()} {...props} />;
}

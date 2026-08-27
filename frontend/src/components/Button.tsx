import { Loader2 } from "lucide-react";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "destructive";
export type ControlSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ControlSize;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  loading?: boolean;
  fullWidth?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    leadingIcon,
    trailingIcon,
    loading = false,
    fullWidth = false,
    disabled,
    className = "",
    children,
    type = "button",
    ...props
  },
  ref,
) {
  const classes = [
    "button",
    `button-${variant}`,
    `control-${size}`,
    fullWidth ? "button-full" : "",
    loading ? "is-loading" : "",
    className,
  ].filter(Boolean).join(" ");

  return (
    <button
      ref={ref}
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Loader2 className="spinner" aria-hidden="true" /> : leadingIcon ? <span className="button-icon" aria-hidden="true">{leadingIcon}</span> : null}
      {/* İçerik yoksa (ör. yükleniyorken IconButton) boş bir label span'i
          bırakma -- grid'de spinner'ı ikinci satıra iterek ortadan kaydırıyor. */}
      {children != null && children !== false && (
        <span className="button-label">{children}</span>
      )}
      {!loading && trailingIcon ? <span className="button-icon" aria-hidden="true">{trailingIcon}</span> : null}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonProps, "children" | "leadingIcon" | "trailingIcon" | "fullWidth"> {
  "aria-label": string;
  icon: ReactNode;
  tooltip?: string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, tooltip, className = "", variant = "ghost", size = "md", loading = false, ...props },
  ref,
) {
  return (
    <Button
      ref={ref}
      variant={variant}
      size={size}
      loading={loading}
      className={`icon-button ${className}`.trim()}
      title={tooltip}
      {...props}
    >
      {/* Yükleniyorken yalnızca spinner görünür -- ikon yanında ayrıca
          çizilip düğmeyi sıkıştırmaz. */}
      {!loading && (
        <span className="icon-button-glyph" aria-hidden="true">
          {icon}
        </span>
      )}
    </Button>
  );
});

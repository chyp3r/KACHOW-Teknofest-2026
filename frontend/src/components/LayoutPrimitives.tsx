import type { CSSProperties, HTMLAttributes, ReactNode } from "react";

type Gap = 1 | 2 | 3 | 4 | 6 | 8;
const gapStyle = (gap: Gap): CSSProperties => ({ "--layout-gap": `var(--space-${gap})` } as CSSProperties);

export function Stack({ gap = 4, className = "", style, ...props }: HTMLAttributes<HTMLDivElement> & { gap?: Gap }) {
  return <div className={`stack ${className}`.trim()} style={{ ...gapStyle(gap), ...style }} {...props} />;
}

export function Inline({ gap = 2, align = "center", justify = "start", wrap = false, className = "", style, ...props }: HTMLAttributes<HTMLDivElement> & { gap?: Gap; align?: "start" | "center" | "end" | "stretch"; justify?: "start" | "center" | "end" | "between"; wrap?: boolean }) {
  return <div className={`inline align-${align} justify-${justify} ${wrap ? "wrap" : ""} ${className}`.trim()} style={{ ...gapStyle(gap), ...style }} {...props} />;
}

export function Cluster(props: HTMLAttributes<HTMLDivElement> & { gap?: Gap }) {
  return <Inline wrap {...props} />;
}

export function Grid({ gap = 4, min = "16rem", className = "", style, ...props }: HTMLAttributes<HTMLDivElement> & { gap?: Gap; min?: string }) {
  const layoutStyle = { ...gapStyle(gap), "--grid-min": min, ...style } as CSSProperties;
  return <div className={`grid ${className}`.trim()} style={layoutStyle} {...props} />;
}

export function FormActions({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`form-actions ${className}`.trim()}>{children}</div>;
}

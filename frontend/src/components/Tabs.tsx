import type { ReactNode } from "react";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  icon?: ReactNode;
}

export function Tabs<T extends string>({
  items,
  active,
  label,
  onChange,
}: {
  items: TabItem<T>[];
  active: T;
  label: string;
  onChange: (tab: T) => void;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={active === item.id}
          className={active === item.id ? "is-active" : ""}
          onClick={() => onChange(item.id)}
        >
          {item.icon && <span aria-hidden="true">{item.icon}</span>}
          {item.label}
        </button>
      ))}
    </div>
  );
}

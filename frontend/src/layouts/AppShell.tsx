import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  FileText,
  ChevronDown,
  LogIn,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  ShieldCheck,
  Sun,
  X,
  FilePenLine,
  Monitor,
} from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import type { ThemeMode } from "../contexts/ThemeContext";
import type { AppRoute } from "../hooks/useAppRoute";

interface AppShellProps {
  route: AppRoute;
  navigate: (route: AppRoute) => void;
  children: ReactNode;
  aside?: ReactNode;
  documentLibrary?: ReactNode;
  documentLibraryOpen?: boolean;
  onToggleDocumentLibrary?: () => void;
}

const NAV_ITEMS: Array<{
  route: AppRoute;
  label: string;
  icon: typeof MessageSquare;
  admin?: boolean;
}> = [
  { route: "/admin", label: "Yönetim Paneli", icon: ShieldCheck, admin: true },
  { route: "/chats", label: "Sohbetler", icon: MessageSquare },
  { route: "/drafts", label: "Taslaklar", icon: FilePenLine },
  { route: "/documents", label: "Evrak Kütüphanesi", icon: FileText },
];

const THEME_ICONS: Record<ThemeMode, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export function AppShell({
  route,
  navigate,
  children,
  aside,
  documentLibrary,
  documentLibraryOpen = false,
  onToggleDocumentLibrary,
}: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const ThemeIcon = THEME_ICONS[mode];
  useEffect(() => setMobileOpen(false), [route]);
  const go = (next: AppRoute) => {
    navigate(next);
    setMobileOpen(false);
  };

  return (
    <div className={`app-shell ${aside ? "with-aside" : ""}`}>
      <button
        className="mobile-menu-button icon-button"
        aria-label="Menüyü aç"
        onClick={() => setMobileOpen(true)}
      >
        <Menu size={20} />
      </button>
      {mobileOpen && (
        <button
          className="sidebar-backdrop"
          aria-label="Menüyü kapat"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={`app-sidebar ${mobileOpen ? "is-open" : ""}`}
        aria-label="Ana menü"
      >
        <div className="brand">
          <span className="brand-mark">
            <Activity size={21} />
          </span>
          <div>
            <strong>KACHOW</strong>
            <small>Karar Destek Sistemi</small>
          </div>
          <button
            className="sidebar-close icon-button"
            aria-label="Menüyü kapat"
            onClick={() => setMobileOpen(false)}
          >
            <X size={18} />
          </button>
        </div>
        <nav className="sidebar-nav">
          <span className="nav-caption">Çalışma Alanı</span>
          {NAV_ITEMS.filter(
            (item) => !item.admin || user?.role === "admin",
          ).map(({ route: itemRoute, label, icon: Icon }) => {
            if (itemRoute === "/documents") {
              return (
                <div className="nav-library-section" key={itemRoute}>
                  <button
                    type="button"
                    className={`nav-item ${
                      route === itemRoute || documentLibraryOpen ? "active" : ""
                    }`}
                    aria-expanded={documentLibraryOpen}
                    aria-controls="document-library-panel"
                    onClick={onToggleDocumentLibrary}
                  >
                    <Icon size={18} />
                    <span>{label}</span>
                    <ChevronDown
                      className="nav-chevron"
                      size={15}
                      aria-hidden="true"
                    />
                  </button>
                  {documentLibraryOpen && documentLibrary}
                </div>
              );
            }

            return (
              <a
                key={itemRoute}
                href={itemRoute}
                className={`nav-item ${route === itemRoute ? "active" : ""}`}
                aria-current={route === itemRoute ? "page" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  go(itemRoute);
                }}
              >
                <Icon size={18} />
                <span>{label}</span>
              </a>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <label className="theme-control">
            <span>
              <ThemeIcon size={17} />
              Tema
            </span>
            <select
              aria-label="Tema seçimi"
              value={mode}
              onChange={(event) => setMode(event.target.value as ThemeMode)}
            >
              <option value="system">Sistem</option>
              <option value="light">Açık</option>
              <option value="dark">Koyu</option>
            </select>
          </label>
          {user ? (
            <div className="user-card">
              <span className="avatar">
                {user.username.slice(0, 2).toLocaleUpperCase("tr-TR")}
              </span>
              <div>
                <strong>{user.username}</strong>
                <small>{user.role === "admin" ? "Yönetici" : user.role}</small>
              </div>
              <button
                className="icon-button"
                aria-label="Oturumu kapat"
                title="Oturumu kapat"
                onClick={() => void logout()}
              >
                <LogOut size={17} />
              </button>
            </div>
          ) : (
            <button className="login-link" onClick={() => go("/login")}>
              <LogIn size={17} />
              Yönetici oturumu aç
            </button>
          )}
        </div>
      </aside>
      <main className="app-main">{children}</main>
      {aside}
    </div>
  );
}

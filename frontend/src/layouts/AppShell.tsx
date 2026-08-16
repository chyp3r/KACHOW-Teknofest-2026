import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  FileText,
  LogIn,
  LogOut,
  Menu,
  MessageCircle,
  MessageSquare,
  Moon,
  ShieldCheck,
  Sun,
  X,
  FilePenLine,
  Monitor,
  Route,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ROLE_LABELS } from "../types/users";
import { useConversations } from "../hooks/useConversations";
import { useMessagingStream } from "../hooks/useMessagingStream";
import { useTheme } from "../hooks/useTheme";
import type { ThemeMode } from "../contexts/ThemeContext";
import { Button, IconButton } from "../components/Button";
import { Select } from "../components/FormControls";
import { NotificationBell } from "../components/NotificationBell";
import { OverlayBackdrop } from "../components/Surface";

interface AppShellProps {
  children: ReactNode;
  aside?: ReactNode;
}

const NAV_ITEMS: Array<{
  route: string;
  label: string;
  icon: typeof MessageSquare;
  admin?: boolean;
  badgeKey?: "messages";
}> = [
  { route: "/chats", label: "Sohbetler", icon: MessageSquare },
  { route: "/messages", label: "Mesajlar", icon: MessageCircle, badgeKey: "messages" },
  { route: "/documents", label: "Evraklar", icon: FileText },
  { route: "/drafts", label: "Taslaklar", icon: FilePenLine },
  { route: "/routing", label: "Yönlendirme", icon: Route },
  { route: "/account", label: "Hesabım", icon: Settings },
  { route: "/admin", label: "Yönetim", icon: ShieldCheck, admin: true },
];

const THEME_ICONS: Record<ThemeMode, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export function AppShell({
  children,
  aside,
}: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [compact, setCompact] = useState(
    () => localStorage.getItem("kachow.sidebar.compact") === "true",
  );
  const location = useLocation();
  const navigate = useNavigate();
  const route = location.pathname;
  const { user, logout } = useAuth();
  const conversations = useConversations();
  useMessagingStream(Boolean(user));
  const { mode, setMode } = useTheme();
  const ThemeIcon = THEME_ICONS[mode];
  const themeModes: ThemeMode[] = ["system", "light", "dark"];
  useEffect(() => setMobileOpen(false), [route]);
  const go = (next: string) => {
    navigate(next);
    setMobileOpen(false);
  };
  useEffect(() => {
    if (!mobileOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [mobileOpen]);
  const toggleCompact = () => {
    setCompact((current) => {
      const next = !current;
      localStorage.setItem("kachow.sidebar.compact", String(next));
      return next;
    });
  };
  const cycleTheme = () => {
    const index = themeModes.indexOf(mode);
    setMode(themeModes[(index + 1) % themeModes.length]);
  };

  return (
    <div className={`app-shell ${compact ? "sidebar-compact" : ""} ${aside ? "with-aside" : ""}`}>
      {!mobileOpen && (
        <IconButton
          className="mobile-menu-button"
          icon={<Menu />}
          aria-label="Menüyü aç"
          aria-controls="primary-sidebar"
          aria-expanded="false"
          onClick={() => setMobileOpen(true)}
        />
      )}
      {mobileOpen && (
        <OverlayBackdrop
          className="sidebar-backdrop"
          aria-label="Menüyü kapat"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        id="primary-sidebar"
        className={`app-sidebar ${mobileOpen ? "is-open" : ""}`}
        aria-label="Ana menü"
      >
        <div className="brand">
          <span className="brand-mark">
            <Activity size={21} />
          </span>
          <div className="brand-copy">
            <strong>KACHOW</strong>
            <small>Karar Destek Sistemi</small>
          </div>
          <IconButton
            className="sidebar-compact-toggle"
            icon={compact ? <PanelLeftOpen /> : <PanelLeftClose />}
            aria-label={compact ? "Menüyü genişlet" : "Menüyü daralt"}
            aria-controls="primary-sidebar"
            aria-expanded={!compact}
            title={compact ? "Menüyü genişlet" : "Menüyü daralt"}
            onClick={toggleCompact}
          />
          <IconButton
            className="sidebar-close"
            icon={<X />}
            aria-label="Menüyü kapat"
            onClick={() => setMobileOpen(false)}
          />
        </div>
        <nav className="sidebar-nav">
          <span className="nav-caption">Çalışma Alanı</span>
          {NAV_ITEMS.filter(
            (item) =>
              !item.admin || user?.role === "admin" || user?.role === "manager",
          ).map(({ route: itemRoute, label, icon: Icon, badgeKey }) => (
              <NavLink
                key={itemRoute}
                to={itemRoute}
                className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                title={compact ? label : undefined}
                onClick={() => setMobileOpen(false)}
              >
                <Icon size={18} />
                <span>{label}</span>
                {badgeKey === "messages" && conversations.unreadTotal > 0 && (
                  <span className="unread-badge nav-item-badge">{conversations.unreadTotal}</span>
                )}
              </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          {!compact && (
            <div className="sidebar-notification-row">
              <NotificationBell />
            </div>
          )}
          <label className="theme-control">
            <span>
              <ThemeIcon size={17} />
              Tema
            </span>
            <Select
              aria-label="Tema seçimi"
              value={mode}
              onChange={(event) => setMode(event.target.value as ThemeMode)}
            >
              <option value="system">Sistem</option>
              <option value="light">Açık</option>
              <option value="dark">Koyu</option>
            </Select>
          </label>
          {compact && (
            <IconButton
              className="compact-theme-button"
              icon={<ThemeIcon />}
              aria-label={`Tema: ${mode}. Temayı değiştir`}
              title={`Tema: ${mode}`}
              onClick={cycleTheme}
            />
          )}
          {user ? (
            <div className="user-card">
              <span className="avatar">
                {user.username.slice(0, 2).toLocaleUpperCase("tr-TR")}
              </span>
              <div>
                <strong>{user.username}</strong>
                <small>{ROLE_LABELS[user.role]}</small>
              </div>
              <IconButton
                icon={<LogOut />}
                aria-label="Oturumu kapat"
                title="Oturumu kapat"
                onClick={() => void logout()}
              />
            </div>
          ) : (
            <Button variant="ghost" className="login-link" leadingIcon={<LogIn />} onClick={() => go("/login")}>Oturum aç</Button>
          )}
        </div>
      </aside>
      <main className="app-main">{children}</main>
      {aside && <div className="workflow-region">{aside}</div>}
    </div>
  );
}

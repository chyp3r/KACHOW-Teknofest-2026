import { Bell, CheckCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNotifications } from "../hooks/useNotifications";
import { useNotificationsStream } from "../hooks/useNotificationsStream";
import { Button, IconButton } from "./Button";
import { EmptyState } from "./EmptyState";

function formatTime(iso: string): string {
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "";
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "short", timeStyle: "short" }).format(value);
}

export function NotificationBell() {
  const notifications = useNotifications();
  useNotificationsStream(true);
  const [open, setOpen] = useState(false);
  const [panelPosition, setPanelPosition] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Rendered via a portal at a `fixed` position computed from the button --
  // `.app-sidebar` sets `overflow: hidden` (it's a fixed-width column with
  // its own scroll region), so a plain absolutely-positioned popout here
  // would just get clipped at the sidebar's edge instead of overlapping
  // the page like a dropdown should.
  useEffect(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    setPanelPosition({ top: rect.bottom + 8, left: rect.left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        buttonRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) {
        return;
      }
      setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  return (
    <div className="notification-bell">
      <IconButton
        ref={buttonRef}
        icon={<Bell />}
        aria-label={
          notifications.unreadCount > 0
            ? `Bildirimler (${notifications.unreadCount} okunmamış)`
            : "Bildirimler"
        }
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      />
      {notifications.unreadCount > 0 && (
        <span className="unread-badge notification-bell-badge">{notifications.unreadCount}</span>
      )}
      {open && panelPosition &&
        createPortal(
          <div
            ref={panelRef}
            className="notification-bell-panel"
            role="dialog"
            aria-label="Bildirimler"
            style={{ position: "fixed", top: panelPosition.top, left: panelPosition.left }}
          >
            <header>
              <h3>Bildirimler</h3>
              {notifications.unreadCount > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  leadingIcon={<CheckCheck />}
                  loading={notifications.markingAllRead}
                  onClick={() => void notifications.markAllRead()}
                >
                  Tümünü okundu işaretle
                </Button>
              )}
            </header>
            {notifications.notifications.length === 0 ? (
              <EmptyState compact icon={Bell} title="Bildiriminiz yok" description="Yeni bir şey olduğunda burada görünecek." />
            ) : (
              <ul className="notification-bell-list">
                {notifications.notifications.map((notification) => (
                  <li
                    key={notification.id}
                    className={notification.read_at ? "" : "is-unread"}
                    onClick={() => {
                      if (!notification.read_at) void notifications.markRead(notification.id);
                    }}
                  >
                    <strong>{notification.title}</strong>
                    {notification.body && <p>{notification.body}</p>}
                    <time dateTime={notification.created_at}>{formatTime(notification.created_at)}</time>
                  </li>
                ))}
              </ul>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}

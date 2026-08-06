import { Search, ShieldAlert, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { userService } from "../services/userService";
import {
  SENSITIVITY_LABELS,
  type SensitivityLevel,
} from "../types/security";
import type { User, UserRole } from "../types/users";

const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Yönetici",
  manager: "Yönetici yardımcısı",
  employee: "Çalışan",
};

export function AdminPage({ onLogin }: { onLogin: () => void }) {
  const { user, loading: sessionLoading } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<UserRole>("employee");
  const [notice, setNotice] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);
  const canView = user?.role === "admin" || user?.role === "manager";
  const canManage = user?.role === "admin";

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setUsers(await userService.list());
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Kullanıcılar yüklenemedi.",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (canView) void load();
    else setLoading(false);
  }, [canView]);

  const filtered = useMemo(
    () =>
      users.filter((item) =>
        `${item.username} ${item.email}`
          .toLocaleLowerCase("tr-TR")
          .includes(query.toLocaleLowerCase("tr-TR")),
      ),
    [query, users],
  );

  const invite = async () => {
    setBusy(true);
    setError(null);
    try {
      await userService.invite(inviteEmail, inviteRole);
      setInviteEmail("");
      setNotice("E-posta adresi kayıt için yetkilendirildi.");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Davet oluşturulamadı.",
      );
    } finally {
      setBusy(false);
    }
  };

  const update = async (
    target: User,
    changes: {
      role?: UserRole;
      is_active?: boolean;
      clearance_level?: SensitivityLevel;
    },
  ) => {
    if (!canManage) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await userService.update(target.id, changes);
      setUsers((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice("Kullanıcı erişimi güncellendi.");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Kullanıcı güncellenemedi.",
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!removeTarget || !canManage) return;
    setBusy(true);
    try {
      await userService.removeAccess(removeTarget.id);
      setUsers((items) => items.filter((item) => item.id !== removeTarget.id));
      setNotice("Kullanıcının erişimi kaldırıldı.");
      setRemoveTarget(null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Erişim kaldırılamadı.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (sessionLoading)
    return <div className="page centered-state">Oturum doğrulanıyor…</div>;
  if (!user)
    return (
      <div className="page centered-state">
        <EmptyState
          icon={ShieldAlert}
          title="Oturum gerekli"
          description="Bu sayfayı görüntülemek için oturum açın."
        />
        <button className="button button-primary" onClick={onLogin}>
          Oturum aç
        </button>
      </div>
    );
  if (!canView)
    return (
      <div className="page centered-state">
        <EmptyState
          icon={ShieldAlert}
          title="Bu alan için yetkiniz yok"
          description="Kullanıcı yönetimi yalnızca yönetici ve manager rollerine açıktır."
        />
      </div>
    );

  return (
    <div className="page page-scroll">
      <PageHeader
        title="Yönetim Paneli"
        description="Kullanıcı rollerini, erişimi ve gizlilik yetkilerini backend kurallarıyla yönetin."
      />
      {error && (
        <div className="notice danger" role="alert">
          {error}
        </div>
      )}
      {notice && <div className="notice success">{notice}</div>}
      <section className="surface invite-panel">
        <div>
          <span className="eyebrow">
            <UserPlus size={14} />
            Yeni kullanıcı erişimi
          </span>
          <h2>E-posta adresini yetkilendir</h2>
          <p>Kullanıcı davetten sonra kayıt akışını tamamlayabilir.</p>
        </div>
        <div className="invite-form">
          <input
            type="email"
            value={inviteEmail}
            onChange={(event) => setInviteEmail(event.target.value)}
            placeholder="kullanici@kurum.gov.tr"
            aria-label="Davet e-posta adresi"
          />
          <select
            value={inviteRole}
            onChange={(event) => setInviteRole(event.target.value as UserRole)}
            aria-label="Davet rolü"
          >
            {Object.entries(ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button
            className="button button-primary"
            disabled={busy || !/^\S+@\S+\.\S+$/.test(inviteEmail)}
            onClick={() => void invite()}
          >
            Erişim daveti oluştur
          </button>
        </div>
      </section>
      <section className="surface users-panel">
        <div className="section-heading">
          <div>
            <h2>Kullanıcı erişimleri</h2>
            <p>{users.length} kayıt</p>
          </div>
          <label className="search-field">
            <Search size={17} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Kullanıcı ara"
            />
          </label>
        </div>
        {loading ? (
          <div className="table-loading">Kullanıcılar yükleniyor…</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Kullanıcı</th>
                  <th>Rol</th>
                  <th>Gizlilik yetkisi</th>
                  <th>Durum</th>
                  <th>İşlemler</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.username}</strong>
                      <span>{item.email}</span>
                    </td>
                    <td>
                      <select
                        value={item.role}
                        disabled={!canManage || busy || item.id === user.id}
                        aria-label={`${item.username} rolü`}
                        onChange={(event) =>
                          void update(item, {
                            role: event.target.value as UserRole,
                          })
                        }
                      >
                        {Object.entries(ROLE_LABELS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select
                        value={item.clearance_level}
                        disabled={!canManage || busy || item.role !== "employee"}
                        aria-label={`${item.username} gizlilik yetkisi`}
                        onChange={(event) =>
                          void update(item, {
                            clearance_level: event.target
                              .value as SensitivityLevel,
                          })
                        }
                      >
                        {Object.entries(SENSITIVITY_LABELS).map(
                          ([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ),
                        )}
                      </select>
                    </td>
                    <td>
                      <StatusBadge
                        tone={
                          item.is_active && !item.is_deleted
                            ? "success"
                            : "neutral"
                        }
                      >
                        {item.is_active && !item.is_deleted
                          ? "Aktif"
                          : "Erişim kapalı"}
                      </StatusBadge>
                    </td>
                    <td>
                      {canManage ? (
                        <div className="table-actions">
                          <button
                            className="button button-quiet"
                            disabled={busy || item.id === user.id}
                            onClick={() =>
                              void update(item, { is_active: !item.is_active })
                            }
                          >
                            {item.is_active ? "Devre dışı bırak" : "Etkinleştir"}
                          </button>
                          <button
                            className="button button-quiet danger-text"
                            disabled={busy || item.id === user.id}
                            onClick={() => setRemoveTarget(item)}
                          >
                            Erişimi kaldır
                          </button>
                        </div>
                      ) : (
                        <small>Yalnızca admin değiştirebilir</small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <ConfirmationDialog
        open={Boolean(removeTarget)}
        title="Erişimi kaldır"
        description={`${removeTarget?.email ?? "Bu kullanıcı"} artık sisteme erişemeyecek.`}
        confirmLabel="Erişimi kaldır"
        busy={busy}
        onCancel={() => setRemoveTarget(null)}
        onConfirm={() => void remove()}
      />
    </div>
  );
}

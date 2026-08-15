import { Activity, Search, ShieldAlert, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { useAdminUsers } from "../hooks/useAdminUsers";
import {
  SENSITIVITY_LABELS,
  type SensitivityLevel,
} from "../types/security";
import { ASSIGNABLE_ROLE_LABELS, type User, type UserRole } from "../types/users";
import { Button } from "../components/Button";
import { Input, Select } from "../components/FormControls";
import { SectionHeader } from "../components/SectionHeader";
import { Alert, Card, Spinner } from "../components/Surface";
import { TrainingPanel } from "../features/admin/TrainingPanel";

export function AdminPage({ onLogin }: { onLogin: () => void }) {
  const { user, loading: sessionLoading } = useAuth();
  const [query, setQuery] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<UserRole>("employee");
  const [notice, setNotice] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<User | null>(null);
  const [removeMode, setRemoveMode] = useState<"soft" | "hard">("soft");
  const canView = user?.role === "admin" || user?.role === "manager";
  const canManage = user?.role === "admin";
  const admin = useAdminUsers(canView);
  const { users, loading, error, busy } = admin;

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
    try {
      await admin.invite(inviteEmail, inviteRole);
      setInviteEmail("");
      setNotice("E-posta adresi kayıt için yetkilendirildi.");
    } catch { /* Mutation error is rendered by the hook. */ }
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
    try {
      await admin.update(target, changes);
      setNotice("Kullanıcı erişimi güncellendi.");
    } catch { /* Mutation error is rendered by the hook. */ }
  };

  const remove = async () => {
    if (!removeTarget || !canManage) return;
    try {
      await admin.remove(removeTarget.id, removeMode === "hard");
      setNotice(
        removeMode === "hard"
          ? "Kullanıcı kalıcı olarak silindi."
          : "Kullanıcının erişimi kaldırıldı.",
      );
      setRemoveTarget(null);
    } catch { /* Mutation error is rendered by the hook. */ }
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
          primaryAction={<Button onClick={onLogin}>Oturum aç</Button>}
        />
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
        secondaryActions={
          <Link className="button button-secondary" to="/status">
            <Activity size={16} /> Sistem durumu
          </Link>
        }
      />
      <ApiErrorNotice error={admin.errorObject ?? error} />
      {notice && <Alert variant="success">{notice}</Alert>}
      <Card className="invite-panel" padding="default">
        <div>
          <span className="eyebrow">
            <UserPlus size={14} />
            Yeni kullanıcı erişimi
          </span>
          <h2>E-posta adresini yetkilendir</h2>
          <p>Kullanıcı davetten sonra kayıt akışını tamamlayabilir.</p>
        </div>
        <div className="invite-form">
          <Input
            type="email"
            value={inviteEmail}
            onChange={(event) => setInviteEmail(event.target.value)}
            placeholder="kullanici@kurum.gov.tr"
            aria-label="Davet e-posta adresi"
          />
          <Select
            value={inviteRole}
            onChange={(event) => setInviteRole(event.target.value as UserRole)}
            aria-label="Davet rolü"
          >
            {Object.entries(ASSIGNABLE_ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
          <Button
            disabled={busy || !/^\S+@\S+\.\S+$/.test(inviteEmail)}
            onClick={() => void invite()}
          >
            Erişim daveti oluştur
          </Button>
        </div>
      </Card>
      <Card className="users-panel">
        <SectionHeader title="Kullanıcı erişimleri" description={`${users.length} kayıt`} action={
          <Input
              fieldClassName="search-field"
              leadingIcon={<Search />}
              aria-label="Kullanıcı ara"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Kullanıcı ara"
            />
        } />
        {loading ? (
          <div className="table-loading"><Spinner label="Kullanıcılar yükleniyor" />Kullanıcılar yükleniyor…</div>
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
                      <Select
                        value={item.role}
                        disabled={!canManage || busy || item.id === user.id}
                        aria-label={`${item.username} rolü`}
                        onChange={(event) =>
                          void update(item, {
                            role: event.target.value as UserRole,
                          })
                        }
                      >
                        {Object.entries(ASSIGNABLE_ROLE_LABELS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </Select>
                    </td>
                    <td>
                      <Select
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
                      </Select>
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
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy || item.id === user.id}
                            onClick={() =>
                              void update(item, { is_active: !item.is_active })
                            }
                          >
                            {item.is_active ? "Devre dışı bırak" : "Etkinleştir"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="danger-text"
                            disabled={busy || item.id === user.id}
                            onClick={() => {
                              setRemoveMode("soft");
                              setRemoveTarget(item);
                            }}
                          >
                            Erişimi kaldır
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="danger-text"
                            disabled={busy || item.id === user.id}
                            onClick={() => {
                              setRemoveMode("hard");
                              setRemoveTarget(item);
                            }}
                          >
                            Kalıcı sil
                          </Button>
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
      </Card>
      {user.company_id && <TrainingPanel companyId={user.company_id} canManage={canManage} />}
      <ConfirmationDialog
        open={Boolean(removeTarget)}
        title={removeMode === "hard" ? "Kullanıcıyı kalıcı sil" : "Erişimi kaldır"}
        description={
          removeMode === "hard"
            ? `${removeTarget?.email ?? "Bu kullanıcı"} ve ilişkili kullanıcı kaydı geri alınamayacak biçimde silinecek.`
            : `${removeTarget?.email ?? "Bu kullanıcı"} artık sisteme erişemeyecek.`
        }
        confirmLabel={removeMode === "hard" ? "Kalıcı sil" : "Erişimi kaldır"}
        busy={busy}
        onCancel={() => setRemoveTarget(null)}
        onConfirm={() => void remove()}
      />
    </div>
  );
}

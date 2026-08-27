import { Activity, BarChart3, Bot, Briefcase, Building2, MoreHorizontal, ScrollText, Search, Shield, ShieldAlert, UserRoundCheck, UserPlus, Users } from "lucide-react";
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
import { Dropdown, Input } from "../components/FormControls";
import { SectionHeader } from "../components/SectionHeader";
import { Alert, Card, Spinner } from "../components/Surface";
import { AiManagementPanel } from "../features/admin/AiManagementPanel";
import { AnalyticsPanel } from "../features/admin/AnalyticsPanel";
import { AuditPanel } from "../features/admin/AuditPanel";
import { CompanySettingsPanel } from "../features/admin/CompanySettingsPanel";
import { UnitsPanel } from "../features/admin/UnitsPanel";
import { UserPermissionsDrawer } from "../features/admin/UserPermissionsDrawer";
import { Tabs } from "../components/Tabs";

type AdminSection = "users" | "units" | "company" | "ai" | "analytics" | "audit";

function UserActionsMenu({
  user,
  disabled,
  onToggle,
  onSoftDelete,
  onHardDelete,
  onDetails,
}: {
  user: User;
  disabled: boolean;
  onToggle: () => void;
  onSoftDelete: () => void;
  onHardDelete: () => void;
  onDetails: () => void;
}) {
  return (
    <details className="action-menu">
      <summary aria-label={`${user.username} için işlemleri aç`} title="İşlemler"><MoreHorizontal /></summary>
      <div role="menu" aria-label={`${user.username} işlemleri`}>
        <Button variant="ghost" size="sm" onClick={onDetails}>Ayrıntılar ve izinler</Button>
        <Button variant="ghost" size="sm" disabled={disabled} onClick={onToggle}>{user.is_active ? "Devre dışı bırak" : "Etkinleştir"}</Button>
        <Button variant="ghost" size="sm" className="danger-text" disabled={disabled} onClick={onSoftDelete}>Erişimi kaldır</Button>
        <Button variant="ghost" size="sm" className="danger-text" disabled={disabled} onClick={onHardDelete}>Kalıcı sil</Button>
      </div>
    </details>
  );
}

export function AdminPage({ onLogin }: { onLogin: () => void }) {
  const { user, loading: sessionLoading } = useAuth();
  const [query, setQuery] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<UserRole>("employee");
  const [notice, setNotice] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<User | null>(null);
  const [removeMode, setRemoveMode] = useState<"soft" | "hard">("soft");
  const [activeSection, setActiveSection] = useState<AdminSection>("users");
  const [detailUser, setDetailUser] = useState<User | null>(null);
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
          canManage ? (
            <Link className="button button-secondary" to="/status">
              <Activity size={16} /> Sistem durumu
            </Link>
          ) : undefined
        }
      />
      <ApiErrorNotice error={admin.errorObject ?? error} />
      {notice && <Alert variant="success">{notice}</Alert>}
      <Tabs
        label="Yönetim bölümleri"
        active={activeSection}
        onChange={setActiveSection}
        items={[
          { id: "users", label: "Kullanıcılar", icon: <Users /> },
          { id: "units", label: "Birimler", icon: <Building2 /> },
          ...(canManage ? [{ id: "company" as const, label: "Kurum", icon: <Briefcase /> }] : []),
          ...(canManage ? [{ id: "ai" as const, label: "AI ve Eğitim", icon: <Bot /> }] : []),
          { id: "analytics", label: "Analitik", icon: <BarChart3 /> },
          ...(canManage ? [{ id: "audit" as const, label: "Denetim", icon: <ScrollText /> }] : []),
        ]}
      />
      {activeSection === "users" && <div className="admin-section" role="tabpanel">
      <div className="admin-overview-grid" aria-label="Kullanıcı özeti">
        <Card className="admin-metric-card"><span><Users /></span><div><small>Toplam kullanıcı</small><strong>{users.length}</strong></div></Card>
        <Card className="admin-metric-card"><span><Shield /></span><div><small>Yönetici</small><strong>{users.filter((item) => item.role === "admin" || item.role === "manager").length}</strong></div></Card>
        <Card className="admin-metric-card"><span><UserRoundCheck /></span><div><small>Yönetici yardımcısı</small><strong>{users.filter((item) => item.role === "manager").length}</strong></div></Card>
        <Card className="admin-metric-card"><span><Briefcase /></span><div><small>Çalışan</small><strong>{users.filter((item) => item.role === "employee").length}</strong></div></Card>
      </div>
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
          <Dropdown
            value={inviteRole}
            onChange={(event) => setInviteRole(event.target.value as UserRole)}
            aria-label="Davet rolü"
          >
            {Object.entries(ASSIGNABLE_ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Dropdown>
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
        ) : filtered.length === 0 ? (
          <EmptyState compact icon={Search} title="Kullanıcı bulunamadı" description="Arama ifadenizi değiştirip yeniden deneyin." />
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
                      <Dropdown
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
                      </Dropdown>
                    </td>
                    <td>
                      <Dropdown
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
                      </Dropdown>
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
                        <UserActionsMenu
                          user={item}
                          disabled={busy || item.id === user.id}
                          onToggle={() => void update(item, { is_active: !item.is_active })}
                          onSoftDelete={() => { setRemoveMode("soft"); setRemoveTarget(item); }}
                          onHardDelete={() => { setRemoveMode("hard"); setRemoveTarget(item); }}
                          onDetails={() => setDetailUser(item)}
                        />
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
      </div>}
      {activeSection === "units" && <UnitsPanel canManage />}
      {activeSection === "company" && user.company_id && <CompanySettingsPanel companyId={user.company_id} canManage={canManage} />}
      {activeSection === "ai" && canManage && (
        <div className="admin-section" role="tabpanel">
          {user.company_id ? (
            <AiManagementPanel companyId={user.company_id} canManage={canManage} />
          ) : (
            <EmptyState icon={Bot} title="Şirket bağlamı bulunamadı" description="AI eğitim verileri yalnızca bir şirkete bağlı yönetici hesabında görüntülenebilir." />
          )}
        </div>
      )}
      {activeSection === "analytics" && user.company_id && <AnalyticsPanel companyId={user.company_id} canViewObservability={canManage} />}
      {activeSection === "audit" && <AuditPanel companyId={user.company_id ?? undefined} />}
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
      <UserPermissionsDrawer user={detailUser} open={Boolean(detailUser)} canManage={canView} onClose={() => setDetailUser(null)} />
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Building2, HeartPulse, LayoutDashboard, Plus, ScrollText, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { Button, IconButton } from "../components/Button";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { Input } from "../components/FormControls";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Alert, Card, Spinner } from "../components/Surface";
import { Tabs } from "../components/Tabs";
import { AuditPanel } from "../features/admin/AuditPanel";
import { queryKeys } from "../query/queryKeys";
import { companyService } from "../services/companyService";
import { rootService } from "../services/rootService";
import type { Company } from "../types/management";

type PlatformTab = "overview" | "companies" | "users" | "health" | "audit";

export function PlatformPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<PlatformTab>("overview");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const [adminIds, setAdminIds] = useState<Record<string, string>>({});
  const [deleteTarget, setDeleteTarget] = useState<Company | null>(null);
  const overview = useQuery({ queryKey: queryKeys.rootOverview, queryFn: rootService.overview, enabled: tab === "overview" });
  const companyStats = useQuery({ queryKey: queryKeys.rootCompanies, queryFn: rootService.companies, enabled: tab === "overview" || tab === "companies" });
  const companies = useQuery({ queryKey: queryKeys.companies, queryFn: () => companyService.list(), enabled: tab === "companies" });
  const companyDetail = useQuery({ queryKey: queryKeys.company(selectedCompanyId), queryFn: () => companyService.get(selectedCompanyId), enabled: tab === "companies" && Boolean(selectedCompanyId) });
  const userStats = useQuery({ queryKey: queryKeys.rootUsers, queryFn: rootService.users, enabled: tab === "users" || tab === "overview" });
  const health = useQuery({ queryKey: queryKeys.rootHealth, queryFn: rootService.health, enabled: tab === "health" });
  const invalidateCompanies = () => { void queryClient.invalidateQueries({ queryKey: queryKeys.companies }); void queryClient.invalidateQueries({ queryKey: queryKeys.rootCompanies }); void queryClient.invalidateQueries({ queryKey: queryKeys.rootOverview }); };
  const create = useMutation({ mutationFn: () => companyService.create({ name, slug, tax_number: taxNumber || null }), onSuccess: () => { invalidateCompanies(); setCreateOpen(false); setName(""); setSlug(""); setTaxNumber(""); } });
  const update = useMutation({ mutationFn: ({ id, changes }: { id: string; changes: Partial<Pick<Company, "name" | "tax_number" | "is_active">> }) => companyService.update(id, changes), onSuccess: invalidateCompanies });
  const remove = useMutation({ mutationFn: companyService.remove, onSuccess: invalidateCompanies });
  const assignAdmin = useMutation({ mutationFn: ({ companyId, userId }: { companyId: string; userId: string }) => companyService.assignAdmin(companyId, userId) });
  const error = overview.error ?? companyStats.error ?? companies.error ?? companyDetail.error ?? userStats.error ?? health.error ?? create.error ?? update.error ?? remove.error ?? assignAdmin.error;
  const summary = overview.data;
  return <div className="page page-scroll platform-page"><PageHeader title="Platform Yönetimi" description="Kurumlar arası sistem görünümü ve root yönetim alanı." /><ApiErrorNotice error={error || null} /><Tabs label="Platform yönetimi" active={tab} onChange={setTab} items={[{ id: "overview", label: "Genel Bakış", icon: <LayoutDashboard /> }, { id: "companies", label: "Kurumlar", icon: <Building2 /> }, { id: "users", label: "Kullanıcı İstatistikleri", icon: <Users /> }, { id: "health", label: "Sistem Sağlığı", icon: <HeartPulse /> }, { id: "audit", label: "Denetim", icon: <ScrollText /> }]} />
    {tab === "overview" && (overview.isLoading ? <div className="table-loading"><Spinner />Platform özeti yükleniyor…</div> : <div className="admin-section"><div className="admin-overview-grid"><Card className="admin-metric-card"><span><Building2 /></span><div><small>Kurumlar</small><strong>{summary?.total_companies ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><Users /></span><div><small>Kullanıcılar</small><strong>{summary?.total_users ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><Activity /></span><div><small>Evraklar</small><strong>{summary?.total_documents ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><LayoutDashboard /></span><div><small>Taslaklar</small><strong>{summary?.total_drafts ?? 0}</strong></div></Card></div><Card className="management-panel"><header className="management-panel-header"><div><h2>Kurum kullanımı</h2><p>Platform genelindeki kayıt hacimleri</p></div></header><ul className="management-list">{companyStats.data?.map((company) => <li key={company.company_id}><div><strong>{company.name}</strong><small>{company.user_count} kullanıcı · {company.document_count} evrak · {company.draft_count} taslak</small></div></li>)}</ul></Card></div>)}
    {tab === "companies" && <div className="admin-section"><Card className="management-panel"><header className="management-panel-header"><div><h2>Kurumlar</h2><p>{companies.data?.total ?? 0} tenant</p></div><Button leadingIcon={<Plus />} onClick={() => setCreateOpen((value) => !value)}>Yeni kurum</Button></header>{createOpen && <div className="management-form"><Input label="Kurum adı" value={name} onChange={(event) => setName(event.target.value)} /><Input label="Kısa ad (slug)" value={slug} pattern="[a-z0-9-]+" onChange={(event) => setSlug(event.target.value.toLocaleLowerCase("tr-TR").replace(/[^a-z0-9-]/g, "-"))} /><Input label="Vergi numarası" value={taxNumber} onChange={(event) => setTaxNumber(event.target.value)} /><Button loading={create.isPending} disabled={!name || !slug} onClick={() => create.mutate()}>Kurumu oluştur</Button></div>}<ul className="management-list company-list">{companies.data?.items.map((company) => <li key={company.id}><div><strong>{company.name}</strong><small>{company.slug} · {company.tax_number || "Vergi no yok"}</small></div><StatusBadge tone={company.is_active ? "success" : "neutral"}>{company.is_active ? "Aktif" : "Pasif"}</StatusBadge><Button size="sm" variant="ghost" onClick={() => setSelectedCompanyId(company.id)}>Detay</Button><Button size="sm" variant="outline" onClick={() => update.mutate({ id: company.id, changes: { is_active: !company.is_active } })}>{company.is_active ? "Pasifleştir" : "Etkinleştir"}</Button><Input aria-label={`${company.name} yönetici kullanıcı kimliği`} placeholder="Yönetici kullanıcı ID" value={adminIds[company.id] ?? ""} onChange={(event) => setAdminIds((current) => ({ ...current, [company.id]: event.target.value }))} /><Button size="sm" variant="outline" disabled={!adminIds[company.id]} loading={assignAdmin.isPending} onClick={() => assignAdmin.mutate({ companyId: company.id, userId: adminIds[company.id] })}>Yönetici ata</Button><IconButton icon={<Trash2 />} aria-label="Kurumu sil" onClick={() => setDeleteTarget(company)} /></li>)}</ul></Card>{selectedCompanyId && <Card className="management-panel"><header className="management-panel-header"><div><h2>Kurum detayı</h2><p>Doğrudan tenant kaydı ve platform ayarları</p></div><Button size="sm" variant="ghost" onClick={() => setSelectedCompanyId("")}>Kapat</Button></header>{companyDetail.isLoading ? <Spinner /> : companyDetail.data && <dl className="detail-list"><div><dt>Ad</dt><dd>{companyDetail.data.name}</dd></div><div><dt>Slug</dt><dd>{companyDetail.data.slug}</dd></div><div><dt>Vergi numarası</dt><dd>{companyDetail.data.tax_number || "—"}</dd></div><div><dt>Durum</dt><dd>{companyDetail.data.is_active ? "Aktif" : "Pasif"}</dd></div><div><dt>Ayar alanı</dt><dd>{Object.keys(companyDetail.data.settings).length} kayıt</dd></div></dl>}</Card>}</div>}
    {tab === "users" && <div className="admin-section"><div className="admin-overview-grid"><Card className="admin-metric-card"><div><small>7 günlük aktif</small><strong>{userStats.data?.active_7d ?? "—"}</strong></div></Card><Card className="admin-metric-card"><div><small>30 günlük aktif</small><strong>{userStats.data?.active_30d ?? "—"}</strong></div></Card>{Object.entries(userStats.data?.by_role ?? {}).map(([role, count]) => <Card key={role} className="admin-metric-card"><div><small>{role}</small><strong>{count}</strong></div></Card>)}</div><Card className="management-panel"><ul className="management-list">{userStats.data?.seats_by_company.map((item) => <li key={item.company_id}><div><strong>{item.name}</strong><small>{item.user_count} kullanıcı</small></div></li>)}</ul></Card></div>}
    {tab === "health" && <Card className="management-panel"><header className="management-panel-header"><div><h2>Platform sağlığı</h2><p>Bağımlılıklar ve kurumların son aktivitesi</p></div><StatusBadge tone={health.data?.status === "healthy" ? "success" : "warning"}>{health.data?.status ?? "Yükleniyor"}</StatusBadge></header>{health.isLoading ? <Spinner /> : <ul className="management-list">{Object.entries(health.data?.companies_last_activity ?? {}).map(([companyId, lastSeen]) => <li key={companyId}><div><strong>{companyId}</strong><small>{lastSeen ? new Date(lastSeen).toLocaleString("tr-TR") : "Aktivite yok"}</small></div></li>)}</ul>}</Card>}
    {tab === "audit" && <AuditPanel />}
    {assignAdmin.isSuccess && <Alert variant="success">Kurum yöneticisi atandı.</Alert>}
    <ConfirmationDialog open={Boolean(deleteTarget)} title="Kurumu sil" description={`${deleteTarget?.name ?? "Bu kurum"} pasif hâle getirilecek.`} confirmLabel="Sil" busy={remove.isPending} onCancel={() => setDeleteTarget(null)} onConfirm={() => deleteTarget && void remove.mutateAsync(deleteTarget.id).then(() => setDeleteTarget(null))} />
  </div>;
}

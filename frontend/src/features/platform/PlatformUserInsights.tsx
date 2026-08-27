import { Card, Spinner } from "../../components/Surface";
import type { RootUserStats } from "../../types/management";

/** The "Kullanıcı İstatistikleri" tab of the Platform Yönetimi page --
 * split out of PlatformPage so that page stays a thin router over its tabs. */
export function PlatformUserInsights({
  data,
  loading,
}: {
  data: RootUserStats | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="table-loading">
        <Spinner />
        Kullanıcı istatistikleri yükleniyor…
      </div>
    );
  }

  return (
    <div className="admin-section">
      <div className="admin-overview-grid">
        <Card className="admin-metric-card">
          <div>
            <small>7 günlük aktif</small>
            <strong>{data?.active_7d ?? "—"}</strong>
          </div>
        </Card>
        <Card className="admin-metric-card">
          <div>
            <small>30 günlük aktif</small>
            <strong>{data?.active_30d ?? "—"}</strong>
          </div>
        </Card>
        {Object.entries(data?.by_role ?? {}).map(([role, count]) => (
          <Card key={role} className="admin-metric-card">
            <div>
              <small>{role}</small>
              <strong>{count}</strong>
            </div>
          </Card>
        ))}
      </div>

      <Card className="management-panel">
        <header className="management-panel-header">
          <div>
            <h2>Kurum bazında koltuklar</h2>
            <p>Aktif kullanıcıların kurumlara dağılımı</p>
          </div>
        </header>
        <ul className="management-list">
          {data?.seats_by_company.map((item) => (
            <li key={item.company_id}>
              <div>
                <strong>{item.name}</strong>
                <small>{item.user_count} kullanıcı</small>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

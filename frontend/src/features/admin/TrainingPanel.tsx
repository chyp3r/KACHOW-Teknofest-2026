import { GraduationCap } from "lucide-react";
import { Fragment, useState } from "react";
import { Button } from "../../components/Button";
import { SectionHeader } from "../../components/SectionHeader";
import { StatusBadge, type StatusTone } from "../../components/StatusBadge";
import { Alert, Card, Spinner } from "../../components/Surface";
import { useTrainingData } from "../../hooks/useTrainingData";

const RUN_STATUS_TONE: Record<string, StatusTone> = {
  succeeded: "success",
  failed: "danger",
  skipped: "neutral",
  running: "pending",
  queued: "pending",
};

const RUN_STATUS_LABELS: Record<string, string> = {
  succeeded: "Başarılı",
  failed: "Başarısız",
  skipped: "Atlandı (yetersiz örnek)",
  running: "Çalışıyor",
  queued: "Sırada",
};

// Company admins train their own company's style adapter; a Root user has
// no company_id and this panel simply does not render for them (see
// AdminPage's own canView gate -- Root already uses a separate console).
export function TrainingPanel({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const training = useTrainingData(companyId);
  const [expandedSampleId, setExpandedSampleId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const compile = async () => {
    try {
      const result = await training.compile();
      setNotice(`${result.total} örnek derlendi.`);
    } catch {
      /* Mutation error is surfaced via training.error below. */
    }
  };

  const triggerRun = async () => {
    try {
      const run = await training.triggerRun();
      setNotice(
        run.status === "succeeded"
          ? "Üslup adaptörü güncellendi."
          : run.status === "skipped"
            ? "Eğitim atlandı -- eşiği geçecek kadar örnek yok."
            : "Eğitim başarısız oldu, aşağıdaki geçmişten hatayı görebilirsiniz.",
      );
    } catch {
      /* Mutation error is surfaced via training.error below. */
    }
  };

  const stats = training.stats;
  const progressPct = stats
    ? Math.min(100, Math.round((stats.total / Math.max(1, stats.min_samples_required)) * 100))
    : 0;

  return (
    <Card className="training-panel">
      <SectionHeader
        title={
          <span className="eyebrow">
            <GraduationCap size={14} /> Üslup adaptörü eğitimi
          </span>
        }
        description="Kullanıcıların 👍/👎 oyladığı taslaklardan otomatik üslup kuralı çıkarımı (Faz C3)."
        action={
          canManage ? (
            <div className="table-actions">
              <Button variant="outline" size="sm" disabled={training.isBusy} onClick={() => void compile()}>
                Örnekleri derle
              </Button>
              <Button size="sm" disabled={training.isBusy} onClick={() => void triggerRun()}>
                {training.isBusy ? <Spinner size="xs" label="Çalışıyor" /> : "Eğitimi başlat"}
              </Button>
            </div>
          ) : null
        }
      />
      {training.error && (
        <Alert variant="error">
          {training.error instanceof Error ? training.error.message : "İşlem başarısız oldu."}
        </Alert>
      )}
      {notice && <Alert variant="success">{notice}</Alert>}

      {training.statsLoading ? (
        <div className="table-loading">
          <Spinner label="İstatistikler yükleniyor" />
          İstatistikler yükleniyor…
        </div>
      ) : stats ? (
        <div className="training-stats-grid">
          <div className="stat-card">
            <small className="stat-label">Toplam örnek</small>
            <strong>{stats.total}</strong>
          </div>
          <div className="stat-card">
            <small className="stat-label">Eşiğe kalan</small>
            <strong>{stats.samples_remaining_to_threshold}</strong>
            <small className="stat-sublabel">/ {stats.min_samples_required} gerekli</small>
          </div>
          <div className="stat-card stat-card-progress">
            <small className="stat-label">İlerleme</small>
            <div className="progress-bar" role="progressbar" aria-valuenow={progressPct} aria-valuemin={0} aria-valuemax={100}>
              <div className="progress-bar-fill" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        </div>
      ) : null}

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Kaynak</th>
              <th>Beğenilen</th>
              <th>Beğenilmeyen</th>
              {canManage && <th>İşlemler</th>}
            </tr>
          </thead>
          <tbody>
            {training.samples.map((sample) => (
              <Fragment key={sample.id}>
                <tr
                  className="clickable-row"
                  onClick={() =>
                    setExpandedSampleId((current) => (current === sample.id ? null : sample.id))
                  }
                >
                  <td>{sample.source}</td>
                  <td>{sample.chosen ? "✓" : "—"}</td>
                  <td>{sample.rejected ? "✓" : "—"}</td>
                  {canManage && (
                    <td>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="danger-text"
                        onClick={(event) => {
                          event.stopPropagation();
                          void training.deleteSample(sample.id);
                        }}
                      >
                        Kaldır
                      </Button>
                    </td>
                  )}
                </tr>
                {expandedSampleId === sample.id && (
                  <tr>
                    <td colSpan={canManage ? 4 : 3}>
                      <div className="sample-diff">
                        {sample.chosen && (
                          <div className="sample-diff-side sample-diff-chosen">
                            <strong>Beğenilen</strong>
                            <p>{sample.chosen}</p>
                          </div>
                        )}
                        {sample.rejected && (
                          <div className="sample-diff-side sample-diff-rejected">
                            <strong>Beğenilmeyen</strong>
                            <p>{sample.rejected}</p>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {!training.samplesLoading && training.samples.length === 0 && (
          <p className="empty-hint">Henüz derlenmiş bir eğitim örneği yok.</p>
        )}
      </div>

      {training.runs.length > 0 && (
        <>
          <SectionHeader title="Eğitim geçmişi" />
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Durum</th>
                  <th>Örnek sayısı</th>
                  <th>Tarih</th>
                </tr>
              </thead>
              <tbody>
                {training.runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <StatusBadge tone={RUN_STATUS_TONE[run.status] ?? "neutral"}>
                        {RUN_STATUS_LABELS[run.status] ?? run.status}
                      </StatusBadge>
                      {run.error && <small className="danger-text"> {run.error}</small>}
                    </td>
                    <td>{run.sample_count ?? "—"}</td>
                    <td>{new Date(run.created_at).toLocaleString("tr-TR")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}

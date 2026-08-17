import { useQuery } from "@tanstack/react-query";
import { FileText, FilePenLine } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Surface";
import { StatusBadge, type StatusTone } from "../../components/StatusBadge";
import { queryKeys } from "../../query/queryKeys";
import { transferService } from "../../services/transferService";
import type { TransferStatus } from "../../types/transfers";

const STATUS_TONE: Record<TransferStatus, StatusTone> = {
  executed: "success",
  failed: "danger",
  withdrawn: "neutral",
};

const STATUS_LABEL: Record<TransferStatus, string> = {
  executed: "Gönderildi",
  failed: "Başarısız",
  withdrawn: "Geri çekildi",
};

// A `kind="artifact"` conversation message never caches the artifact's own
// title/status into `body` (see `ConversationMessageModel`'s own
// docstring) -- this card reads the transfer live, so a withdrawn/failed
// transfer's card reflects reality instead of a stale snapshot.
export function ArtifactMessageCard({
  transferId,
  currentUserId,
}: {
  transferId: string;
  currentUserId: string;
}) {
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: queryKeys.transfer(transferId),
    queryFn: () => transferService.get(transferId),
    staleTime: 15_000,
  });

  if (query.isLoading) {
    return (
      <div className="artifact-card" role="status">
        <Spinner size="sm" label="Gönderi yükleniyor" />
      </div>
    );
  }

  if (query.error || !query.data) {
    return <div className="artifact-card artifact-card-error">Gönderi yüklenemedi.</div>;
  }

  const transfer = query.data;
  const isOwnSend = transfer.sender_id === currentUserId;
  const isDraft = transfer.artifact_kind === "draft";
  // The sender opens their own original; the recipient opens their own,
  // independently owned fork -- never the other party's copy.
  const openTargetId = isOwnSend ? transfer.source_artifact_id : transfer.snapshot_ref;

  return (
    <div className="artifact-card">
      <span className="artifact-card-icon" aria-hidden="true">
        {isDraft ? <FilePenLine /> : <FileText />}
      </span>
      <div className="artifact-card-body">
        <strong>
          {isDraft ? "Taslak" : "Evrak"}
          {transfer.source_version ? ` · v${transfer.source_version}` : ""}
        </strong>
        <div className="artifact-card-meta">
          <StatusBadge tone={STATUS_TONE[transfer.status]}>{STATUS_LABEL[transfer.status]}</StatusBadge>
          {transfer.cross_unit && <span className="artifact-card-cross-unit">Farklı birim</span>}
        </div>
      </div>
      {isDraft && openTargetId && transfer.status === "executed" && (
        <Button
          size="sm"
          variant="outline"
          onClick={() => navigate(`/drafts/${encodeURIComponent(openTargetId)}`)}
        >
          Aç
        </Button>
      )}
    </div>
  );
}

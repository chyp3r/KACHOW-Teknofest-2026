import { useMutation, useQuery } from "@tanstack/react-query";
import { FileText, FilePenLine, Send } from "lucide-react";
import { useState } from "react";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Dialog } from "../../components/Overlay";
import { Spinner } from "../../components/Surface";
import { useDrafts } from "../../hooks/useDrafts";
import { queryKeys } from "../../query/queryKeys";
import { documentService } from "../../services/documentService";
import { transferService } from "../../services/transferService";
import type { ArtifactKind } from "../../types/transfers";

export function SendArtifactDialog({
  open,
  onClose,
  recipientId,
  onSent,
}: {
  open: boolean;
  onClose: () => void;
  recipientId: string;
  onSent: () => void;
}) {
  const [tab, setTab] = useState<ArtifactKind>("draft");
  const drafts = useDrafts();
  const documentsQuery = useQuery({
    queryKey: queryKeys.documents(),
    queryFn: () => documentService.list(),
    enabled: open && tab === "document",
    staleTime: 30_000,
  });

  const sendMutation = useMutation({
    mutationFn: (params: { sourceArtifactId: string; sourceVersion?: number }) =>
      transferService.send({
        recipientId,
        artifactKind: tab,
        sourceArtifactId: params.sourceArtifactId,
        sourceVersion: params.sourceVersion,
      }),
    onSuccess: () => {
      onSent();
      onClose();
    },
  });

  return (
    <Dialog open={open} title="Taslak veya evrak gönder" onClose={onClose}>
      <div className="new-conversation-tabs" role="tablist" aria-label="Gönderilecek içerik türü">
        <Button
          role="tab"
          aria-selected={tab === "draft"}
          variant={tab === "draft" ? "primary" : "outline"}
          size="sm"
          leadingIcon={<FilePenLine />}
          onClick={() => setTab("draft")}
        >
          Taslak
        </Button>
        <Button
          role="tab"
          aria-selected={tab === "document"}
          variant={tab === "document" ? "primary" : "outline"}
          size="sm"
          leadingIcon={<FileText />}
          onClick={() => setTab("document")}
        >
          Evrak
        </Button>
      </div>

      {tab === "draft" ? (
        drafts.loading ? (
          <div className="centered-state" role="status">
            <Spinner label="Taslaklar yükleniyor" />
          </div>
        ) : drafts.drafts.length === 0 ? (
          <EmptyState compact icon={FilePenLine} title="Taslağınız yok" description="Önce bir taslak oluşturun." />
        ) : (
          <ul className="send-artifact-list" aria-label="Taslaklarınız">
            {drafts.drafts.map((draft) => (
              <li key={draft.id} className="send-artifact-row">
                <span className="send-artifact-row-title">
                  {draft.correspondence_type?.replace(/_/g, " ") || "Resmî taslak"}
                  <small>v{draft.version} · {new Date(draft.updated_at).toLocaleDateString("tr-TR")}</small>
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  leadingIcon={<Send />}
                  loading={sendMutation.isPending}
                  onClick={() => sendMutation.mutate({ sourceArtifactId: draft.id, sourceVersion: draft.version })}
                >
                  Gönder
                </Button>
              </li>
            ))}
          </ul>
        )
      ) : documentsQuery.isLoading ? (
        <div className="centered-state" role="status">
          <Spinner label="Evraklar yükleniyor" />
        </div>
      ) : !documentsQuery.data || documentsQuery.data.length === 0 ? (
        <EmptyState compact icon={FileText} title="Evrakınız yok" description="Önce bir evrak yükleyin." />
      ) : (
        <ul className="send-artifact-list" aria-label="Evraklarınız">
          {documentsQuery.data.map((document) => (
            <li key={document.storage_path} className="send-artifact-row">
              <span className="send-artifact-row-title">{document.file_name}</span>
              <Button
                size="sm"
                variant="outline"
                leadingIcon={<Send />}
                loading={sendMutation.isPending}
                onClick={() => sendMutation.mutate({ sourceArtifactId: document.storage_path })}
              >
                Gönder
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

import type { CorrespondenceType, DocumentMetadata } from "../types/documents";
import type { PersistedDraft } from "../types/drafts";

/**
 * The draft's own "Konu: ..." header line (writer.md's fixed structure
 * always includes one, see backend app.ai.prompts.templates.writer.md).
 *
 * The bug this closes: the drafts list used to title every entry from just
 * its source document name and correspondence type -- two document-less
 * drafts of the same type ("Kaynak yok - Bilgilendirme Metni", say)
 * rendered an identical, non-distinguishing title, making the list
 * unusable for telling them apart. `null` for a draft whose Konu line is
 * itself an unfilled `[Konu]` placeholder -- that carries no more
 * information than the fallback title already does.
 */
export function draftSubject(draft: Pick<PersistedDraft, "content">): string | null {
  const match = draft.content.match(/^[ \t]*Konu[ \t]*:[ \t]*(.+)$/im);
  const subject = match?.[1]?.trim();
  if (!subject || /^\[.+\]$/.test(subject)) return null;
  return subject;
}

export function documentName(
  documentId: string | null,
  documents: DocumentMetadata[],
): string {
  if (!documentId) return "Kaynak yok";
  const document = documents.find((item) => item.storage_path === documentId);
  return document?.file_name ?? documentId.split(/[\\/]/).pop() ?? documentId;
}

export function correspondenceTypeLabel(
  draft: Pick<PersistedDraft, "correspondence_type">,
  correspondenceTypes: CorrespondenceType[],
): string {
  const knownType = correspondenceTypes.find((item) => item.value === draft.correspondence_type);
  if (knownType) return knownType.label;
  if (!draft.correspondence_type) return "Resmî taslak";
  return draft.correspondence_type.replace(/_/g, " ");
}

/** Prefers the draft's own subject (see {@link draftSubject}); falls back
 * to the pre-existing "<source> - <type>" form when it can't be extracted. */
export function draftTitle(
  draft: PersistedDraft,
  documents: DocumentMetadata[],
  correspondenceTypes: CorrespondenceType[],
): string {
  const subject = draftSubject(draft);
  if (subject) return `${subject} · ${correspondenceTypeLabel(draft, correspondenceTypes)}`;
  return `${documentName(draft.document_id, documents)} - ${correspondenceTypeLabel(draft, correspondenceTypes)}`;
}

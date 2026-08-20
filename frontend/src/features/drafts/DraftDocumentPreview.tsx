export function DraftDocumentPreview({ content }: { content: string }) {
  return (
    <article className="draft-paper" aria-label="Resmî yazı önizlemesi">
      <div className="draft-paper-content">{content}</div>
    </article>
  );
}

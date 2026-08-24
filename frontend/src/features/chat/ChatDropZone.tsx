import { UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { validateUploadFile } from "../documents/uploadConstraints";

export function ChatDropZone({
  onUpload,
  children,
}: {
  onUpload: (file: File) => Promise<void>;
  children: ReactNode;
}) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // dragenter/dragleave fire once per element the pointer crosses, including
  // children of this wrapper -- a plain boolean would flicker the overlay
  // closed every time the drag moves over a nested element. Counting nets
  // enter/leave pairs out so the overlay only closes once the pointer
  // actually leaves the wrapper's whole subtree.
  const dragDepth = useRef(0);

  const hasFiles = (event: DragEvent) => Array.from(event.dataTransfer.types).includes("Files");

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  };
  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
  };
  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (!hasFiles(event)) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  };
  const handleDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (!file) return;
    const validationError = validateUploadFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    try {
      await onUpload(file);
    } catch {
      /* Error is surfaced by the chat/document hooks. */
    }
  };

  return (
    <div
      className="chat-dropzone-wrapper"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(event) => void handleDrop(event)}
    >
      {children}
      {(dragging || error) && (
        <div className="chat-dropzone-overlay" role="status" aria-live="polite">
          <div className="chat-dropzone-overlay-content">
            <span className="chat-dropzone-overlay-icon" aria-hidden="true">
              <UploadCloud size={32} />
            </span>
            {error ? (
              <>
                <strong>{error}</strong>
                <button
                  type="button"
                  className="chat-dropzone-dismiss"
                  onClick={() => setError(null)}
                >
                  Kapat
                </button>
              </>
            ) : (
              <>
                <strong>Dosyanızı buraya bırakın</strong>
                <span>Evrak sohbete eklenir ve analiz edilir.</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

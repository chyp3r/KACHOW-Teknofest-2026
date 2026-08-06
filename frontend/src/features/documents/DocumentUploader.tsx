import { useRef, useState, type DragEvent } from "react";
import { CheckCircle2, UploadCloud } from "lucide-react";

const MAX_SIZE = 50 * 1024 * 1024;
const ALLOWED_EXTENSIONS = [
  "pdf",
  "txt",
  "doc",
  "png",
  "jpg",
  "jpeg",
  "tif",
  "tiff",
];

export function DocumentUploader({
  uploading,
  onUpload,
}: {
  uploading: boolean;
  onUpload: (file: File) => Promise<void>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const selectFile = async (file?: File) => {
    if (!file) return;
    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ALLOWED_EXTENSIONS.includes(extension)) {
      setMessage("Bu dosya türü desteklenmiyor.");
      return;
    }
    if (file.size > MAX_SIZE) {
      setMessage("Dosya boyutu 50 MB sınırını aşıyor.");
      return;
    }
    setMessage(null);
    try {
      await onUpload(file);
      setMessage("Evrak başarıyla yüklendi ve analiz edildi.");
    } catch {
      /* Error is shown by the page hook. */
    }
    if (inputRef.current) inputRef.current.value = "";
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void selectFile(event.dataTransfer.files[0]);
  };

  return (
    <section className="upload-card" aria-labelledby="upload-title">
      <div className="section-heading">
        <div>
          <h2 id="upload-title">Yeni evrak yükle</h2>
          <p>
            Yüklenen evrak otomatik olarak analiz edilir ve kütüphaneye eklenir.
          </p>
        </div>
      </div>
      <div
        className={`dropzone ${dragging ? "is-dragging" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        <span className="dropzone-icon">
          <UploadCloud size={26} />
        </span>
        <div>
          <strong>
            {uploading
              ? "Evrak analiz ediliyor…"
              : "Dosyanızı buraya sürükleyin"}
          </strong>
          <span>PDF, TXT, DOC veya görsel • En fazla 50 MB</span>
        </div>
        <button
          className="button button-primary"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
        >
          {uploading ? "Yükleniyor…" : "Dosya seç"}
        </button>
        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          tabIndex={-1}
          aria-hidden="true"
          accept=".pdf,.txt,.doc,.png,.jpg,.jpeg,.tif,.tiff"
          onChange={(event) => void selectFile(event.target.files?.[0])}
        />
      </div>
      {message && (
        <p
          className={
            message.startsWith("Evrak") ? "feedback success" : "feedback error"
          }
        >
          <CheckCircle2 size={15} />
          {message}
        </p>
      )}
    </section>
  );
}

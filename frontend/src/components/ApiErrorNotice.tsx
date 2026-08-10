import { useState } from "react";
import { ApiError } from "../services/apiClient";
import { Button } from "./Button";
import { Alert } from "./Surface";

const STATUS_PREFIX: Record<number, string> = {
  401: "Oturum doğrulanamadı",
  403: "Bu işlem için yetkiniz yok",
  404: "Kayıt bulunamadı",
  409: "İşlem mevcut durumla çakıştı",
  422: "Girilen bilgiler doğrulanamadı",
  429: "İstek sınırına ulaşıldı",
};

export function ApiErrorNotice({ error }: { error: unknown }) {
  const [copied, setCopied] = useState(false);
  if (!error) return null;
  const apiError = error instanceof ApiError ? error : null;
  const message = error instanceof Error ? error.message : String(error);
  const prefix = apiError
    ? STATUS_PREFIX[apiError.status] ?? (apiError.status >= 500 ? "Sunucu işlemi tamamlayamadı" : null)
    : null;

  return (
    <Alert variant="error" title={prefix ?? undefined}>
      {message}
      {apiError && (apiError.requestId || apiError.code || apiError.retryAfter !== undefined) && (
        <details>
          <summary>Hata ayrıntıları</summary>
          {apiError.code && <p>Hata kodu: <code>{apiError.code}</code></p>}
          {apiError.retryAfter !== undefined && <p>Yeniden deneme: {apiError.retryAfter} saniye sonra</p>}
          {apiError.requestId && (
            <p>
              İstek kimliği: <code>{apiError.requestId}</code>{" "}
              <Button variant="ghost" size="sm" onClick={() => {
                void navigator.clipboard.writeText(apiError.requestId!);
                setCopied(true);
              }}>{copied ? "Kopyalandı" : "Kopyala"}</Button>
            </p>
          )}
        </details>
      )}
    </Alert>
  );
}

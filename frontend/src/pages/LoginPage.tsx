import { LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../hooks/useAuth";

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      onSuccess();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Oturum açılamadı.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="page page-scroll">
      <PageHeader
        title="Yönetici oturumu"
        description="Yönetim paneline erişmek için mevcut KACHOW hesabınızla oturum açın."
      />
      <div className="login-wrap">
        <form
          className="surface login-card"
          onSubmit={(event) => void submit(event)}
        >
          <span className="login-icon">
            <LockKeyhole size={22} />
          </span>
          <h2>Oturum aç</h2>
          <p>Yetki, backend tarafından hesabınızın rolüne göre doğrulanır.</p>
          <div className="form-stack">
            <label>
              Kullanıcı adı veya e-posta
              <input
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label>
              Parola
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error && (
              <p className="feedback error" role="alert">
                {error}
              </p>
            )}
            <button className="button button-primary" disabled={busy}>
              {busy ? "Oturum açılıyor…" : "Oturum aç"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

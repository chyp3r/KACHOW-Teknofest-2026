import {
  Eye,
  EyeOff,
  FileBarChart,
  LockKeyhole,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { BrandLockup } from "../components/BrandLockup";
import { Button, IconButton } from "../components/Button";
import { Input } from "../components/FormControls";
import { Alert, Card } from "../components/Surface";
import { useAuth } from "../hooks/useAuth";
import { useSessionNotice } from "../hooks/useSessionNotice";

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionNotice = useSessionNotice();

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
    <main className="login-page">
      <section className="login-intro" aria-labelledby="login-intro-title">
        <BrandLockup />
        <div className="login-intro-copy">
          <span className="eyebrow">Kurumsal karar destek platformu</span>
          <h1 id="login-intro-title">Doğru veri.<br />Doğru analiz.<br />Doğru karar.</h1>
          <p>
            Kurum içi karar süreçlerini destekleyen güvenli, entegre ve güçlü bir çalışma alanı.
          </p>
        </div>
        <div className="login-illustration" aria-hidden="true">
          <div className="login-document-art">
            <FileBarChart />
            <span><ShieldCheck /></span>
          </div>
        </div>
        <small className="login-copyright">© 2026 T.C. Tüm hakları saklıdır.</small>
      </section>

      <section className="login-form-region" aria-labelledby="login-title">
        <Card className="login-card" padding="prominent">
          <form onSubmit={(event) => void submit(event)}>
            <div className="login-form-heading"><div><h2 id="login-title">Oturum aç</h2><p>Kurum hesabınızla devam edin.</p></div></div>
            {sessionNotice && <Alert variant="warning">{sessionNotice}</Alert>}
            <div className="form-stack">
              <Input
                label="Kullanıcı adı veya e-posta"
                leadingIcon={<UserRound />}
                autoComplete="username"
                required
                value={username}
                disabled={busy}
                onChange={(event) => setUsername(event.target.value)}
              />
              <Input
                label="Parola"
                leadingIcon={<LockKeyhole />}
                type={passwordVisible ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                disabled={busy}
                trailingAction={(
                  <IconButton
                    size="sm"
                    icon={passwordVisible ? <EyeOff /> : <Eye />}
                    aria-label={passwordVisible ? "Parolayı gizle" : "Parolayı göster"}
                    aria-pressed={passwordVisible}
                    onClick={() => setPasswordVisible((visible) => !visible)}
                  />
                )}
                onChange={(event) => setPassword(event.target.value)}
              />
              {error && <Alert variant="error">{error}</Alert>}
              <Button type="submit" size="lg" loading={busy} fullWidth>Oturum aç</Button>
            </div>
            <p className="login-security-note"><ShieldCheck /> Bağlantınız ve oturum bilgileriniz güvenli biçimde korunur.</p>
          </form>
        </Card>
      </section>
    </main>
  );
}

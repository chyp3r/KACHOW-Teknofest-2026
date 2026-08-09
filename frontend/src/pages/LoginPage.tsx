import { LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../hooks/useAuth";
import { useSessionNotice } from "../hooks/useSessionNotice";
import { Button } from "../components/Button";
import { Input } from "../components/FormControls";
import { Alert, Card } from "../components/Surface";

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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
    <div className="page page-scroll">
      <PageHeader
        title="KACHOW oturumu"
        description="Evrak ve karar destek çalışma alanına erişmek için hesabınızla oturum açın."
      />
      <div className="login-wrap">
        <Card className="login-card" padding="prominent"><form onSubmit={(event) => void submit(event)}>
          <span className="login-icon">
            <LockKeyhole size={22} />
          </span>
          <h2>Oturum aç</h2>
          {sessionNotice && <Alert variant="warning">{sessionNotice}</Alert>}
          <div className="form-stack">
            <Input
                label="Kullanıcı adı veya e-posta"
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            <Input
                label="Parola"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            {error && (
              <p className="feedback error" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" loading={busy} fullWidth>Oturum aç</Button>
          </div>
        </form></Card>
      </div>
    </div>
  );
}

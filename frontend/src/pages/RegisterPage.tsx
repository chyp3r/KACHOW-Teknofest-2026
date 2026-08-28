import {
  Eye,
  EyeOff,
  FileBarChart,
  LockKeyhole,
  Mail,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { BrandLockup } from "../components/BrandLockup";
import { Button, IconButton } from "../components/Button";
import { Input } from "../components/FormControls";
import { Alert, Card } from "../components/Surface";
import { useAuth } from "../hooks/useAuth";
import { userService } from "../services/userService";

//: The backend replies in plain English (see UserService.register_user) --
//: this app is otherwise entirely Turkish, so known messages get a local
//: translation; anything unrecognised still falls through to the raw
//: message rather than hiding it.
const KNOWN_ERROR_MESSAGES: Record<string, string> = {
  "Username is already taken.": "Bu kullanıcı adı zaten alınmış.",
  "Email address is already in use.": "Bu e-posta adresi zaten kullanımda.",
  "This email address has not been invited by a system administrator.":
    "Bu e-posta adresi bir yöneticiniz tarafından davet edilmedi. Lütfen kurumunuzun yöneticisiyle iletişime geçin.",
};

function registerErrorMessage(caught: unknown): string {
  if (caught instanceof Error) {
    return KNOWN_ERROR_MESSAGES[caught.message] ?? caught.message;
  }
  return "Kayıt tamamlanamadı.";
}

export function RegisterPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Parolalar eşleşmiyor.");
      return;
    }
    setBusy(true);
    try {
      await userService.register(username, email, password);
      // Registration returns the created account, not a session -- log
      // in with the same credentials right away so the user lands in the
      // app instead of being sent back to a login form they just filled.
      await login(username, password);
    } catch (caught) {
      setError(registerErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-intro" aria-labelledby="register-intro-title">
        <BrandLockup />
        <div className="login-intro-copy">
          <span className="eyebrow">Kurumsal karar destek platformu</span>
          <h1 id="register-intro-title">Doğru veri.<br />Doğru analiz.<br />Doğru karar.</h1>
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

      <section className="login-form-region" aria-labelledby="register-title">
        <Card className="login-card" padding="prominent">
          <form onSubmit={(event) => void submit(event)}>
            <div className="login-form-heading"><div><h2 id="register-title">Kayıt ol</h2><p>Davet edildiyseniz hesabınızı oluşturun.</p></div></div>
            <div className="form-stack">
              <Input
                label="Kullanıcı adı"
                leadingIcon={<UserRound />}
                autoComplete="username"
                required
                value={username}
                disabled={busy}
                onChange={(event) => setUsername(event.target.value)}
              />
              <Input
                label="E-posta"
                type="email"
                leadingIcon={<Mail />}
                autoComplete="email"
                required
                value={email}
                disabled={busy}
                onChange={(event) => setEmail(event.target.value)}
              />
              <Input
                label="Parola"
                leadingIcon={<LockKeyhole />}
                type={passwordVisible ? "text" : "password"}
                autoComplete="new-password"
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
              <Input
                label="Parola (Tekrar)"
                leadingIcon={<LockKeyhole />}
                type={passwordVisible ? "text" : "password"}
                autoComplete="new-password"
                required
                value={confirmPassword}
                disabled={busy}
                onChange={(event) => setConfirmPassword(event.target.value)}
              />
              {error && <Alert variant="error">{error}</Alert>}
              <Button type="submit" size="lg" loading={busy} fullWidth>Kayıt ol</Button>
            </div>
            <p className="login-security-note"><ShieldCheck /> Bağlantınız ve oturum bilgileriniz güvenli biçimde korunur.</p>
            <p className="login-alt-action">Zaten hesabınız var mı? <Link to="/login">Oturum aç</Link></p>
          </form>
        </Card>
      </section>
    </main>
  );
}

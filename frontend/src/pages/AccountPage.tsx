import { CheckCircle2, KeyRound, Monitor, Moon, ShieldCheck, Sun, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { useAccount } from "../hooks/useAccount";
import { useAuth } from "../hooks/useAuth";
import { SENSITIVITY_LABELS } from "../types/security";
import { ROLE_LABELS } from "../types/users";
import { Button } from "../components/Button";
import { Input } from "../components/FormControls";
import { FormActions } from "../components/LayoutPrimitives";
import { Alert, Card } from "../components/Surface";
import { StatusBadge } from "../components/StatusBadge";
import { useTheme } from "../hooks/useTheme";

export function AccountPage() {
  const { user } = useAuth();
  const { mode, setMode } = useTheme();
  const account = useAccount();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordAgain, setNewPasswordAgain] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (newPassword !== newPasswordAgain) {
      setValidationError("Yeni parola alanları birbiriyle eşleşmiyor.");
      return;
    }
    await account.changePassword({ currentPassword, newPassword });
    setCurrentPassword("");
    setNewPassword("");
    setNewPasswordAgain("");
    setValidationError(null);
  };
  return (
    <div className="page page-scroll">
      <PageHeader title="Hesabım" description="Profilinizi görüntüleyin ve parolanızı güvenli biçimde değiştirin." />
      <div className="account-layout">
        <div className="account-summary-column">
          <Card className="profile-summary" padding="prominent">
            <div className="profile-summary-heading">
              <span className="profile-avatar" aria-hidden="true"><UserRound /></span>
              <div><h2>{user?.username}</h2><p>{user?.email}</p></div>
              <StatusBadge tone={user?.is_active ? "success" : "neutral"}>{user?.is_active ? "Aktif" : "Erişim kapalı"}</StatusBadge>
            </div>
            <dl className="metadata-grid">
              <div><dt>Rol</dt><dd>{user ? ROLE_LABELS[user.role] : "—"}</dd></div>
              <div><dt>Gizlilik yetkisi</dt><dd>{user ? SENSITIVITY_LABELS[user.clearance_level] : "—"}</dd></div>
              <div><dt>Kullanıcı adı</dt><dd>{user?.username ?? "—"}</dd></div>
              <div><dt>Kurum hesabı</dt><dd>{user?.company_id ? "Kuruma bağlı" : "Sistem hesabı"}</dd></div>
            </dl>
          </Card>
          <Card className="appearance-card" padding="default">
            <div className="section-heading"><div><span className="eyebrow">Görünüm</span><h2>Tema tercihi</h2><p>Arayüz düzeni değişmeden renkler seçiminize uyarlanır.</p></div></div>
            <div className="appearance-options" role="group" aria-label="Tema tercihi">
              <Button variant={mode === "system" ? "secondary" : "ghost"} aria-pressed={mode === "system"} leadingIcon={<Monitor />} onClick={() => setMode("system")}>Sistem</Button>
              <Button variant={mode === "light" ? "secondary" : "ghost"} aria-pressed={mode === "light"} leadingIcon={<Sun />} onClick={() => setMode("light")}>Açık</Button>
              <Button variant={mode === "dark" ? "secondary" : "ghost"} aria-pressed={mode === "dark"} leadingIcon={<Moon />} onClick={() => setMode("dark")}>Koyu</Button>
            </div>
          </Card>
        </div>
        <Card className="password-card" padding="prominent"><form className="form-stack" onSubmit={(event) => void submit(event)}>
          <span className="eyebrow"><KeyRound size={15} />Parola yönetimi</span><h2>Parolayı değiştir</h2>
          <Input label="Mevcut parola" type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => { setCurrentPassword(event.target.value); account.reset(); }} />
          <Input label="Yeni parola" type="password" autoComplete="new-password" required minLength={8} value={newPassword} onChange={(event) => { setNewPassword(event.target.value); account.reset(); }} />
          <Input label="Yeni parola (tekrar)" type="password" autoComplete="new-password" required minLength={8} value={newPasswordAgain} onChange={(event) => { setNewPasswordAgain(event.target.value); setValidationError(null); account.reset(); }} />
          <ul className="password-rule-list" aria-label="Şifre güvenliği kuralları">
            <li className={newPassword.length >= 8 ? "is-valid" : undefined}><CheckCircle2 />En az 8 karakter</li>
            <li className={/[A-ZÇĞİÖŞÜ]/.test(newPassword) ? "is-valid" : undefined}><CheckCircle2 />Büyük harf içerir</li>
            <li className={/[a-zçğıöşü]/.test(newPassword) ? "is-valid" : undefined}><CheckCircle2 />Küçük harf içerir</li>
            <li className={/\d/.test(newPassword) ? "is-valid" : undefined}><CheckCircle2 />Rakam içerir</li>
          </ul>
          <div className="password-guidance"><ShieldCheck /><span><strong>Güçlü parola kullanın</strong><small>Kurum hesabınızın parolasını paylaşmayın.</small></span></div>
          {validationError && <Alert variant="error">{validationError}</Alert>}
          <ApiErrorNotice error={account.errorObject ?? account.error} />
          {account.passwordChanged && <Alert variant="success">Parolanız değiştirildi.</Alert>}
          <FormActions><Button type="submit" loading={account.changingPassword}>Parolayı değiştir</Button></FormActions>
        </form></Card>
      </div>
    </div>
  );
}

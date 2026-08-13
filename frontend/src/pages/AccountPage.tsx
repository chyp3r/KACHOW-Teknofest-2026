import { KeyRound } from "lucide-react";
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

export function AccountPage() {
  const { user } = useAuth();
  const account = useAccount();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await account.changePassword({ currentPassword, newPassword });
    setCurrentPassword("");
    setNewPassword("");
  };
  return (
    <div className="page page-scroll">
      <PageHeader title="Hesabım" description="Profilinizi görüntüleyin ve parolanızı güvenli biçimde değiştirin." />
      <div className="account-layout">
        <Card padding="prominent"><h2>{user?.username}</h2><p>{user?.email}</p><dl className="metadata-grid"><div><dt>Rol</dt><dd>{user ? ROLE_LABELS[user.role] : "—"}</dd></div><div><dt>Gizlilik yetkisi</dt><dd>{user ? SENSITIVITY_LABELS[user.clearance_level] : "—"}</dd></div></dl></Card>
        <Card padding="prominent"><form className="form-stack" onSubmit={(event) => void submit(event)}>
          <span className="eyebrow"><KeyRound size={15} />Parola yönetimi</span><h2>Parolayı değiştir</h2>
          <Input label="Mevcut parola" type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => { setCurrentPassword(event.target.value); account.reset(); }} />
          <Input label="Yeni parola" type="password" autoComplete="new-password" required minLength={8} value={newPassword} onChange={(event) => { setNewPassword(event.target.value); account.reset(); }} />
          <ApiErrorNotice error={account.errorObject ?? account.error} />
          {account.passwordChanged && <Alert variant="success">Parolanız değiştirildi.</Alert>}
          <FormActions><Button type="submit" loading={account.changingPassword}>Parolayı değiştir</Button></FormActions>
        </form></Card>
      </div>
    </div>
  );
}

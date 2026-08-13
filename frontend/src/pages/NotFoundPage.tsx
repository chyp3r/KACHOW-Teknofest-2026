import { FileQuestion } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";

export function NotFoundPage() {
  return <div className="page centered-state"><EmptyState icon={FileQuestion} title="Sayfa bulunamadı" description="Adres değişmiş veya sayfa kaldırılmış olabilir." /><Link className="button button-primary" to="/chats">Sohbetlere dön</Link></div>;
}

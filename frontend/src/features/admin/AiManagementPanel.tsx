import { Bot, GraduationCap, MessageSquareText } from "lucide-react";
import { useState } from "react";
import { Tabs } from "../../components/Tabs";
import { TrainingPanel } from "./TrainingPanel";
import { FeedbackPanel } from "./FeedbackPanel";
import { AdapterPanel } from "./AdapterPanel";

type Tab = "training" | "feedback" | "adapter";
export function AiManagementPanel({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const [tab, setTab] = useState<Tab>("training");
  return <div className="admin-section"><Tabs label="AI yönetimi" active={tab} onChange={setTab} items={[{ id: "training", label: "Eğitim", icon: <GraduationCap /> }, { id: "feedback", label: "Geri Bildirimler", icon: <MessageSquareText /> }, { id: "adapter", label: "Model Ayarları", icon: <Bot /> }]} />{tab === "training" && <TrainingPanel companyId={companyId} canManage={canManage} />}{tab === "feedback" && <FeedbackPanel companyId={companyId} />}{tab === "adapter" && <AdapterPanel companyId={companyId} canManage={canManage} />}</div>;
}

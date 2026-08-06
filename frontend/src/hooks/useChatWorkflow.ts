import { useCallback, useRef, useState } from "react";
import { chatService } from "../services/chatService";
import type {
  ChatMessage,
  InterruptState,
  WorkflowEvent,
  WorkflowLog,
  WorkflowNodeStatus,
} from "../types/chat";
import type { DocumentMetadata, ReasoningLevel } from "../types/documents";

type NodeResults = Record<string, Record<string, unknown>>;

export function useChatWorkflow(selectedDocument: DocumentMetadata | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pendingInterrupt, setPendingInterrupt] =
    useState<InterruptState | null>(null);
  const [nodeStatus, setNodeStatus] = useState<
    Record<string, WorkflowNodeStatus>
  >({});
  const [nodeResults, setNodeResults] = useState<NodeResults>({});
  const [nodeMeta, setNodeMeta] = useState<NodeResults>({});
  const [planSteps, setPlanSteps] = useState<string[]>([]);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const logsRef = useRef<WorkflowLog[]>([]);
  const seenInterrupts = useRef(new Set<string>());

  const appendLog = useCallback((text: string) => {
    const next = [
      ...logsRef.current,
      { time: new Date().toLocaleTimeString("tr-TR"), text },
    ];
    logsRef.current = next;
    setLogs(next);
  }, []);

  const resetFlow = useCallback(() => {
    setStreamingText("");
    setNodeStatus({});
    setNodeResults({});
    setNodeMeta({});
    setPlanSteps([]);
    logsRef.current = [];
    setLogs([]);
  }, []);

  const handleEvent = useCallback(
    (event: WorkflowEvent) => {
      switch (event.event) {
        case "session":
          setSessionId(event.thread_id);
          break;
        case "node_start":
          setNodeStatus((previous) => ({
            ...previous,
            [event.node]: "running",
          }));
          if (event.meta)
            setNodeMeta((previous) => ({
              ...previous,
              [event.node]: event.meta ?? {},
            }));
          if (event.node === "draft") setStreamingText("");
          appendLog(`${event.label} işlemi başlatıldı.`);
          break;
        case "planning_completed": {
          const planned = event.plan_steps.map((step) => step.toLowerCase());
          setPlanSteps(planned);
          setNodeStatus((previous) => ({ ...previous, planning: "completed" }));
          appendLog(
            `İşlem planı belirlendi: ${planned.join(" → ") || "genel sohbet"}.`,
          );
          break;
        }
        case "node_end":
          setNodeStatus((previous) => ({
            ...previous,
            [event.node]: "completed",
          }));
          if (event.result)
            setNodeResults((previous) => ({
              ...previous,
              [event.node]: {
                ...(previous[event.node] ?? {}),
                ...event.result,
              },
            }));
          if (event.meta)
            setNodeMeta((previous) => ({
              ...previous,
              [event.node]: event.meta ?? {},
            }));
          appendLog(`${event.label} tamamlandı.`);
          break;
        case "node_error":
          setNodeStatus((previous) => ({
            ...previous,
            [event.node]: event.fatal
              ? "failed"
              : (previous[event.node] ?? "completed"),
          }));
          appendLog(
            `${event.fatal ? "Hata" : "Uyarı"} (${event.label}): ${event.message}`,
          );
          break;
        case "node_skipped":
          setNodeStatus((previous) => ({
            ...previous,
            [event.node]: "skipped",
          }));
          appendLog(`${event.label} atlandı: ${event.reason}`);
          break;
        case "token":
          setStreamingText((previous) => previous + event.text);
          break;
        case "partial_result":
          setNodeResults((previous) => ({
            ...previous,
            [event.key]: { ...(previous[event.key] ?? {}), ...event.value },
          }));
          break;
        case "interrupt":
          if (seenInterrupts.current.has(event.interrupt_id)) break;
          seenInterrupts.current.add(event.interrupt_id);
          setPendingInterrupt({
            kind: event.kind,
            interruptId: event.interrupt_id,
            payload: event.payload,
          });
          setNodeStatus((previous) => ({ ...previous, human_gate: "running" }));
          appendLog(
            event.kind === "missing_information"
              ? "Eksik bilgi bekleniyor."
              : "İnsan onayı bekleniyor.",
          );
          break;
        case "final_result":
          setStreamingText("");
          setMessages((previous) => [
            ...previous,
            {
              sender: "assistant",
              text: event.reply,
              status: event.workflow_status,
              logs: logsRef.current,
              details: event.details,
            },
          ]);
          break;
        case "error":
          appendLog(`Hata: ${event.message}`);
          setMessages((previous) => [
            ...previous,
            {
              sender: "assistant",
              text: `İşlem tamamlanamadı: ${event.message}`,
              status: "FAILED",
              logs: logsRef.current,
            },
          ]);
          break;
      }
    },
    [appendLog],
  );

  const send = useCallback(
    async (
      text: string,
      reasoningLevel: ReasoningLevel,
      useDocument: boolean,
    ) => {
      if (!text.trim() || loading) return;
      setLoading(true);
      setPendingInterrupt(null);
      resetFlow();
      setMessages((previous) => [
        ...previous,
        { sender: "user", text: text.trim() },
      ]);
      try {
        await chatService.send(
          {
            message: text.trim(),
            session_id: sessionId,
            document_id: useDocument
              ? (selectedDocument?.storage_path ?? null)
              : null,
            reasoning_level: reasoningLevel,
          },
          handleEvent,
        );
      } catch (caught) {
        setMessages((previous) => [
          ...previous,
          {
            sender: "assistant",
            text:
              caught instanceof Error
                ? caught.message
                : "İletişim sırasında bir hata oluştu.",
            status: "FAILED",
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [handleEvent, loading, resetFlow, selectedDocument, sessionId],
  );

  const resume = useCallback(
    async (
      action: "answer" | "approve" | "revise" | "reject",
      answers: Record<string, string>,
      instructions: string,
    ) => {
      if (!sessionId || !pendingInterrupt) return;
      setLoading(true);
      resetFlow();
      try {
        setPendingInterrupt(null);
        await chatService.resume(
          { session_id: sessionId, action, answers, instructions },
          handleEvent,
        );
      } catch (caught) {
        setMessages((previous) => [
          ...previous,
          {
            sender: "assistant",
            text:
              caught instanceof Error
                ? caught.message
                : "Devam işlemi tamamlanamadı.",
            status: "FAILED",
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [handleEvent, pendingInterrupt, resetFlow, sessionId],
  );

  const newChat = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setPendingInterrupt(null);
    seenInterrupts.current.clear();
    resetFlow();
  }, [resetFlow]);

  const addUploadMessage = useCallback(
    (fileName: string) =>
      setMessages((previous) => [
        ...previous,
        {
          sender: "assistant",
          text: `“${fileName}” evrakı yüklendi ve analiz edildi. Sohbette kullanmak için evrak seçimini açık bırakın.`,
        },
      ]),
    [],
  );

  return {
    messages,
    loading,
    streamingText,
    pendingInterrupt,
    nodeStatus,
    nodeResults,
    nodeMeta,
    planSteps,
    logs,
    send,
    resume,
    newChat,
    addUploadMessage,
  };
}

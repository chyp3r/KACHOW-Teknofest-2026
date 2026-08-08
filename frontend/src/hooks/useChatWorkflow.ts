import { useCallback, useEffect, useRef, useState } from "react";
import { chatService } from "../services/chatService";
import type {
  ChatMessage,
  GuardrailEvent,
  InterruptState,
  ToolCallEvent,
  WorkflowEvent,
  WorkflowLog,
  WorkflowNodeStatus,
} from "../types/chat";
import type { DocumentMetadata, ReasoningLevel } from "../types/documents";

type NodeResults = Record<string, Record<string, unknown>>;

interface StoredSession {
  clientSessionId: string;
  threadId: string | null;
}

function createClientSessionId(): string {
  return `web:${crypto.randomUUID()}`;
}

function sessionStorageKey(userId: string): string {
  return `kachow.chat.session.${userId}`;
}

function loadSession(userId: string): StoredSession {
  try {
    const value = localStorage.getItem(sessionStorageKey(userId));
    if (value) {
      const parsed = JSON.parse(value) as Partial<StoredSession>;
      if (typeof parsed.clientSessionId === "string") {
        return {
          clientSessionId: parsed.clientSessionId,
          threadId: typeof parsed.threadId === "string" ? parsed.threadId : null,
        };
      }
    }
  } catch {
    // Storage can be unavailable in private browsing; a memory-only session is fine.
  }
  return { clientSessionId: createClientSessionId(), threadId: null };
}

export function useChatWorkflow(
  selectedDocument: DocumentMetadata | null,
  userId: string,
) {
  const [initialSession] = useState<StoredSession>(() => loadSession(userId));
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [clientSessionId, setClientSessionId] = useState(
    initialSession.clientSessionId,
  );
  const [threadId, setThreadId] = useState<string | null>(
    initialSession.threadId,
  );
  const [pendingInterrupt, setPendingInterrupt] =
    useState<InterruptState | null>(null);
  const [nodeStatus, setNodeStatus] = useState<
    Record<string, WorkflowNodeStatus>
  >({});
  const [nodeResults, setNodeResults] = useState<NodeResults>({});
  const [nodeMeta, setNodeMeta] = useState<NodeResults>({});
  const [planSteps, setPlanSteps] = useState<string[]>([]);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallEvent[]>([]);
  const [guardrailEvents, setGuardrailEvents] = useState<GuardrailEvent[]>([]);
  const logsRef = useRef<WorkflowLog[]>([]);
  const seenInterrupts = useRef(new Set<string>());
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(
        sessionStorageKey(userId),
        JSON.stringify({ clientSessionId, threadId }),
      );
    } catch {
      // Continue with an in-memory session when persistent storage is unavailable.
    }
  }, [clientSessionId, threadId, userId]);

  useEffect(() => {
    if (!threadId) return;
    let active = true;
    chatService
      .state(threadId)
      .then((state) => {
        if (!active || state.status !== "interrupted" || !state.interrupt) return;
        const { kind: recoveredKind, ...payload } = state.interrupt;
        const kind =
          recoveredKind ??
          ((payload.questions?.length ?? 0) > 0
            ? "missing_information"
            : "draft_approval");
        const recoveredId = `recovered:${threadId}`;
        seenInterrupts.current.add(recoveredId);
        setPendingInterrupt({ kind, interruptId: recoveredId, payload });
        setNodeStatus((previous) => ({ ...previous, human_gate: "running" }));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [threadId]);

  useEffect(
    () => () => {
      activeRequest.current?.abort();
    },
    [],
  );

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
    setToolCalls([]);
    setGuardrailEvents([]);
    logsRef.current = [];
    setLogs([]);
  }, []);

  const handleEvent = useCallback(
    (event: WorkflowEvent) => {
      switch (event.event) {
        case "session":
          setThreadId(event.thread_id);
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
        case "tool_call":
          setToolCalls((previous) => [
            ...previous,
            { node: event.node, tool: event.tool, args: event.args },
          ]);
          appendLog(`Araç çağrıldı: ${event.tool}.`);
          break;
        case "guardrail":
          setGuardrailEvents((previous) => [
            ...previous,
            {
              stage: event.stage,
              kind: event.kind,
              decision: event.decision,
              reasons: event.reasons,
            },
          ]);
          appendLog(`Güvenlik kontrolü: ${event.decision}.`);
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
          setPendingInterrupt(null);
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
      const controller = new AbortController();
      activeRequest.current = controller;
      try {
        await chatService.send(
          {
            message: text.trim(),
            session_id: clientSessionId,
            document_id: useDocument
              ? (selectedDocument?.storage_path ?? null)
              : null,
            reasoning_level: reasoningLevel,
          },
          handleEvent,
          controller.signal,
        );
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
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
        if (activeRequest.current === controller) activeRequest.current = null;
        setLoading(false);
      }
    },
    [clientSessionId, handleEvent, loading, resetFlow, selectedDocument],
  );

  const resume = useCallback(
    async (
      action: "answer" | "approve" | "revise" | "reject",
      answers: Record<string, string>,
      instructions: string,
      reason?: string,
    ) => {
      if (!threadId || !pendingInterrupt || loading) return;
      setLoading(true);
      resetFlow();
      const controller = new AbortController();
      activeRequest.current = controller;
      try {
        setPendingInterrupt(null);
        await chatService.resume(
          { session_id: threadId, action, answers, instructions, reason },
          // The gate's own "revizyon iste" loop (see backend
          // planning_graph.gate_revise_node) can re-interrupt within this
          // same stream -- handleEvent's "interrupt" case already re-opens
          // the panel for a round it hasn't seen (dedup keys on
          // interrupt_id, which the backend varies per round), so no extra
          // handling is needed here beyond passing events through.
          handleEvent,
          controller.signal,
        );
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setPendingInterrupt(pendingInterrupt);
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
        if (activeRequest.current === controller) activeRequest.current = null;
        setLoading(false);
      }
    },
    [handleEvent, loading, pendingInterrupt, resetFlow, threadId],
  );

  const newChat = useCallback(() => {
    activeRequest.current?.abort();
    setMessages([]);
    setClientSessionId(createClientSessionId());
    setThreadId(null);
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
    toolCalls,
    guardrailEvents,
    send,
    resume,
    newChat,
    addUploadMessage,
  };
}

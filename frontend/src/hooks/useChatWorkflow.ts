import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { chatService } from "../services/chatService";
import type {
  ChatMessage,
  GuardrailEvent,
  InterruptState,
  PersistedChatMessage,
  PromptQuestion,
  ToolCallEvent,
  WorkflowEvent,
  WorkflowLog,
  WorkflowNodeStatus,
} from "../types/chat";
import type { DocumentMetadata, ReasoningLevel } from "../types/documents";

type NodeResults = Record<string, Record<string, unknown>>;

function createClientSessionId(): string {
  return `web:${crypto.randomUUID()}`;
}

function clientSessionId(threadId: string, userId: string): string {
  const prefix = `${userId}:`;
  return threadId.startsWith(prefix) ? threadId.slice(prefix.length) : threadId;
}

function toChatMessage(message: PersistedChatMessage): ChatMessage {
  return {
    id: message.id,
    sender: message.role,
    text: message.content,
    status: message.workflow_status ?? undefined,
    details: message.details ?? undefined,
  };
}

export function useChatWorkflow(
  selectedDocument: DocumentMetadata | null,
  userId: string,
  activeSessionId: string | null = null,
  onSessionResolved?: (sessionId: string) => void,
) {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [clientId, setClientId] = useState(() =>
    activeSessionId ? clientSessionId(activeSessionId, userId) : createClientSessionId(),
  );
  const [threadId, setThreadId] = useState<string | null>(activeSessionId);
  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptState | null>(null);
  const [nodeStatus, setNodeStatus] = useState<Record<string, WorkflowNodeStatus>>({});
  const [nodeResults, setNodeResults] = useState<NodeResults>({});
  const [nodeMeta, setNodeMeta] = useState<NodeResults>({});
  const [planSteps, setPlanSteps] = useState<string[]>([]);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallEvent[]>([]);
  const [guardrailEvents, setGuardrailEvents] = useState<GuardrailEvent[]>([]);
  const logsRef = useRef<WorkflowLog[]>([]);
  const threadIdRef = useRef<string | null>(activeSessionId);
  const seenInterrupts = useRef(new Set<string>());
  const activeRequest = useRef<AbortController | null>(null);
  const internallyResolvedSession = useRef<string | null>(null);
  // Set by the last "question" event this turn, consumed once by the very
  // next "final_result" (the clarify step's own reply) and cleared -- a
  // question is always answered by the turn that asked it, so nothing else
  // should ever attach these options to an unrelated later message.
  const pendingQuestions = useRef<PromptQuestion[] | null>(null);

  const sessionsQuery = useQuery({
    queryKey: queryKeys.chatSessions(),
    queryFn: () => chatService.sessions(),
    staleTime: 15_000,
  });
  const messagesQuery = useQuery({
    queryKey: queryKeys.chatMessages(threadId ?? ""),
    queryFn: () => chatService.messages(threadId!),
    enabled: Boolean(threadId) && !loading,
  });
  const stateQuery = useQuery({
    queryKey: queryKeys.chatState(threadId ?? ""),
    queryFn: () => chatService.state(threadId!),
    enabled: Boolean(threadId) && !loading,
    staleTime: 0,
  });

  useEffect(() => {
    if (
      activeSessionId &&
      internallyResolvedSession.current === activeSessionId
    ) {
      internallyResolvedSession.current = null;
      threadIdRef.current = activeSessionId;
      setThreadId(activeSessionId);
      return;
    }
    internallyResolvedSession.current = null;
    activeRequest.current?.abort();
    threadIdRef.current = activeSessionId;
    setThreadId(activeSessionId);
    setClientId(
      activeSessionId ? clientSessionId(activeSessionId, userId) : createClientSessionId(),
    );
    setMessages([]);
    setPendingInterrupt(null);
    seenInterrupts.current.clear();
  }, [activeSessionId, userId]);

  useEffect(() => {
    if (messagesQuery.data && !activeRequest.current) {
      setMessages(messagesQuery.data.items.map(toChatMessage));
    }
  }, [messagesQuery.data]);

  useEffect(() => {
    const state = stateQuery.data;
    if (!threadId || state?.status !== "interrupted" || !state.interrupt) return;
    const { kind: recoveredKind, ...payload } = state.interrupt;
    const kind =
      recoveredKind ??
      ((payload.questions?.length ?? 0) > 0 ? "missing_information" : "draft_approval");
    const recoveredId = `recovered:${threadId}`;
    setPendingInterrupt({ kind, interruptId: recoveredId, payload });
    setNodeStatus((previous) => ({ ...previous, human_gate: "running" }));
  }, [stateQuery.data, threadId]);

  useEffect(() => () => activeRequest.current?.abort(), []);

  const appendLog = useCallback((text: string) => {
    const next = [...logsRef.current, { time: new Date().toLocaleTimeString("tr-TR"), text }];
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
    pendingQuestions.current = null;
  }, []);

  const refreshServerState = useCallback(
    (resolvedThreadId: string) => {
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", resolvedThreadId] });
      void queryClient.invalidateQueries({ queryKey: ["chat-state", resolvedThreadId] });
      void queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
    [queryClient],
  );

  const handleEvent = useCallback(
    (event: WorkflowEvent) => {
      switch (event.event) {
        case "session":
          internallyResolvedSession.current = event.thread_id;
          threadIdRef.current = event.thread_id;
          setThreadId(event.thread_id);
          onSessionResolved?.(event.thread_id);
          break;
        case "node_start":
          setNodeStatus((previous) => ({ ...previous, [event.node]: "running" }));
          if (event.meta) setNodeMeta((previous) => ({ ...previous, [event.node]: event.meta ?? {} }));
          // Every node_start clears any in-progress streamingText, not just
          // "draft"'s -- a revise round (the initial rewrite, then every
          // repair/multi-directive re-entry into the same "revise" node)
          // starts fresh each time. Without this, a second round's tokens
          // appended onto the first round's leftover text instead of
          // replacing it.
          setStreamingText("");
          appendLog(`${event.label} işlemi başlatıldı.`);
          break;
        case "planning_completed":
          setPlanSteps(event.plan_steps.map((step) => step.toLowerCase()));
          setNodeStatus((previous) => ({ ...previous, planning: "completed" }));
          appendLog(`İşlem planı belirlendi: ${event.plan_steps.join(" → ") || "genel sohbet"}.`);
          break;
        case "node_end":
          setNodeStatus((previous) => ({ ...previous, [event.node]: "completed" }));
          if (event.result) setNodeResults((previous) => ({ ...previous, [event.node]: { ...(previous[event.node] ?? {}), ...event.result } }));
          if (event.meta) setNodeMeta((previous) => ({ ...previous, [event.node]: event.meta ?? {} }));
          appendLog(`${event.label} tamamlandı.`);
          break;
        case "node_error":
          setNodeStatus((previous) => ({ ...previous, [event.node]: event.fatal ? "failed" : (previous[event.node] ?? "completed") }));
          appendLog(`${event.fatal ? "Hata" : "Uyarı"} (${event.label}): ${event.message}`);
          break;
        case "node_skipped":
          setNodeStatus((previous) => ({ ...previous, [event.node]: "skipped" }));
          appendLog(`${event.label} atlandı: ${event.reason}`);
          break;
        case "token":
          setStreamingText((previous) => previous + event.text);
          break;
        case "partial_result":
          if (typeof event.value === "object" && event.value !== null)
            setNodeResults((previous) => ({ ...previous, [event.key]: { ...(previous[event.key] ?? {}), ...event.value } }));
          break;
        case "tool_call":
          setToolCalls((previous) => [...previous, { node: event.node, tool: event.tool, args: event.args }]);
          appendLog(`Araç çağrıldı: ${event.tool}.`);
          break;
        case "guardrail":
          setGuardrailEvents((previous) => [...previous, { stage: event.stage, kind: event.kind, decision: event.decision, reasons: event.reasons }]);
          appendLog(`Güvenlik kontrolü: ${event.decision}.`);
          break;
        case "notice":
          // Its own chat message, appended immediately rather than folded
          // into whatever comes next -- a conflict finding is a heads-up
          // about an edit that already happened (see
          // app.ai.revision.conflict's applied_anyway invariant), not a
          // decision to block on, so it must never look like the
          // human-approval popup (pendingInterrupt) and must never wait for
          // final_result to be shown.
          setStreamingText("");
          setMessages((previous) => [
            ...previous,
            {
              sender: "assistant",
              text: `**${event.title}**\n\n${event.message}`,
              kind: "notice",
            },
          ]);
          appendLog(`Bilgilendirme: ${event.title}`);
          break;
        case "question":
          pendingQuestions.current =
            event.questions && event.questions.length > 0
              ? event.questions
              : [
                  {
                    key: event.node,
                    question: event.question,
                    options: event.options,
                    multi_select: false,
                    allow_free_text: event.allow_free_text,
                    required: true,
                  },
                ];
          appendLog("Netleştirme sorusu soruldu.");
          break;
        case "interrupt":
          if (seenInterrupts.current.has(event.interrupt_id)) break;
          seenInterrupts.current.add(event.interrupt_id);
          setPendingInterrupt({ kind: event.kind, interruptId: event.interrupt_id, payload: event.payload });
          setNodeStatus((previous) => ({ ...previous, human_gate: "running" }));
          appendLog(event.kind === "missing_information" ? "Eksik bilgi bekleniyor." : "İnsan onayı bekleniyor.");
          break;
        case "final_result": {
          setStreamingText("");
          setPendingInterrupt(null);
          const questions = pendingQuestions.current ?? undefined;
          pendingQuestions.current = null;
          setMessages((previous) => [
            ...previous,
            {
              sender: "assistant",
              text: event.reply,
              status: event.workflow_status,
              logs: logsRef.current,
              details: event.details,
              questions,
            },
          ]);
          if (threadIdRef.current) refreshServerState(threadIdRef.current);
          break;
        }
        case "error":
          appendLog(`Hata: ${event.message}`);
          setMessages((previous) => [...previous, { sender: "assistant", text: `İşlem tamamlanamadı: ${event.message}`, status: "FAILED", logs: logsRef.current }]);
          break;
      }
    },
    [appendLog, onSessionResolved, refreshServerState],
  );

  const send = useCallback(async (text: string, reasoningLevel: ReasoningLevel, useDocument: boolean) => {
    if (!text.trim() || loading || activeRequest.current) return;
    setLoading(true);
    setPendingInterrupt(null);
    resetFlow();
    setMessages((previous) => [...previous, { sender: "user", text: text.trim() }]);
    const controller = new AbortController();
    activeRequest.current = controller;
    try {
      await chatService.send({ message: text.trim(), session_id: clientId, document_id: useDocument ? (selectedDocument?.storage_path ?? null) : null, reasoning_level: reasoningLevel }, handleEvent, controller.signal);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setMessages((previous) => [...previous, { sender: "assistant", text: caught instanceof Error ? caught.message : "İletişim sırasında bir hata oluştu.", status: "FAILED" }]);
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
      setLoading(false);
    }
  }, [clientId, handleEvent, loading, resetFlow, selectedDocument]);

  const resume = useCallback(async (action: "answer" | "approve" | "revise" | "reject", answers: Record<string, string | string[]>, instructions: string, reason?: string) => {
    if (!threadId || !pendingInterrupt || loading || activeRequest.current) return;
    setLoading(true);
    const controller = new AbortController();
    activeRequest.current = controller;
    const currentInterrupt = pendingInterrupt;
    try {
      const state = await chatService.state(threadId);
      if (state.status !== "interrupted") throw new Error("Bekleyen onay artık geçerli değil. Oturum yenileniyor.");
      setPendingInterrupt(null);
      resetFlow();
      await chatService.resume({ session_id: threadId, action, answers, instructions, reason }, handleEvent, controller.signal);
      refreshServerState(threadId);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setPendingInterrupt(currentInterrupt);
      setMessages((previous) => [...previous, { sender: "assistant", text: caught instanceof Error ? caught.message : "Devam işlemi tamamlanamadı.", status: "FAILED" }]);
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
      setLoading(false);
    }
  }, [handleEvent, loading, pendingInterrupt, refreshServerState, resetFlow, threadId]);

  const newChat = useCallback(() => {
    activeRequest.current?.abort();
    internallyResolvedSession.current = null;
    setMessages([]);
    setClientId(createClientSessionId());
    threadIdRef.current = null;
    setThreadId(null);
    setPendingInterrupt(null);
    seenInterrupts.current.clear();
    resetFlow();
  }, [resetFlow]);

  const cancel = useCallback(() => activeRequest.current?.abort(), []);
  const addUploadMessage = useCallback((fileName: string) => setMessages((previous) => [...previous, { sender: "assistant", text: `“${fileName}” evrakı yüklendi ve analiz edildi.` }]), []);

  return {
    sessions: sessionsQuery.data?.items ?? [],
    sessionsLoading: sessionsQuery.isLoading,
    sessionsRefreshing: sessionsQuery.isFetching && !sessionsQuery.isLoading,
    sessionsError:
      sessionsQuery.error instanceof Error ? sessionsQuery.error.message : null,
    historyLoading: messagesQuery.isLoading || stateQuery.isLoading,
    historyError: messagesQuery.error instanceof Error ? messagesQuery.error.message : stateQuery.error instanceof Error ? stateQuery.error.message : null,
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
    cancel,
    addUploadMessage,
    refreshSessions: sessionsQuery.refetch,
    retrySessions: async () => {
      await sessionsQuery.refetch();
    },
    retryHistory: async () => {
      await Promise.all([
        ...(threadId ? [messagesQuery.refetch(), stateQuery.refetch()] : []),
      ]);
    },
  };
}

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
  // Backend-supplied Turkish label per node id (from node_start/end/error/
  // skipped's own `label`), plus the order nodes were first seen in -- the
  // dynamic workflow stepper (DecisionFlow) derives its stage list from
  // these instead of a hardcoded stage set, so a run only ever shows the
  // steps it actually took.
  const [nodeLabels, setNodeLabels] = useState<Record<string, string>>({});
  const [nodeOrder, setNodeOrder] = useState<string[]>([]);
  // Wall-clock timestamp (Date.now()) each node most recently started running
  // -- re-stamped on every node_start, including a re-entry (e.g. "draft"
  // running a second attempt), so the waiting-state UI's per-step timer
  // always reflects the current attempt rather than the first one.
  const [nodeStartedAt, setNodeStartedAt] = useState<Record<string, number>>({});
  // Wall-clock timestamp the current turn's request left the client -- reset
  // on every send/resume, distinct from nodeStartedAt so the waiting-state
  // UI can show a total-elapsed counter even before the first node_start
  // event has arrived.
  const [turnStartedAt, setTurnStartedAt] = useState<number | null>(null);
  const [planIntent, setPlanIntent] = useState("");
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
  // Mirrors `streamingText` synchronously (state updates don't commit
  // in time to read back within the same handler) -- final_result reads
  // this as "what the user was looking at a moment ago" to diff against
  // the settled reply, so a guardrail redaction animates in place instead
  // of the streamed draft just vanishing and reappearing edited.
  const streamingTextRef = useRef("");

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

  // Records a node's backend-supplied label and its first-seen order --
  // idempotent, since a node can re-enter (e.g. "revise" runs once per
  // repair round) without moving in the order or losing its label.
  const noteNode = useCallback((node: string, label: string) => {
    setNodeLabels((previous) => (previous[node] === label ? previous : { ...previous, [node]: label }));
    setNodeOrder((previous) => (previous.includes(node) ? previous : [...previous, node]));
  }, []);

  useEffect(() => {
    if (messagesQuery.data && !activeRequest.current) {
      setMessages(messagesQuery.data.items.map(toChatMessage));
    }
  }, [messagesQuery.data]);

  // Rehydrates the workflow stepper's plan/order from the last persisted
  // assistant message when a session is loaded from history (page reload,
  // opening an old conversation) -- there is no live SSE stream to derive it
  // from in that case, only final_result.details (see
  // event_schema.FinalResultEvent / planning_graph._compile_final_output).
  useEffect(() => {
    if (!messagesQuery.data || activeRequest.current) return;
    const items = messagesQuery.data.items;
    const lastAssistant = [...items].reverse().find((item) => item.role === "assistant");
    const details = lastAssistant?.details;
    const steps = details?.plan_steps;
    if (!Array.isArray(steps) || steps.length === 0) return;
    const normalizedSteps = steps.filter((step): step is string => typeof step === "string").map((step) => step.toLowerCase());
    if (normalizedSteps.length === 0) return;
    const failed = lastAssistant?.workflow_status === "FAILED";
    setPlanSteps(normalizedSteps);
    setPlanIntent(typeof details?.intent === "string" ? details.intent : "");
    setNodeOrder(normalizedSteps);
    setNodeStatus((previous) => {
      if (Object.keys(previous).length > 0) return previous;
      const seeded: Record<string, WorkflowNodeStatus> = {};
      for (const step of normalizedSteps) seeded[step] = failed ? "failed" : "completed";
      return seeded;
    });
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
    noteNode("human_gate", "İnsan Onayı");
  }, [noteNode, stateQuery.data, threadId]);

  useEffect(() => () => activeRequest.current?.abort(), []);

  const appendLog = useCallback((text: string) => {
    const next = [...logsRef.current, { time: new Date().toLocaleTimeString("tr-TR"), text }];
    logsRef.current = next;
    setLogs(next);
  }, []);

  const resetFlow = useCallback(() => {
    streamingTextRef.current = "";
    setStreamingText("");
    setNodeStatus({});
    setNodeResults({});
    setNodeMeta({});
    setPlanSteps([]);
    setNodeLabels({});
    setNodeOrder([]);
    setNodeStartedAt({});
    setTurnStartedAt(Date.now());
    setPlanIntent("");
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
          noteNode(event.node, event.label);
          setNodeStatus((previous) => ({ ...previous, [event.node]: "running" }));
          setNodeStartedAt((previous) => ({ ...previous, [event.node]: Date.now() }));
          if (event.meta) setNodeMeta((previous) => ({ ...previous, [event.node]: event.meta ?? {} }));
          // No node clears streamingText here anymore -- draft/revise/assist
          // no longer stream their own raw output (see backend
          // app.ai.workflows.events.emit_reply_stream's docstring: the
          // validated final reply is the only thing ever streamed, once,
          // from chat_service._enqueue_terminal_event). The progress
          // stepper (nodeStatus/nodeOrder) is what shows live progress
          // while a turn is in flight; the chat bubble stays empty until
          // the "token" case below starts filling in the real answer.
          appendLog(`${event.label} işlemi başlatıldı.`);
          break;
        case "planning_completed":
          setPlanSteps(event.plan_steps.map((step) => step.toLowerCase()));
          setPlanIntent(event.intent);
          setNodeStatus((previous) => ({ ...previous, planning: "completed" }));
          appendLog(`İşlem planı belirlendi: ${event.plan_steps.join(" → ") || "genel sohbet"}.`);
          break;
        case "node_end":
          noteNode(event.node, event.label);
          setNodeStatus((previous) => ({ ...previous, [event.node]: "completed" }));
          if (event.result) setNodeResults((previous) => ({ ...previous, [event.node]: { ...(previous[event.node] ?? {}), ...event.result } }));
          if (event.meta) setNodeMeta((previous) => ({ ...previous, [event.node]: event.meta ?? {} }));
          appendLog(`${event.label} tamamlandı.`);
          break;
        case "node_error":
          noteNode(event.node, event.label);
          setNodeStatus((previous) => ({ ...previous, [event.node]: event.fatal ? "failed" : (previous[event.node] ?? "completed") }));
          appendLog(`${event.fatal ? "Hata" : "Uyarı"} (${event.label}): ${event.message}`);
          break;
        case "node_skipped":
          noteNode(event.node, event.label);
          setNodeStatus((previous) => ({ ...previous, [event.node]: "skipped" }));
          appendLog(`${event.label} atlandı: ${event.reason}`);
          break;
        case "token":
          streamingTextRef.current += event.text;
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
          streamingTextRef.current = "";
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
          // The "token" case above already streamed this exact text in (see
          // emit_reply_stream's docstring) -- streamingText and event.reply
          // are the same string by construction, so there is nothing left
          // to diff. Clearing the preview and appending the real message is
          // a plain hand-off, not a replace.
          streamingTextRef.current = "";
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
    [appendLog, noteNode, onSessionResolved, refreshServerState],
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
    nodeLabels,
    nodeOrder,
    nodeStartedAt,
    turnStartedAt,
    planIntent,
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

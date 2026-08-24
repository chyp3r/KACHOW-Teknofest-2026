import { createElement, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChatWorkflow } from "./useChatWorkflow";

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  resume: vi.fn(),
  state: vi.fn(),
  sessions: vi.fn(),
  messages: vi.fn(),
}));

vi.mock("../services/chatService", () => ({ chatService: mocks }));

describe("useChatWorkflow", () => {
  function wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return createElement(QueryClientProvider, { client }, children);
  }

  beforeEach(() => {
    mocks.send.mockReset();
    mocks.resume.mockReset();
    mocks.sessions.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    mocks.messages.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
    mocks.state.mockReset().mockResolvedValue({ status: "idle", interrupt: null });
    mocks.send.mockImplementation(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({
        event: "final_result",
        reply: "tamam",
        workflow_status: "COMPLETED",
      });
    });
  });

  it("keeps the client session id separate from the prefixed backend thread id", async () => {
    const onSessionResolved = vi.fn();
    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", null, onSessionResolved),
      { wrapper },
    );

    await act(() => result.current.send("ilk", "balanced", false));
    await act(() => result.current.send("ikinci", "balanced", false));

    const firstSession = mocks.send.mock.calls[0][0].session_id as string;
    const secondSession = mocks.send.mock.calls[1][0].session_id as string;
    expect(firstSession).toMatch(/^web:/);
    expect(secondSession).toBe(firstSession);
    expect(secondSession).not.toContain("user-1:");
    expect(onSessionResolved).toHaveBeenCalledWith("user-1:web:thread");
  });

  it("sends an explicitly selected draft as revision context", async () => {
    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1"),
      { wrapper },
    );

    await act(() => result.current.send(
      "Üslubu sadeleştir",
      "balanced",
      false,
      undefined,
      "draft-1",
    ));

    expect(mocks.send.mock.calls[0][0]).toMatchObject({
      document_id: null,
      draft_id: "draft-1",
    });
  });

  it("preserves the active stream when the first session event updates the route", async () => {
    let continueStream: (() => void) | undefined;
    let receivedSignal: AbortSignal | undefined;
    mocks.send.mockImplementation(async (_request, onEvent, signal: AbortSignal) => {
      receivedSignal = signal;
      onEvent({ event: "session", thread_id: "user-1:web:resolved" });
      await new Promise<void>((resolve) => {
        continueStream = resolve;
      });
      if (signal.aborted) throw new DOMException("cancelled", "AbortError");
      onEvent({
        event: "final_result",
        reply: "Yanıt korundu",
        workflow_status: "COMPLETED",
      });
    });

    const { result } = renderHook(() => {
      const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
      const workflow = useChatWorkflow(
        null,
        "user-1",
        activeSessionId,
        setActiveSessionId,
      );
      return { activeSessionId, workflow };
    }, { wrapper });

    let pending!: Promise<void>;
    act(() => {
      pending = result.current.workflow.send("İlk mesaj", "balanced", false);
    });

    await waitFor(() =>
      expect(result.current.activeSessionId).toBe("user-1:web:resolved"),
    );
    expect(receivedSignal?.aborted).toBe(false);
    expect(result.current.workflow.messages).toEqual([
      { sender: "user", text: "İlk mesaj" },
    ]);

    await act(async () => {
      continueStream?.();
      await pending;
    });

    expect(receivedSignal?.aborted).toBe(false);
    expect(result.current.workflow.messages.map((message) => message.text)).toEqual([
      "İlk mesaj",
      "Yanıt korundu",
    ]);
  });

  it("recovers persisted messages and a pending interrupt from the server", async () => {
    mocks.messages.mockResolvedValue({
      items: [{
        id: "message-1",
        role: "assistant",
        content: "Önceki yanıt",
        workflow_status: "INTERRUPTED",
        details: null,
        created_at: "2026-08-09T10:00:00Z",
      }],
      total: 1,
      page: 1,
      page_size: 50,
    });
    mocks.state.mockResolvedValue({
      status: "interrupted",
      interrupt: {
        kind: "missing_information",
        questions: [{ key: "muhatap", label: "Muhatap", required: true }],
      },
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:client"),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.pendingInterrupt?.kind).toBe("missing_information"),
    );
    expect(result.current.messages[0]?.text).toBe("Önceki yanıt");
    expect(mocks.messages).toHaveBeenCalledWith("user-1:web:client");
    expect(mocks.state).toHaveBeenCalledWith("user-1:web:client");
  });

  it("preserves the server conversation order when messages share a timestamp", async () => {
    mocks.messages.mockResolvedValue({
      items: [
        {
          id: "z-user-message",
          role: "user",
          content: "Seçili evrakı incele ve önemli noktaları özetle.",
          workflow_status: null,
          details: null,
          created_at: "2026-08-23T09:17:11Z",
        },
        {
          id: "a-assistant-message",
          role: "assistant",
          content: "Evrak analizi tamamlandı.",
          workflow_status: "COMPLETED",
          details: null,
          created_at: "2026-08-23T09:17:11Z",
        },
      ],
      total: 2,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:client"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages.map((message) => message.text)).toEqual([
      "Seçili evrakı incele ve önemli noktaları özetle.",
      "Evrak analizi tamamlandı.",
    ]);
  });

  it("rehydrates a structured resume as a completed question card instead of raw keys", async () => {
    const questions = [{
      key: "yazisma_turu",
      question: "Nasıl bir yazışma hazırlayayım?",
      header: "Yazışma türü",
      options: [{ value: "information_notice", label: "Bilgilendirme metni" }],
      multi_select: false,
      allow_free_text: false,
      required: true,
    }];
    mocks.messages.mockResolvedValue({
      items: [
        {
          id: "message-interrupt",
          role: "assistant",
          content: "Devam etmek için ek bilgiye ihtiyacım var.",
          workflow_status: "INTERRUPTED",
          details: { interrupt: { kind: "writing_brief", title: "Yazım Briefi", questions } },
          created_at: "2026-08-19T10:00:00Z",
        },
        {
          id: "message-answer",
          role: "user",
          content: "yazisma_turu: information_notice",
          workflow_status: null,
          details: {
            interaction_response: {
              action: "answer",
              answers: { yazisma_turu: "information_notice" },
              instructions: "",
              reason: null,
            },
          },
          created_at: "2026-08-19T10:01:00Z",
        },
      ],
      total: 2,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:client"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({
      sender: "assistant",
      text: "",
      resolvedPrompt: {
        kind: "writing_brief",
        title: "Yazım Briefi",
        answers: { yazisma_turu: "information_notice" },
      },
    });
  });

  it("leaves an answered interrupt receipt in the live conversation", async () => {
    const questions = [{
      key: "document_count",
      question: "Belge sayısı nedir?",
      header: "Belge sayısı",
      options: [],
      multi_select: false,
      allow_free_text: true,
      required: true,
    }];
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({
        event: "interrupt",
        kind: "missing_information",
        interrupt_id: "interrupt-answers",
        payload: { kind: "missing_information", questions },
      });
    });
    mocks.state.mockResolvedValue({
      status: "interrupted",
      interrupt: { kind: "missing_information", questions },
    });
    mocks.resume.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "final_result", reply: "Taslak hazır.", workflow_status: "COMPLETED" });
    });

    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });
    await act(() => result.current.send("taslak hazırla", "balanced", false));
    expect(result.current.pendingInterrupt?.kind).toBe("missing_information");

    await act(() => result.current.resume("answer", { document_count: "1234" }, ""));

    expect(result.current.messages).toEqual(expect.arrayContaining([
      expect.objectContaining({
        sender: "assistant",
        text: "",
        resolvedPrompt: expect.objectContaining({
          answers: { document_count: "1234" },
          questions,
        }),
      }),
    ]));
    expect(result.current.messages.some((message) => message.text.includes("document_count:"))).toBe(false);
  });

  it("replaces each answered form in place and opens a later request as a new message", async () => {
    const briefQuestions = [{
      key: "yazisma_turu",
      question: "Nasıl bir yazışma hazırlayayım?",
      header: "Yazışma türü",
      options: [{ value: "information_notice", label: "Bilgilendirme metni" }],
      multi_select: false,
      allow_free_text: false,
      required: true,
    }];
    const missingQuestions = [{
      key: "sender_name",
      question: "Gönderen kurumun adı nedir?",
      header: "Gönderen kurumun adı",
      options: [],
      multi_select: false,
      allow_free_text: true,
      required: true,
    }];
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({
        event: "interrupt",
        kind: "writing_brief",
        interrupt_id: "brief-1",
        payload: { kind: "writing_brief", title: "Yazım Briefi", questions: briefQuestions },
      });
      onEvent({
        event: "final_result",
        reply: "Devam etmek için ek bilgiye veya onayınıza ihtiyaç var.",
        workflow_status: "INTERRUPTED",
        details: { interrupt: { kind: "writing_brief", questions: briefQuestions } },
      });
    });
    let persistedInterrupt = { kind: "writing_brief", questions: briefQuestions };
    mocks.state.mockImplementation(async () => ({
      status: "interrupted",
      interrupt: persistedInterrupt,
    }));
    mocks.resume
      .mockImplementationOnce(async (_request, onEvent) => {
        persistedInterrupt = { kind: "missing_information", questions: missingQuestions };
        onEvent({
          event: "interrupt",
          kind: "missing_information",
          interrupt_id: "missing-2",
          payload: { kind: "missing_information", questions: missingQuestions },
        });
        onEvent({
          event: "final_result",
          reply: "Devam etmek için ek bilgiye veya onayınıza ihtiyaç var.",
          workflow_status: "INTERRUPTED",
          details: { interrupt: { kind: "missing_information", questions: missingQuestions } },
        });
      })
      .mockImplementationOnce(async (_request, onEvent) => {
        onEvent({ event: "final_result", reply: "Taslak hazır.", workflow_status: "COMPLETED" });
      });

    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });
    await act(() => result.current.send("taslak hazırla", "balanced", false));
    expect(result.current.messages.map((message) => message.text)).toEqual(["taslak hazırla"]);

    await act(() => result.current.resume("answer", { yazisma_turu: "information_notice" }, ""));
    expect(result.current.messages.filter((message) => message.resolvedPrompt)).toHaveLength(1);
    expect(result.current.messages.some((message) => message.text.startsWith("Devam etmek için"))).toBe(false);
    expect(result.current.pendingInterrupt?.kind).toBe("missing_information");

    await act(() => result.current.resume("answer", { sender_name: "KACHOW" }, ""));
    const receipts = result.current.messages.filter((message) => message.resolvedPrompt);
    expect(receipts).toHaveLength(2);
    expect(receipts[0]?.resolvedPrompt?.answers).toEqual({ yazisma_turu: "information_notice" });
    expect(receipts[1]?.resolvedPrompt?.answers).toEqual({ sender_name: "KACHOW" });
    expect(result.current.messages[result.current.messages.length - 1]?.text).toBe("Taslak hazır.");
  });

  it("converts legacy raw resume summaries into the same completed card", async () => {
    const questions = [{
      key: "yazisma_turu",
      question: "Nasıl bir yazışma hazırlayayım?",
      header: "Yazışma türü",
      options: [{ value: "information_notice", label: "Bilgilendirme metni" }],
      multi_select: false,
      allow_free_text: false,
      required: true,
    }];
    mocks.messages.mockResolvedValue({
      items: [
        {
          id: "legacy-interrupt",
          role: "assistant",
          content: "Devam etmek için ek bilgiye veya onayınıza ihtiyaç var.",
          workflow_status: "INTERRUPTED",
          details: { interrupt: { kind: "writing_brief", title: "Yazım Briefi", questions } },
          created_at: "2026-08-19T10:00:00Z",
        },
        {
          id: "legacy-answer",
          role: "user",
          content: "yazisma_turu: information_notice",
          workflow_status: null,
          details: null,
          created_at: "2026-08-19T10:01:00Z",
        },
      ],
      total: 2,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:legacy"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({
      sender: "assistant",
      text: "",
      resolvedPrompt: { answers: { yazisma_turu: "information_notice" } },
    });
  });

  it("formats a structured resume even when the matching interrupt is missing from history", async () => {
    mocks.messages.mockResolvedValue({
      items: [{
        id: "orphaned-answer",
        role: "user",
        content: "sender_name: KACHOW",
        workflow_status: null,
        details: { interaction_response: { action: "answer", answers: { sender_name: "KACHOW" } } },
        created_at: "2026-08-19T10:01:00Z",
      }],
      total: 1,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:orphaned"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({
      sender: "assistant",
      text: "",
      resolvedPrompt: {
        title: "Yanıtlanan bilgiler",
        answers: { sender_name: "KACHOW" },
        questions: [expect.objectContaining({ key: "sender_name", question: "Sender Name" })],
      },
    });
  });

  it("keeps the pending question across an intervening assistant record and preserves punctuation in legacy answers", async () => {
    const questions = [
      { key: "aciklama", question: "Açıklama nedir?", header: "Açıklama", options: [], multi_select: false, allow_free_text: true, required: true },
      { key: "sender_name", question: "Gönderen kim?", header: "Gönderen", options: [], multi_select: false, allow_free_text: true, required: true },
    ];
    mocks.messages.mockResolvedValue({
      items: [
        {
          id: "edge-interrupt",
          role: "assistant",
          content: "Ek bilgi gerekiyor.",
          workflow_status: "INTERRUPTED",
          details: { interrupt: { kind: "missing_information", questions } },
          created_at: "2026-08-19T10:00:00Z",
        },
        {
          id: "edge-notice",
          role: "assistant",
          content: "İşlem notu kaydedildi.",
          workflow_status: null,
          details: null,
          created_at: "2026-08-19T10:00:30Z",
        },
        {
          id: "edge-answer",
          role: "user",
          content: "aciklama: İlk bölüm; ikinci: açıklama; sender_name: KACHOW",
          workflow_status: null,
          details: null,
          created_at: "2026-08-19T10:01:00Z",
        },
      ],
      total: 3,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:edge"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages.some((message) => message.text.includes("aciklama:"))).toBe(false);
    expect(result.current.messages[1]).toMatchObject({
      sender: "assistant",
      resolvedPrompt: {
        answers: {
          aciklama: "İlk bölüm; ikinci: açıklama",
          sender_name: "KACHOW",
        },
      },
    });
  });

  it("records each node's backend label and first-seen order, then clears both on the next send", async () => {
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({ event: "node_start", node: "classification", label: "Evrak Analizi", message: "" });
      onEvent({ event: "node_end", node: "classification", label: "Evrak Analizi", message: "" });
      onEvent({ event: "node_start", node: "examples", label: "Üslup Örnekleri", message: "" });
      onEvent({ event: "node_end", node: "examples", label: "Üslup Örnekleri", message: "" });
      onEvent({ event: "final_result", reply: "tamam", workflow_status: "COMPLETED" });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    await act(() => result.current.send("bir evrakı analiz et", "balanced", true));

    expect(result.current.nodeOrder).toEqual(["classification", "examples"]);
    expect(result.current.nodeLabels).toEqual({
      classification: "Evrak Analizi",
      examples: "Üslup Örnekleri",
    });

    await act(() => result.current.send("ikinci istek", "balanced", true));
    expect(result.current.nodeOrder).toEqual([]);
    expect(result.current.nodeLabels).toEqual({});
  });

  it("orders workflow nodes by backend sequence even when events arrive late", async () => {
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "node_start", seq: 20, node: "draft", label: "Taslak", message: "" });
      onEvent({ event: "node_start", seq: 10, node: "classification", label: "Analiz", message: "" });
      onEvent({ event: "node_end", seq: 21, node: "draft", label: "Taslak", message: "" });
      onEvent({ event: "node_start", seq: 19, node: "draft", label: "Taslak", message: "" });
      onEvent({ event: "final_result", seq: 22, reply: "tamam", workflow_status: "COMPLETED" });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    await act(() => result.current.send("sırayı koru", "balanced", false));

    expect(result.current.nodeOrder).toEqual(["classification", "draft"]);
    expect(result.current.nodeStatus.draft).toBe("completed");
  });

  it("rehydrates plan_steps/intent from the last persisted message's final_output details", async () => {
    mocks.messages.mockResolvedValue({
      items: [{
        id: "message-1",
        role: "assistant",
        content: "Taslak hazır",
        workflow_status: "COMPLETED",
        details: { plan_steps: ["classification", "draft", "routing"], intent: "draft" },
        created_at: "2026-08-09T10:00:00Z",
      }],
      total: 1,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:client"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.planSteps).toEqual(["classification", "draft", "routing"]));
    expect(result.current.planIntent).toBe("draft");
    expect(result.current.nodeOrder).toEqual(["classification", "draft", "routing"]);
    expect(result.current.nodeStatus).toEqual({
      classification: "completed",
      draft: "completed",
      routing: "completed",
    });
  });

  it("appends the streamed reply as one message with no diff artifact, since token text and final reply are always the same string", async () => {
    // Mirrors the backend invariant (see app.ai.workflows.events.
    // emit_reply_stream): the only text ever streamed is the exact final
    // reply, chunked, emitted once from the terminal event -- never a raw
    // per-agent generation that final_result could later diverge from.
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({ event: "node_start", node: "draft", label: "Taslak Oluşturma", message: "" });
      onEvent({ event: "token", node: "reply", text: "Resmî yazı taslağınız hazırlandı.\n\n" });
      onEvent({ event: "token", node: "reply", text: "Sayın Makam, ..." });
      onEvent({
        event: "final_result",
        reply: "Resmî yazı taslağınız hazırlandı.\n\nSayın Makam, ...",
        workflow_status: "COMPLETED",
      });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    await act(() => result.current.send("itiraz dilekçesi yaz", "balanced", false));

    const assistantMessage = result.current.messages.find((message) => message.sender === "assistant");
    expect(assistantMessage?.text).toBe(
      "Resmî yazı taslağınız hazırlandı.\n\nSayın Makam, ...",
    );
    expect(assistantMessage).not.toHaveProperty("diffSegments");
    expect(result.current.streamingText).toBe("");
  });

  it("does not let a lagging server-history refetch wipe the message final_result just appended", async () => {
    // The bug this closes: handleEvent's `final_result` case calls
    // `refreshServerState`, which invalidates `messagesQuery` -- but that
    // query is `enabled: !loading`, and `loading` only flips back to
    // `false` in `send`'s own `finally`, at essentially the same moment
    // the `!activeRequest.current` guard on the messages-sync effect opens.
    // So the invalidation's refetch fires *after* that guard is already
    // open, and if it resolves with fewer items than we already have (chat
    // history mocked here, as in every other test, to always return `[]`
    // -- a stand-in for a server read that simply hasn't caught up yet),
    // the sync effect used to overwrite `messages` with that stale, empty
    // list, making the assistant's just-shown reply vanish.
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({ event: "final_result", reply: "Tamamdır.", workflow_status: "COMPLETED" });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    await act(() => result.current.send("bir şey sor", "balanced", false));
    // Give any invalidation-triggered refetch every chance to resolve and
    // (if the bug were still present) clobber `messages` before asserting.
    await waitFor(() => expect(mocks.messages).toHaveBeenCalled());
    await act(() => Promise.resolve());

    expect(
      result.current.messages.some(
        (message) => message.sender === "assistant" && message.text === "Tamamdır.",
      ),
    ).toBe(true);
  });

  it("does not blank an in-progress stream on a node_start, since no per-agent node streams its own raw output anymore", async () => {
    let emitToken: (() => void) | undefined;
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({ event: "token", node: "reply", text: "Merhaba" });
      onEvent({ event: "node_start", node: "verify", label: "Taslak Doğrulama", message: "" });
      await new Promise<void>((resolve) => {
        emitToken = resolve;
      });
      onEvent({ event: "final_result", reply: "Merhaba", workflow_status: "COMPLETED" });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    let pending!: Promise<void>;
    act(() => {
      pending = result.current.send("selam", "balanced", false);
    });

    await waitFor(() => expect(result.current.streamingText).toBe("Merhaba"));

    await act(async () => {
      emitToken?.();
      await pending;
    });
  });

  it("aborts an active stream without rendering a workflow failure", async () => {
    let receivedSignal: AbortSignal | undefined;
    mocks.send.mockImplementation((_request, _onEvent, signal: AbortSignal) => {
      receivedSignal = signal;
      return new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("cancelled", "AbortError")));
      });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    let pending!: Promise<void>;
    act(() => { pending = result.current.send("iptal et", "balanced", false); });
    await waitFor(() => expect(result.current.loading).toBe(true));
    act(() => result.current.cancel());
    await act(async () => pending);

    expect(receivedSignal?.aborted).toBe(true);
    expect(result.current.messages).toEqual([{ sender: "user", text: "iptal et" }]);
  });
});

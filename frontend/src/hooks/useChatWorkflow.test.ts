import { createElement, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChatWorkflow } from "./useChatWorkflow";

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
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
    mocks.cancel.mockReset().mockResolvedValue({ status: "cancelled" });
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

  it("repairs a same-timestamp resume returned after its assistant result", async () => {
    const questions = [{
      key: "belge_sayisi",
      question: "Belge sayısı nedir?",
      header: "Belge sayısı",
      options: [],
      multi_select: false,
      allow_free_text: true,
      required: true,
    }];
    mocks.messages.mockResolvedValue({
      items: [
        {
          id: "interrupt-before-reversed-pair",
          role: "assistant",
          content: "Birkaç bilgi daha gerekiyor.",
          workflow_status: "INTERRUPTED",
          details: { interrupt: { kind: "missing_information", questions } },
          created_at: "2026-08-24T16:40:00Z",
        },
        {
          id: "assistant-result-sorted-first",
          role: "assistant",
          content: "Taslak hazırlandı.",
          workflow_status: "COMPLETED",
          details: null,
          created_at: "2026-08-24T16:41:00Z",
        },
        {
          id: "structured-response-sorted-last",
          role: "user",
          content: "belge_sayisi: 123",
          workflow_status: null,
          details: {
            interaction_response: {
              action: "answer",
              answers: { belge_sayisi: "123" },
              instructions: "",
              reason: null,
            },
          },
          created_at: "2026-08-24T16:41:00Z",
        },
      ],
      total: 3,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:reversed"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[0]).toMatchObject({
      sender: "assistant",
      text: "",
      resolvedPrompt: { action: "answer", answers: { belge_sayisi: "123" } },
    });
    expect(result.current.messages[1]).toMatchObject({
      sender: "assistant",
      text: "Taslak hazırlandı.",
    });
    expect(result.current.messages.some((message) => message.sender === "user")).toBe(false);
  });

  it("repairs a legacy rejection returned after the cancellation reply", async () => {
    mocks.messages.mockResolvedValue({
      items: [
        {
          id: "legacy-reject-interrupt",
          role: "assistant",
          content: "Taslağı onaylıyor musunuz?",
          workflow_status: "INTERRUPTED",
          details: {
            interrupt: {
              kind: "writing_brief",
              title: "Taslak kontrolü",
              questions: [],
            },
          },
          created_at: "2026-08-24T16:48:00Z",
        },
        {
          id: "legacy-cancel-reply",
          role: "assistant",
          content: "Taslak talebi iptal edildi.",
          workflow_status: "COMPLETED",
          details: null,
          created_at: "2026-08-24T16:49:00Z",
        },
        {
          id: "legacy-reject-summary",
          role: "user",
          content: "reject: Kullanıcı taslağı iptal etti.",
          workflow_status: null,
          details: null,
          created_at: "2026-08-24T16:49:00Z",
        },
      ],
      total: 3,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:legacy-reject"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[0]).toMatchObject({
      sender: "assistant",
      text: "",
      resolvedPrompt: {
        action: "reject",
        reason: "Kullanıcı taslağı iptal etti.",
      },
    });
    expect(result.current.messages[1]?.text).toBe("Taslak talebi iptal edildi.");
    expect(result.current.messages.some((message) => message.sender === "user")).toBe(false);
  });

  it("never exposes an orphan structured resume carrier as a user bubble", async () => {
    mocks.messages.mockResolvedValue({
      items: [{
        id: "orphan-resume-carrier",
        role: "user",
        content: "belge_sayisi: 123",
        workflow_status: null,
        details: {
          interaction_response: {
            action: "answer",
            answers: { belge_sayisi: "123" },
          },
        },
        created_at: "2026-08-24T16:50:00Z",
      }],
      total: 1,
      page: 1,
      page_size: 50,
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:orphan"),
      { wrapper },
    );

    await waitFor(() => expect(mocks.messages).toHaveBeenCalled());
    expect(result.current.messages).toEqual([]);
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

  it("inserts the final reply once and marks it for local animation", async () => {
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
    expect(assistantMessage?.animate).toBe(true);
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

  it("keeps the live animation flag when server history refreshes the same final reply", async () => {
    const draftDetails = {
      draft: {
        draft: "Taslak hazır.",
        status: "COMPLETED",
        combined_score: 92,
      },
    };
    mocks.messages.mockResolvedValue({
      items: [
        {
          id: "message-user",
          role: "user",
          content: "taslak hazırla",
          workflow_status: null,
          details: null,
          created_at: "2026-08-27T10:00:00Z",
        },
        {
          id: "message-assistant",
          role: "assistant",
          content: "Taslak hazır.",
          workflow_status: "COMPLETED",
          details: draftDetails,
          created_at: "2026-08-27T10:00:01Z",
        },
      ],
      total: 2,
      page: 1,
      page_size: 50,
    });
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({
        event: "final_result",
        reply: "Taslak hazır.",
        workflow_status: "COMPLETED",
        details: draftDetails,
      });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    await act(() => result.current.send("taslak hazırla", "balanced", false));
    await waitFor(() => expect(mocks.messages).toHaveBeenCalled());
    await waitFor(() =>
      expect(result.current.messages[result.current.messages.length - 1]).toMatchObject({
        id: "message-assistant",
        sender: "assistant",
        text: "Taslak hazır.",
        animate: true,
      }),
    );
  });

  it("keeps transport chunks out of UI state until the final reply is ready", async () => {
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

    await waitFor(() => expect(result.current.nodeStatus.verify).toBe("running"));
    expect(result.current.streamingText).toBe("");

    await act(async () => {
      emitToken?.();
      await pending;
    });
    expect(result.current.messages[result.current.messages.length - 1]).toMatchObject({
      sender: "assistant",
      text: "Merhaba",
      animate: true,
    });
  });

  it("aborts an active stream without rendering a workflow failure", async () => {
    let receivedSignal: AbortSignal | undefined;
    mocks.send.mockImplementation((_request, onEvent, signal: AbortSignal) => {
      receivedSignal = signal;
      onEvent({ event: "session", thread_id: "user-1:web:cancelled" });
      onEvent({ event: "node_start", node: "brief", label: "Brief", message: "Başladı" });
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
    await waitFor(() => expect(mocks.cancel).toHaveBeenCalledWith("user-1:web:cancelled"));
    await waitFor(() => expect(result.current.messages[1]?.text).toBe("İşlem durduruldu."));
    expect(result.current.pendingInterrupt).toBeNull();
    expect(result.current.nodeStatus).toEqual({});
    expect(result.current.messages).toEqual([
      { sender: "user", text: "iptal et" },
      {
        id: expect.stringMatching(/^cancel:/),
        sender: "assistant",
        text: "İşlem durduruldu.",
        kind: "notice",
      },
    ]);
  });

  it("blocks the next message until backend cancellation settles", async () => {
    let settleCancellation!: () => void;
    mocks.cancel.mockImplementationOnce(() => new Promise<{ status: "cancelled" }>((resolve) => {
      settleCancellation = () => resolve({ status: "cancelled" });
    }));
    mocks.send.mockImplementationOnce((_request, onEvent, signal: AbortSignal) => {
      onEvent({ event: "session", thread_id: "user-1:web:stop-race" });
      return new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("cancelled", "AbortError")));
      });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    let firstTurn!: Promise<void>;
    act(() => { firstTurn = result.current.send("ilk", "balanced", false); });
    await waitFor(() => expect(result.current.loading).toBe(true));
    act(() => result.current.cancel());
    await act(async () => firstTurn);

    await act(() => result.current.send("çok erken", "balanced", false));
    expect(mocks.send).toHaveBeenCalledTimes(1);

    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "final_result", reply: "devam", workflow_status: "COMPLETED" });
    });
    await act(async () => {
      settleCancellation();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.messages[1]?.text).toBe("İşlem durduruldu."));

    await act(() => result.current.send("şimdi gönder", "balanced", false));
    expect(mocks.send).toHaveBeenCalledTimes(2);
  });

  it("silently clears an interrupt that settled before its form was submitted", async () => {
    const interrupt = {
      kind: "writing_brief" as const,
      questions: [{ key: "type", question: "Tür?", required: true }],
    };
    let stale = false;
    mocks.state.mockImplementation(async () =>
      stale
        ? { status: "idle", interrupt: null }
        : { status: "interrupted", interrupt },
    );
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:stale" });
      onEvent({
        event: "interrupt",
        kind: "writing_brief",
        interrupt_id: "stale-brief",
        payload: interrupt,
      });
    });

    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });
    await act(() => result.current.send("taslak hazırla", "balanced", false));
    await waitFor(() => expect(result.current.pendingInterrupt).not.toBeNull());

    stale = true;
    await act(() => result.current.resume("reject", {}, "", "Kullanıcı vazgeçti."));

    expect(mocks.resume).not.toHaveBeenCalled();
    expect(result.current.pendingInterrupt).toBeNull();
    expect(result.current.messages.some((message) =>
      message.text.includes("Bekleyen onay artık geçerli değil"),
    )).toBe(false);
  });

  it("dismisses a single guardrail alert by index without touching the others", async () => {
    mocks.send.mockImplementationOnce(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:guardrail" });
      onEvent({ event: "guardrail", stage: "output", kind: "pii", decision: "redacted", reasons: ["TCKN maskelendi."] });
      onEvent({ event: "guardrail", stage: "output", kind: "sensitivity", decision: "blocked", reasons: ["Gizlilik derecesi yetkiyi aşıyor."] });
      onEvent({ event: "final_result", reply: "tamam", workflow_status: "COMPLETED" });
    });

    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });
    await act(() => result.current.send("merhaba", "balanced", false));

    expect(result.current.guardrailEvents).toHaveLength(2);

    act(() => result.current.dismissGuardrailEvent(0));

    expect(result.current.guardrailEvents).toHaveLength(1);
    expect(result.current.guardrailEvents[0].kind).toBe("sensitivity");
  });
});

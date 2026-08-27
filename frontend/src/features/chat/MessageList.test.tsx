import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, InterruptState } from "../../types/chat";
import { MessageList } from "./MessageList";

const baseProps = {
  messages: [] as ChatMessage[],
  streamingText: "",
  loading: false,
  logs: [],
  hasSelectedDocument: false,
  onSuggestion: vi.fn(),
};

// A message.sender === "assistant" message renders FeedbackButtons (Faz
// C1), which calls useMutation -- every render in this file needs a
// QueryClient in scope now, same as AdminPage.test.tsx's own wrapper.
function renderWithQueryClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("MessageList", () => {
  it("offers general conversation starters when no document or draft is selected", () => {
    const onSuggestion = vi.fn();
    renderWithQueryClient(<MessageList {...baseProps} onSuggestion={onSuggestion} />);

    expect(screen.getByText("Neler yapabilirsin?")).toBeInTheDocument();
    expect(screen.getByText("Sohbete başlayalım")).toBeInTheDocument();
    expect(screen.queryByText("Resmî taslak hazırla")).not.toBeInTheDocument();
    expect(screen.queryByText("Hedef birim öner")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Neler yapabilirsin/ }));
    expect(onSuggestion).toHaveBeenCalledWith(
      "Neler yapabildiğini ve bana hangi konularda yardımcı olabileceğini kısaca anlat.",
    );
  });

  it("offers document-specific starters only when a document or draft is selected", () => {
    renderWithQueryClient(<MessageList {...baseProps} hasSelectedDocument />);

    expect(screen.getByText("Seçili içeriği incele")).toBeInTheDocument();
    expect(screen.getByText("Resmî taslak hazırla")).toBeInTheDocument();
    expect(screen.getByText("Hedef birim öner")).toBeInTheDocument();
    expect(screen.queryByText("Neler yapabilirsin?")).not.toBeInTheDocument();
    expect(screen.queryByText("Sohbete başlayalım")).not.toBeInTheDocument();
  });

  it("renders a pending missing-information gate as a chat bubble in the scrolling conversation, not a standalone panel", () => {
    const interrupt: InterruptState = {
      kind: "missing_information",
      interruptId: "interrupt-1",
      payload: {
        draft: "Onaylanacak taslak metni",
        questions: [
          {
            key: "muhatap",
            question: "'Muhatap' bilgisi nedir?",
            header: "Muhatap",
            options: [],
            multi_select: false,
            allow_free_text: true,
            required: true,
          },
        ],
      },
    };
    const { container } = renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[{ sender: "user", text: "taslak hazırla" }]}
        interrupt={interrupt}
        onResume={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    // Lives inside .messages-area as a .chat-message article, the same
    // container every ordinary message scrolls in -- not a sibling panel
    // pinned above it (the old .interrupt-panel standalone-card layout).
    const bubble = container.querySelector(".chat-message.interrupt-message");
    expect(bubble).not.toBeNull();
    expect(bubble?.closest(".messages-area")).not.toBeNull();
    expect(screen.getByText("Onaylanacak taslak metni")).toBeInTheDocument();
    expect(screen.getByText("Birkaç bilgi daha gerekiyor")).toBeInTheDocument();
  });

  it("does not show the empty state when a fresh session already has a pending interrupt", () => {
    const interrupt: InterruptState = {
      kind: "missing_information",
      interruptId: "interrupt-2",
      payload: { questions: [] },
    };
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[]}
        interrupt={interrupt}
        onResume={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.queryByText("Nasıl yardımcı olabilirim?")).not.toBeInTheDocument();
  });

  it("renders no interrupt bubble when there is nothing pending", () => {
    const { container } = renderWithQueryClient(
      <MessageList {...baseProps} messages={[{ sender: "assistant", text: "tamam" }]} />,
    );
    expect(container.querySelector(".interrupt-message")).toBeNull();
  });

  it("keeps completed questions and their selected answers visible in the conversation", () => {
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[
          {
            sender: "assistant",
            text: "",
            resolvedPrompt: {
              kind: "writing_brief",
              title: "Yazım Briefi",
              action: "answer",
              questions: [
                {
                  key: "yazisma_turu",
                  header: "Yazışma türü",
                  question: "Nasıl bir yazışma hazırlayayım?",
                  options: [
                    { value: "information_notice", label: "Bilgilendirme metni" },
                  ],
                  multi_select: false,
                  allow_free_text: false,
                  required: true,
                },
                {
                  key: "muhatap",
                  header: "Muhatap",
                  question: "Yazı kime gidecek?",
                  options: [],
                  multi_select: false,
                  allow_free_text: true,
                  required: true,
                },
              ],
              answers: {
                yazisma_turu: "information_notice",
                muhatap: "Strateji Geliştirme Dairesi",
              },
            },
          },
        ]}
      />,
    );

    expect(screen.getByText("Yazım Briefi")).toBeInTheDocument();
    expect(screen.getByText("Yanıtlandı")).toBeInTheDocument();
    expect(screen.getByText("Yazışma türü")).toBeInTheDocument();
    expect(screen.getByText("Bilgilendirme metni")).toBeInTheDocument();
    expect(screen.getByText("Strateji Geliştirme Dairesi")).toBeInTheDocument();
    expect(screen.queryByText(/yazisma_turu:/)).not.toBeInTheDocument();
  });

  it("renders a persisted interrupt sentence and its active form as one message", () => {
    const interrupt: InterruptState = {
      kind: "missing_information",
      interruptId: "interrupt-single-surface",
      payload: {
        questions: [{
          key: "sender_name",
          question: "Gönderen kurumun adı nedir?",
          header: "Gönderen kurumun adı",
          options: [],
          multi_select: false,
          allow_free_text: true,
          required: true,
        }],
      },
    };
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[{
          sender: "assistant",
          text: "Devam etmek için ek bilgiye veya onayınıza ihtiyaç var.",
          details: { interrupt: interrupt.payload },
        }]}
        interrupt={interrupt}
        onResume={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.queryByText("Devam etmek için ek bilgiye veya onayınıza ihtiyaç var.")).not.toBeInTheDocument();
    expect(screen.getByText("Birkaç bilgi daha gerekiyor")).toBeInTheDocument();
    expect(screen.queryByText(/akış duraklatıldı/i)).not.toBeInTheDocument();
  });

  it("offers a 👍/👎 vote on an assistant reply but not on the user's own message", () => {
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[
          { sender: "user", text: "taslak hazırla" },
          { sender: "assistant", text: "İşte taslağınız." },
        ]}
      />,
    );

    expect(screen.getAllByRole("button", { name: "Beğendim" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Beğenmedim" })).toHaveLength(1);
  });

  it("does not offer a vote on a non-blocking notice message", () => {
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[{ sender: "assistant", text: "Bir çelişki bulundu.", kind: "notice" }]}
      />,
    );

    expect(screen.queryByRole("button", { name: "Beğendim" })).not.toBeInTheDocument();
  });

  it("shows draft confidence only after the live message animation completes", () => {
    vi.useFakeTimers();
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[{
          sender: "assistant",
          text: "Hazırlanan resmî yazı taslağı burada gösterilir.",
          animate: true,
          details: {
            draft: {
              draft: "Hazırlanan resmî yazı taslağı burada gösterilir.",
              status: "COMPLETED",
              combined_score: 92,
            },
          },
        }]}
      />,
    );

    expect(screen.queryByText("Güven skoru: 92/100")).not.toBeInTheDocument();

    act(() => vi.advanceTimersByTime(10_000));

    expect(screen.getByText("Güven skoru: 92/100")).toBeInTheDocument();
  });

  it("shows document analysis as a compact message in the conversation", () => {
    const { container } = renderWithQueryClient(
      <MessageList {...baseProps} uploadingDocumentName="Başvuru.pdf" />,
    );

    const uploadMessage = container.querySelector(".document-upload-message");
    expect(uploadMessage?.closest(".messages-area")).not.toBeNull();
    expect(screen.getByText("Evrak yükleniyor")).toBeInTheDocument();
    expect(screen.getByText("Başvuru.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Nasıl yardımcı olabilirim?")).not.toBeInTheDocument();
  });
});

// ==========================================
// Page citations reaching the rendered message
// ==========================================
describe("MessageList page citations", () => {
  const citedMessage: ChatMessage[] = [
    {
      id: "m1",
      sender: "assistant",
      text: "Not ortalaması 3.83'tür [1].\n\nKAYNAKLAR:\n[1] (s. 1) Genel not ortalaması 3.83.",
    } as ChatMessage,
  ];

  it("renders a citation in a finished message as a badge, hiding the block", () => {
    const { container } = renderWithQueryClient(
      <MessageList {...baseProps} messages={citedMessage} />,
    );

    expect(container.querySelector(".page-citation")?.textContent).toBe("1");
    expect(container.textContent).not.toContain("KAYNAKLAR");
  });

  it("makes the badge clickable once a citation handler is wired through", () => {
    const onCitationClick = vi.fn();
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={citedMessage}
        onCitationClick={onCitationClick}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Kaynak 1/ }));

    expect(onCitationClick).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, quote: "Genel not ortalaması 3.83." }),
    );
  });

  it("badges a citation in the streaming preview too", () => {
    const { container } = renderWithQueryClient(
      <MessageList
        {...baseProps}
        loading
        streamingText={"Sonuç şudur [1].\n\nKAYNAKLAR:\n[1] (s. 2) Kaynak cümlesi."}
      />,
    );

    expect(container.querySelector(".page-citation")?.textContent).toBe("1");
  });
});

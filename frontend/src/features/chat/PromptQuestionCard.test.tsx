import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PromptQuestion } from "../../types/chat";
import { PromptQuestionCard } from "./PromptQuestionCard";

describe("PromptQuestionCard", () => {
  it("renders a free-text question when no options are given and gates submit on required fields", () => {
    const onSubmit = vi.fn();
    const questions: PromptQuestion[] = [
      {
        key: "organization",
        question: "'Kurum adı' bilgisi nedir?",
        header: "Kurum adı",
        options: [],
        multi_select: false,
        allow_free_text: true,
        required: true,
      },
    ];
    render(<PromptQuestionCard questions={questions} loading={false} onSubmit={onSubmit} />);

    const submit = screen.getByRole("button", { name: "Devam et" });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Kurum adı"), { target: { value: "KACMAK" } });
    expect(submit).toBeEnabled();

    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledWith({ organization: "KACMAK" });
  });

  it("submits immediately on the last (and only) question when a single option is clicked", () => {
    const onSubmit = vi.fn();
    const questions: PromptQuestion[] = [
      {
        key: "kapanis",
        question: "Kapanış ifadesi",
        header: "Kapanış",
        options: [
          { value: "arz_ederim", label: "Arz ederim" },
          { value: "rica_ederim", label: "Rica ederim" },
          { value: "__auto__", label: "Sen karar ver" },
        ],
        multi_select: false,
        allow_free_text: false,
        required: true,
      },
    ];
    render(<PromptQuestionCard questions={questions} loading={false} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole("button", { name: "Arz ederim" }));
    expect(onSubmit).toHaveBeenCalledWith({ kapanis: "arz_ederim" });
  });

  it("advances step by step through multiple questions instead of showing them all at once", () => {
    const onSubmit = vi.fn();
    const questions: PromptQuestion[] = [
      {
        key: "yazan_taraf",
        question: "Yazıyı kim yazıyor?",
        header: "Yazan taraf",
        options: [{ value: "kacmak", label: "KACMAK Ekibi" }],
        multi_select: false,
        allow_free_text: false,
        required: true,
      },
      {
        key: "kapanis",
        question: "Kapanış ifadesi",
        header: "Kapanış",
        options: [{ value: "arz_ederim", label: "Arz ederim" }],
        multi_select: false,
        allow_free_text: false,
        required: true,
      },
    ];
    render(<PromptQuestionCard questions={questions} loading={false} onSubmit={onSubmit} />);

    expect(screen.getByText("Soru 1 / 2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Arz ederim" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "KACMAK Ekibi" }));

    expect(screen.getByText("Soru 2 / 2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "KACMAK Ekibi" })).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Arz ederim" }));
    expect(onSubmit).toHaveBeenCalledWith({ yazan_taraf: "kacmak", kapanis: "arz_ederim" });
  });

  it("toggles multiple values for a multi-select question", () => {
    const onSubmit = vi.fn();
    const questions: PromptQuestion[] = [
      {
        key: "uslup",
        question: "Hangi üslup değişikliklerini istersiniz?",
        header: "Üslup",
        options: [
          { value: "daha_resmi", label: "Daha resmi" },
          { value: "daha_kisa", label: "Daha kısa" },
        ],
        multi_select: true,
        allow_free_text: false,
        required: false,
      },
    ];
    render(<PromptQuestionCard questions={questions} loading={false} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole("button", { name: "Daha resmi" }));
    fireEvent.click(screen.getByRole("button", { name: "Daha kısa" }));
    fireEvent.click(screen.getByRole("button", { name: "Devam et" }));
    expect(onSubmit).toHaveBeenCalledWith({ uslup: ["daha_resmi", "daha_kisa"] });
  });

  it("lets a free-text answer override the option list via Diğer…", () => {
    const onSubmit = vi.fn();
    const questions: PromptQuestion[] = [
      {
        key: "muhatap",
        question: "Yazı kime gidiyor?",
        header: "Muhatap",
        options: [{ value: "teknofest", label: "TEKNOFEST Komitesi" }],
        multi_select: false,
        allow_free_text: true,
        required: true,
      },
    ];
    render(<PromptQuestionCard questions={questions} loading={false} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole("button", { name: "Diğer…" }));
    fireEvent.change(screen.getByLabelText("Muhatap"), {
      target: { value: "Hacettepe Üniversitesi Rektörlüğü" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Devam et" }));
    expect(onSubmit).toHaveBeenCalledWith({ muhatap: "Hacettepe Üniversitesi Rektörlüğü" });
  });

  const exampleQuestion: PromptQuestion[] = [
    {
      key: "belge_sayisi",
      question: "'Belge Sayısı' alanı için ne yazılmalı?",
      header: "Belge Sayısı",
      example: "E-12345678-100-4567",
      options: [],
      multi_select: false,
      allow_free_text: true,
      required: true,
    },
  ];

  it("accepts question.example by pressing Tab on the empty input", () => {
    const onSubmit = vi.fn();
    render(<PromptQuestionCard questions={exampleQuestion} loading={false} onSubmit={onSubmit} />);

    const input = screen.getByLabelText("Belge Sayısı");
    const submit = screen.getByRole("button", { name: "Devam et" });
    expect(submit).toBeDisabled();

    fireEvent.keyDown(input, { key: "Tab" });
    expect((input as HTMLInputElement).value).toBe("E-12345678-100-4567");
    expect(submit).toBeEnabled();

    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledWith({ belge_sayisi: "E-12345678-100-4567" });
  });

  it("accepts question.example by clicking the suggestion chip, which then hides", () => {
    render(<PromptQuestionCard questions={exampleQuestion} loading={false} onSubmit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Öneri:/ }));
    expect((screen.getByLabelText("Belge Sayısı") as HTMLInputElement).value).toBe(
      "E-12345678-100-4567",
    );
    expect(screen.queryByRole("button", { name: /Öneri:/ })).not.toBeInTheDocument();
  });

  it("renders the resolved slots as a read-only strip", () => {
    const questions: PromptQuestion[] = [
      {
        key: "muhatap",
        question: "Yazı kime gidiyor?",
        options: [{ value: "teknofest", label: "TEKNOFEST" }],
        multi_select: false,
        allow_free_text: false,
        required: true,
      },
    ];
    render(
      <PromptQuestionCard
        questions={questions}
        resolved={{ yazan_taraf: { value: "KACMAK Ekibi", label: "KACMAK Ekibi" } }}
        loading={false}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("Bilinenler")).toBeInTheDocument();
    expect(screen.getByText("KACMAK Ekibi")).toBeInTheDocument();
  });
});

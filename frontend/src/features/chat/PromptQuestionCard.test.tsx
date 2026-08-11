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

  it("selects a single option by value on click", () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Devam et" }));
    expect(onSubmit).toHaveBeenCalledWith({ kapanis: "arz_ederim" });
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

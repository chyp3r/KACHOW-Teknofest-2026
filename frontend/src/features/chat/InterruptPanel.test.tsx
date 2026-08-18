import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { InterruptState } from "../../types/chat";
import { InterruptPanel } from "./InterruptPanel";

const missingInformation: InterruptState = {
  kind: "missing_information",
  interruptId: "interrupt-1",
  payload: {
    draft: "Hazırlanan resmî yazı taslağı",
    questions: [
      {
        key: "organization",
        question: "'Kurum adı' bilgisi nedir?",
        header: "Kurum adı",
        options: [],
        multi_select: false,
        allow_free_text: true,
        required: true,
      },
      {
        key: "document_count",
        question: "'Belge sayısı' bilgisi nedir?",
        header: "Belge sayısı",
        options: [],
        multi_select: false,
        allow_free_text: true,
        required: true,
      },
    ],
  },
};

describe("InterruptPanel", () => {
  it("keeps the draft collapsed and asks missing information one question at a time", () => {
    const onResume = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <InterruptPanel
        interrupt={missingInformation}
        loading={false}
        onResume={onResume}
      />,
    );

    expect(container.querySelector("details")).not.toHaveAttribute("open");

    // Only the first question is on screen -- not a form with every field open.
    expect(screen.getByLabelText(/kurum adı/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/belge sayısı/i)).not.toBeInTheDocument();
    const next = screen.getByRole("button", { name: "İleri" });
    expect(next).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/kurum adı/i), {
      target: { value: "KACHOW" },
    });
    expect(next).toBeEnabled();
    fireEvent.click(next);

    expect(screen.queryByLabelText(/kurum adı/i)).not.toBeInTheDocument();
    const submit = screen.getByRole("button", {
      name: "Bilgileri gönder ve devam et",
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/belge sayısı/i), {
      target: { value: "24" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    expect(onResume).toHaveBeenCalledWith(
      "answer",
      { organization: "KACHOW", document_count: "24" },
      "",
    );
  });

  it("lets the user redirect a missing-information answer into a revision instead", () => {
    const onResume = vi.fn().mockResolvedValue(undefined);
    render(
      <InterruptPanel
        interrupt={missingInformation}
        loading={false}
        onResume={onResume}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Bilgi vermek yerine taslağı revize etmek mi istiyorsunuz?",
      }),
    );
    const note = screen.getByLabelText("Revizyon talimatı");
    fireEvent.change(note, { target: { value: "Unvanı Daire Başkanı olarak değiştir." } });
    fireEvent.click(screen.getByRole("button", { name: "Bunun yerine revizyon iste" }));

    expect(onResume).toHaveBeenCalledWith(
      "revise",
      {},
      "Unvanı Daire Başkanı olarak değiştir.",
    );
  });

  it("never shows an approval prompt -- missing_information is the only draft-related gate", () => {
    render(
      <InterruptPanel
        interrupt={missingInformation}
        loading={false}
        onResume={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.queryByRole("button", { name: "Onayla" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reddet" })).not.toBeInTheDocument();
    expect(screen.queryByText(/İnsan onayı/)).not.toBeInTheDocument();
  });

  it("lets the writing-brief gate fall back to the system's own choice for every slot", () => {
    const onResume = vi.fn().mockResolvedValue(undefined);
    render(
      <InterruptPanel
        interrupt={{
          kind: "writing_brief",
          interruptId: "interrupt-brief",
          payload: {
            questions: [
              {
                key: "muhatap",
                question: "Yazı kime gidiyor?",
                header: "Muhatap",
                options: [
                  { value: "teknofest", label: "TEKNOFEST Komitesi" },
                  { value: "__auto__", label: "Sen karar ver" },
                ],
                multi_select: false,
                allow_free_text: true,
                required: true,
              },
            ],
            resolved: { yazan_taraf: { value: "KACMAK Ekibi", source: "user_text" } },
            auto_value: "__auto__",
          },
        }}
        loading={false}
        onResume={onResume}
      />,
    );

    expect(screen.getByText("Bilinenler")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sen karar ver, devam et" }));
    expect(onResume).toHaveBeenCalledWith("answer", { muhatap: "__auto__" }, "");
  });
});

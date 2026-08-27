import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSpeechToText } from "./useSpeechToText";

/** Minimal stand-in for the Web Speech API used by the hook. */
class FakeRecognition {
  lang = "";
  continuous = false;
  interimResults = false;
  onresult: ((e: unknown) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn(() => this.onend?.());
  abort = vi.fn();

  emit(results: Array<{ isFinal: boolean; transcript: string }>, resultIndex = 0) {
    this.onresult?.({
      resultIndex,
      results: {
        length: results.length,
        ...results.map((r) => ({ isFinal: r.isFinal, length: 1, 0: { transcript: r.transcript } })),
      },
    });
  }
}

let current: FakeRecognition | null = null;

afterEach(() => {
  current = null;
  // @ts-expect-error test cleanup
  delete window.SpeechRecognition;
});

function installFakeRecognition() {
  // @ts-expect-error test shim
  window.SpeechRecognition = class {
    constructor() {
      current = new FakeRecognition();
      return current as unknown as FakeRecognition;
    }
  };
}

describe("useSpeechToText", () => {
  it("emits the full transcript on every event, never a delta", () => {
    installFakeRecognition();
    const onTranscript = vi.fn();
    const { result } = renderHook(() => useSpeechToText({ onTranscript }));

    act(() => result.current.start());
    act(() => current!.emit([{ isFinal: false, transcript: "merha" }]));
    act(() => current!.emit([{ isFinal: true, transcript: "merhaba" }]));
    act(() => current!.emit([{ isFinal: true, transcript: "merhaba" }, { isFinal: false, transcript: "dün" }], 1));

    expect(onTranscript).toHaveBeenLastCalledWith("merhaba dün", false);
  });

  it("does not re-deliver an already-final segment when resultIndex regresses on stop", () => {
    installFakeRecognition();
    const onTranscript = vi.fn();
    const { result } = renderHook(() => useSpeechToText({ onTranscript }));

    act(() => result.current.start());
    act(() => current!.emit([{ isFinal: true, transcript: "birinci cümle" }]));
    act(() => current!.emit([{ isFinal: true, transcript: "birinci cümle" }, { isFinal: false, transcript: "ikinci" }], 1));
    // stop(): browser re-sends every result as final, resultIndex back to 0
    act(() =>
      current!.emit(
        [
          { isFinal: true, transcript: "birinci cümle" },
          { isFinal: true, transcript: "ikinci cümle" },
        ],
        0,
      ),
    );

    expect(onTranscript).toHaveBeenLastCalledWith("birinci cümle ikinci cümle", true);
    // the first segment appears exactly once
    const last = onTranscript.mock.lastCall![0] as string;
    expect(last.match(/birinci cümle/g)).toHaveLength(1);
  });
});

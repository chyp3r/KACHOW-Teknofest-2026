import { describe, expect, it } from "vitest";
import type { WorkflowEvent } from "../types/chat";
import { consumeSseStream } from "./chatService";

describe("consumeSseStream", () => {
  it("parses chunked tool and guardrail events and ignores duplicate seq", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"event":"tool_call","seq":1,"node":"assist","tool":"search_document",',
          ),
        );
        controller.enqueue(
          encoder.encode(
            '"args":{"query":"izin"}}\n\ndata: {"event":"guardrail","seq":2,"stage":"output","kind":"pii","decision":"redacted","reasons":["masked"]}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'data: {"event":"guardrail","seq":2,"stage":"output","kind":"pii","decision":"redacted","reasons":[]}\n\n',
          ),
        );
        controller.close();
      },
    });
    const events: WorkflowEvent[] = [];

    await consumeSseStream(new Response(stream, { status: 200 }), (event) =>
      events.push(event),
    );

    expect(events.map((event) => event.event)).toEqual([
      "tool_call",
      "guardrail",
    ]);
  });

  it("ignores malformed and unknown frames without dropping later valid events", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {not-json}\n\n'));
        controller.enqueue(encoder.encode('data: {"event":"future_event","seq":3}\n\n'));
        controller.enqueue(encoder.encode('data: {"event":"planning_completed","seq":3}\n\n'));
        controller.enqueue(
          encoder.encode('data: {"event":"token","seq":4,"node":"draft","text":"Merhaba"}\n\n'),
        );
        controller.close();
      },
    });
    const events: WorkflowEvent[] = [];

    await consumeSseStream(new Response(stream, { status: 200 }), (event) =>
      events.push(event),
    );

    expect(events).toEqual([
      { event: "token", seq: 4, node: "draft", text: "Merhaba" },
    ]);
  });

  it("passes through notice events instead of dropping them", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"event":"notice","seq":1,"node":"revise_audit","level":"info","title":"Çelişki bulundu","message":"Talimat uygulandı ama..."}\n\n',
          ),
        );
        controller.close();
      },
    });
    const events: WorkflowEvent[] = [];

    await consumeSseStream(new Response(stream, { status: 200 }), (event) =>
      events.push(event),
    );

    expect(events).toEqual([
      {
        event: "notice",
        seq: 1,
        node: "revise_audit",
        level: "info",
        title: "Çelişki bulundu",
        message: "Talimat uygulandı ama...",
      },
    ]);
  });

  it("keeps distinct events that arrive out of sequence while still deduplicating", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"event":"token","seq":8,"node":"reply","text":"son"}\n\n'));
        controller.enqueue(encoder.encode('data: {"event":"token","seq":7,"node":"reply","text":"önce"}\n\n'));
        controller.enqueue(encoder.encode('data: {"event":"token","seq":8,"node":"reply","text":"tekrar"}\n\n'));
        controller.close();
      },
    });
    const events: WorkflowEvent[] = [];

    await consumeSseStream(new Response(stream, { status: 200 }), (event) => events.push(event));

    expect(events.map((event) => event.seq)).toEqual([8, 7]);
  });

  it("passes through question events instead of dropping them", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"event":"question","seq":1,"node":"clarify","question":"Taslak mı, revizyon mu?","options":[{"value":"draft","label":"Taslak"}],"allow_free_text":true}\n\n',
          ),
        );
        controller.close();
      },
    });
    const events: WorkflowEvent[] = [];

    await consumeSseStream(new Response(stream, { status: 200 }), (event) =>
      events.push(event),
    );

    expect(events).toEqual([
      {
        event: "question",
        seq: 1,
        node: "clarify",
        question: "Taslak mı, revizyon mu?",
        options: [{ value: "draft", label: "Taslak" }],
        allow_free_text: true,
      },
    ]);
  });
});

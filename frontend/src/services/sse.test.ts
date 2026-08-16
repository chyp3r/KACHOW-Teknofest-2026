import { describe, expect, it } from "vitest";
import { readRawSseStream } from "./sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

describe("readRawSseStream", () => {
  it("yields the raw payload for a real data frame", async () => {
    const values: unknown[] = [];
    await readRawSseStream(
      new Response(streamOf('data: {"id":"msg-1","body":"merhaba"}\n\n'), { status: 200 }),
      (value) => values.push(value),
    );
    expect(values).toEqual([{ id: "msg-1", body: "merhaba" }]);
  });

  it("ignores the connected handshake and error frames", async () => {
    const values: unknown[] = [];
    await readRawSseStream(
      new Response(
        streamOf(
          'data: {"event":"connected"}\n\n',
          'data: {"event":"error","message":"boom"}\n\n',
          'data: {"id":"msg-2","body":"gerçek mesaj"}\n\n',
        ),
        { status: 200 },
      ),
      (value) => values.push(value),
    );
    expect(values).toEqual([{ id: "msg-2", body: "gerçek mesaj" }]);
  });

  it("ignores keep-alive comment lines and malformed frames", async () => {
    const values: unknown[] = [];
    await readRawSseStream(
      new Response(
        streamOf(
          ": keep-alive\n\n",
          "data: {not-json}\n\n",
          'data: {"id":"msg-3"}\n\n',
        ),
        { status: 200 },
      ),
      (value) => values.push(value),
    );
    expect(values).toEqual([{ id: "msg-3" }]);
  });

  it("reassembles a frame split across multiple stream chunks", async () => {
    const values: unknown[] = [];
    await readRawSseStream(
      new Response(streamOf('data: {"id":"msg-4",', '"body":"parçalı"}\n\n'), { status: 200 }),
      (value) => values.push(value),
    );
    expect(values).toEqual([{ id: "msg-4", body: "parçalı" }]);
  });
});

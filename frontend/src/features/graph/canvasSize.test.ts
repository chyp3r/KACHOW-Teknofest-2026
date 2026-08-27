import { describe, expect, it } from "vitest";
import { DEFAULT_HEIGHT, DEFAULT_WIDTH } from "./forceLayout";
import { MAX_LAYOUT_SCALE, graphCanvasSize } from "./canvasSize";

describe("graphCanvasSize", () => {
  it("never shrinks below the base dimensions", () => {
    for (const count of [0, 1, 10, 36]) {
      const { width, height } = graphCanvasSize(count);
      expect(width).toBeGreaterThanOrEqual(DEFAULT_WIDTH);
      expect(height).toBeGreaterThanOrEqual(DEFAULT_HEIGHT);
    }
  });

  it("grows with the node count", () => {
    const small = graphCanvasSize(40);
    const large = graphCanvasSize(400);
    expect(large.width).toBeGreaterThan(small.width);
    expect(large.height).toBeGreaterThan(small.height);
    // keeps the base aspect ratio
    expect(large.width / large.height).toBeCloseTo(DEFAULT_WIDTH / DEFAULT_HEIGHT, 1);
  });

  it("caps the scale so a huge graph stays pannable", () => {
    const huge = graphCanvasSize(100_000);
    expect(huge.width).toBeLessThanOrEqual(Math.round(DEFAULT_WIDTH * MAX_LAYOUT_SCALE));
    expect(huge.height).toBeLessThanOrEqual(Math.round(DEFAULT_HEIGHT * MAX_LAYOUT_SCALE));
  });

  it("quantizes so small node-count changes do not resize", () => {
    expect(graphCanvasSize(40)).toEqual(graphCanvasSize(45));
  });
});

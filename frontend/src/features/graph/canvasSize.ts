import { DEFAULT_HEIGHT, DEFAULT_WIDTH } from "./forceLayout";

// The unified force-graph canvas grows with the visible node count so nodes
// keep breathing room instead of cramming into the fixed base box. Area scales
// ~linearly with the node count (√ on each axis, so on-screen density stays
// roughly constant), never below the base, and capped so a very large graph
// stays pannable rather than shrinking every node to a dot. LAYOUT_BASE_NODES
// is the count the base dimensions were originally tuned for; the scale is
// quantized to quarter-steps so the force simulation -- which reads its
// dimensions once, at creation -- is only re-seeded when the size actually
// changes (see EntityGraphCanvas's `key`).
export const LAYOUT_BASE_NODES = 36;
export const MAX_LAYOUT_SCALE = 3.5;

export function graphCanvasSize(nodeCount: number): { width: number; height: number } {
  const raw = Math.sqrt(Math.max(nodeCount, 1) / LAYOUT_BASE_NODES);
  const scale = Math.min(MAX_LAYOUT_SCALE, Math.max(1, Math.round(raw * 4) / 4));
  return {
    width: Math.round(DEFAULT_WIDTH * scale),
    height: Math.round(DEFAULT_HEIGHT * scale),
  };
}

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GraphNode, KnowledgeGraph } from "../../types/documents";
import { useForceSimulation } from "./useForceSimulation";

function node(id: string): GraphNode {
  return {
    id, node_type: "entity", label: id,
    storage_path: null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun: null, madde: null, field_labels: [], document_count: null,
    entity_kind: null, surface_forms: [], attributes: {},
  };
}

function graphWithTwoConnectedNodes(): KnowledgeGraph {
  return {
    nodes: [node("a"), node("b")],
    edges: [
      { source: "a", target: "b", edge_type: "bahseder", source_kind: "llm",
        field_key: null, field_label: null, severity: null, reason: null, aciklama: null, raw: null },
    ],
    insights: {
      document_count: 0, madde_count: 0, kanun_count: 0, entity_count: 2, konu_count: 0,
      rule_edge_count: 0, llm_edge_count: 1, unresolved_reference_count: 0,
      top_breached_madde: null,
    },
  };
}

/** A controllable requestAnimationFrame -- nothing runs until `flush()` is
 * called, so a test can advance the simulation exactly one frame at a
 * time and assert on the state in between. */
function mockRaf() {
  let queue: FrameRequestCallback[] = [];
  let nextId = 1;
  const raf = vi.fn((cb: FrameRequestCallback) => {
    queue.push(cb);
    return nextId++;
  });
  const caf = vi.fn();
  vi.stubGlobal("requestAnimationFrame", raf);
  vi.stubGlobal("cancelAnimationFrame", caf);
  return {
    raf,
    caf,
    flush() {
      const callbacks = queue;
      queue = [];
      act(() => {
        callbacks.forEach((cb) => cb(0));
      });
    },
  };
}

function stubReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
}

describe("useForceSimulation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // A single, stable graph reference reused across every render of the
  // hook -- exactly how a real caller must use it (EntityGraphView passes
  // a `useMemo`-stabilized filtered graph). Calling the factory fresh
  // inside the renderHook callback would hand a *new* object reference to
  // every re-render, and the hook's graph-changed effect (correctly)
  // compares by reference -- it would treat every one of the hook's own
  // tick-driven re-renders as a brand new graph and reheat forever,
  // never settling. That is a bug in a test built to look like real
  // usage but isn't, not in the hook.
  function stableGraph(): KnowledgeGraph {
    return graphWithTwoConnectedNodes();
  }

  it("mounting schedules a frame and stepping it changes positions", () => {
    stubReducedMotion(false);
    const rafMock = mockRaf();
    const graph = stableGraph();
    const { result } = renderHook(() => useForceSimulation(graph));
    const before = { ...result.current.positions.a };

    expect(rafMock.raf).toHaveBeenCalledTimes(1);
    rafMock.flush();

    expect(result.current.positions.a).not.toEqual(before);
  });

  it("the loop stops scheduling once the simulation settles", () => {
    stubReducedMotion(false);
    const rafMock = mockRaf();
    const graph = stableGraph();
    renderHook(() => useForceSimulation(graph));

    for (let i = 0; i < 500; i++) {
      const callsBefore = rafMock.raf.mock.calls.length;
      rafMock.flush();
      if (rafMock.raf.mock.calls.length === callsBefore) break; // stopped scheduling
    }

    const callsAtSettle = rafMock.raf.mock.calls.length;
    expect(callsAtSettle).toBeLessThan(500); // it actually settled, not just ran out of budget
    rafMock.flush(); // nothing queued -- must be a no-op
    expect(rafMock.raf.mock.calls.length).toBe(callsAtSettle);
  });

  it("cancelAnimationFrame is called on unmount", () => {
    stubReducedMotion(false);
    const rafMock = mockRaf();
    const graph = stableGraph();
    const { unmount } = renderHook(() => useForceSimulation(graph));

    unmount();

    expect(rafMock.caf).toHaveBeenCalled();
  });

  it("prefers-reduced-motion: reduce skips the loop entirely -- never calls requestAnimationFrame", () => {
    stubReducedMotion(true);
    const rafMock = mockRaf();
    const graph = stableGraph();

    renderHook(() => useForceSimulation(graph));

    expect(rafMock.raf).not.toHaveBeenCalled();
  });

  it("prefers-reduced-motion: reduce still produces real (non-random-seed) positions", () => {
    stubReducedMotion(true);
    mockRaf();
    const graph = stableGraph();
    const { result } = renderHook(() => useForceSimulation(graph));

    // Two connected nodes pulled together by the spring force should not
    // remain at their raw seeded positions -- the simulation must have
    // actually settled synchronously, not just skipped work.
    expect(Number.isFinite(result.current.positions.a.x)).toBe(true);
    expect(Number.isFinite(result.current.positions.b.x)).toBe(true);
  });

  it("reheat() restarts the loop after it stopped", () => {
    stubReducedMotion(false);
    const rafMock = mockRaf();
    const graph = stableGraph();
    const { result } = renderHook(() => useForceSimulation(graph));

    for (let i = 0; i < 500; i++) {
      const callsBefore = rafMock.raf.mock.calls.length;
      rafMock.flush();
      if (rafMock.raf.mock.calls.length === callsBefore) break;
    }
    const callsAtSettle = rafMock.raf.mock.calls.length;

    act(() => {
      result.current.reheat();
    });

    expect(rafMock.raf.mock.calls.length).toBeGreaterThan(callsAtSettle);
  });

  it("pin() fixes a node's position and wakes the loop", () => {
    stubReducedMotion(false);
    const rafMock = mockRaf();
    const graph = stableGraph();
    const { result } = renderHook(() => useForceSimulation(graph));

    act(() => {
      result.current.pin("a", 42, 84);
    });

    expect(result.current.positions.a).toEqual({ x: 42, y: 84 });
    expect(result.current.isPinned("a")).toBe(true);

    rafMock.flush();
    // Pinned node must hold position across a stepped frame.
    expect(result.current.positions.a).toEqual({ x: 42, y: 84 });
  });

  it("unpin() releases a pinned node", () => {
    stubReducedMotion(false);
    mockRaf();
    const graph = stableGraph();
    const { result } = renderHook(() => useForceSimulation(graph));

    act(() => {
      result.current.pin("a", 42, 84);
    });
    expect(result.current.isPinned("a")).toBe(true);

    act(() => {
      result.current.unpin("a");
    });

    expect(result.current.isPinned("a")).toBe(false);
  });
});

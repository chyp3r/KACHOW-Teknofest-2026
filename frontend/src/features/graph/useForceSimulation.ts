import { useCallback, useEffect, useRef, useState } from "react";
import type { KnowledgeGraph } from "../../types/documents";
import { createForceSimulation, type ForceSimulation, type ForceSimulationOptions, type Point } from "./forceLayout";

//: No `requestAnimationFrame`-driven loop exists anywhere else in this repo
//: (`MessageList.tsx`'s is one-shot) -- this hook establishes the pattern:
//: one `step()` per frame, stop scheduling once the simulation settles,
//: `cancelAnimationFrame` on unmount. Reheating (a drag, a filter change)
//: wakes it back up.

const EMPTY_GRAPH: KnowledgeGraph = {
  nodes: [],
  edges: [],
  insights: {
    document_count: 0, madde_count: 0, kanun_count: 0, entity_count: 0, konu_count: 0,
    rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
    top_breached_madde: null,
  },
};

function prefersReducedMotion(): boolean {
  // Already used unguarded elsewhere in this codebase (ThemeProvider.tsx),
  // so calling it directly here is consistent with an established,
  // working pattern -- jsdom returns matches: false by default, which is
  // exactly the "animate" branch this hook should take under test.
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

export interface UseForceSimulationResult {
  /** The simulation's live position map -- same object identity across
   * renders (only its contents mutate); re-read after every render this
   * hook triggers via its internal tick counter. */
  positions: Record<string, Point>;
  /** Wake the simulation back up (e.g. before a drag) without pinning
   * anything. */
  reheat: (target?: number) => void;
  /** Fix a node at a position and wake the simulation -- what dragging
   * calls on every pointer-move. */
  pin: (id: string, x: number, y: number) => void;
  unpin: (id: string) => void;
  isPinned: (id: string) => boolean;
}

/** Drives a live `ForceSimulation` (see `forceLayout.ts`) with
 * `requestAnimationFrame`, sleeping once settled and waking on
 * interaction. Under `prefers-reduced-motion: reduce`, the simulation is
 * settled synchronously up front and the loop never runs at all -- the
 * graph appears already at rest, no animation. */
export function useForceSimulation(
  graph: KnowledgeGraph | null,
  options: ForceSimulationOptions = {},
): UseForceSimulationResult {
  const reducedMotionRef = useRef<boolean | null>(null);
  if (reducedMotionRef.current === null) reducedMotionRef.current = prefersReducedMotion();
  const reducedMotion = reducedMotionRef.current;

  const simulationRef = useRef<ForceSimulation | null>(null);
  const previousGraphRef = useRef<KnowledgeGraph | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const [, setTick] = useState(0);

  if (!simulationRef.current) {
    simulationRef.current = createForceSimulation(graph ?? EMPTY_GRAPH, options);
    previousGraphRef.current = graph;
    if (reducedMotion) {
      while (!simulationRef.current.isSettled()) simulationRef.current.step();
    }
  }

  const startLoopIfNeeded = useCallback(() => {
    if (reducedMotion || rafIdRef.current !== null) return;
    const simulation = simulationRef.current;
    if (!simulation || simulation.isSettled()) return;
    const frame = () => {
      simulation.step();
      setTick((t) => t + 1);
      rafIdRef.current = simulation.isSettled() ? null : requestAnimationFrame(frame);
    };
    rafIdRef.current = requestAnimationFrame(frame);
  }, [reducedMotion]);

  useEffect(() => {
    startLoopIfNeeded();
    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, [startLoopIfNeeded]);

  useEffect(() => {
    const simulation = simulationRef.current;
    if (!simulation || !graph || graph === previousGraphRef.current) return;
    previousGraphRef.current = graph;
    simulation.syncGraph(graph);
    if (reducedMotion) {
      while (!simulation.isSettled()) simulation.step();
      setTick((t) => t + 1);
    } else {
      simulation.reheat();
      startLoopIfNeeded();
    }
  }, [graph, reducedMotion, startLoopIfNeeded]);

  const reheat = useCallback(
    (target?: number) => {
      simulationRef.current?.reheat(target);
      startLoopIfNeeded();
    },
    [startLoopIfNeeded],
  );

  const pin = useCallback(
    (id: string, x: number, y: number) => {
      const simulation = simulationRef.current;
      if (!simulation) return;
      simulation.pin(id, x, y);
      simulation.reheat();
      setTick((t) => t + 1);
      startLoopIfNeeded();
    },
    [startLoopIfNeeded],
  );

  const unpin = useCallback((id: string) => {
    // Must trigger a re-render, not just mutate the simulation: an
    // isPinned()-driven CSS class (or anything else read during render)
    // would otherwise keep showing the *previous* render's pinned state
    // until some unrelated update happened to fire next -- calling
    // isPinned() fresh afterward returns the right answer, but nothing
    // painted it.
    simulationRef.current?.unpin(id);
    setTick((t) => t + 1);
  }, []);

  const isPinned = useCallback((id: string) => simulationRef.current?.isPinned(id) ?? false, []);

  return {
    positions: simulationRef.current.positions,
    reheat,
    pin,
    unpin,
    isPinned,
  };
}

// Split out of InteractiveGraphViewport.tsx solely because a file that
// exports both a component and a non-component (a context + hook) trips
// react-refresh/only-export-components, and this repo's lint runs with
// --max-warnings 0 -- not a design preference otherwise. The viewport
// still owns all the camera math; this file only owns the plumbing that
// exposes one piece of it (graphPointAt) to nested children.

import { createContext, useContext } from "react";

export interface Point {
  x: number;
  y: number;
}

//: Converts a screen (client) pixel to a graph/SVG-space point, correctly
//: accounting for the current camera (pan/zoom) and the viewport's
//: `preserveAspectRatio="xMidYMid meet"` letterboxing. Node-level dragging
//: (added on top of the viewport by `EntityGraphView`) needs exactly this
//: conversion and previously had no way to reach it -- every camera-math
//: helper lived as a closure inside `InteractiveGraphViewport` with no
//: ref, render-prop, or context exposing it to children.
export interface GraphViewportContextValue {
  graphPointAt: (clientPoint: Point) => Point;
}

export const GraphViewportContext = createContext<GraphViewportContextValue | null>(null);

/** Read the enclosing `InteractiveGraphViewport`'s screen->graph
 * converter. Throws outside a provider -- a node that drags itself is
 * always rendered inside the viewport it drags within, so reaching this
 * hook from anywhere else is a programming error, not a runtime
 * possibility to design around. */
export function useGraphViewport(): GraphViewportContextValue {
  const context = useContext(GraphViewportContext);
  if (!context) {
    throw new Error("useGraphViewport must be called from within an InteractiveGraphViewport");
  }
  return context;
}

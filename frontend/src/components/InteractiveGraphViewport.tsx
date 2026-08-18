import { Minus, Plus, RotateCcw } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type WheelEvent,
} from "react";
import { IconButton } from "./Button";

const DEFAULT_BASE_WIDTH = 560;
const DEFAULT_BASE_HEIGHT = 700;
const MIN_SCALE = 0.6;
const MAX_SCALE = 3;
const SCALE_STEP = 0.2;

interface Camera {
  centerX: number;
  centerY: number;
  scale: number;
}

interface Point {
  x: number;
  y: number;
}

interface DragStart {
  point: Point;
  centerX: number;
  centerY: number;
  unitsPerPixel: number;
}

interface PinchStart {
  distance: number;
  scale: number;
  anchor: Point;
}

const clampScale = (scale: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
const distance = (left: Point, right: Point) =>
  Math.hypot(right.x - left.x, right.y - left.y);
const midpoint = (left: Point, right: Point): Point => ({
  x: (left.x + right.x) / 2,
  y: (left.y + right.y) / 2,
});
const pointerPoint = (event: PointerEvent<HTMLDivElement>): Point => ({
  x: Number.isFinite(event.clientX) ? event.clientX : 0,
  y: Number.isFinite(event.clientY) ? event.clientY : 0,
});

export function InteractiveGraphViewport({
  children,
  ariaLabel,
  baseWidth = DEFAULT_BASE_WIDTH,
  baseHeight = DEFAULT_BASE_HEIGHT,
}: {
  children: ReactNode;
  ariaLabel: string;
  // Lets a caller with a taller/wider canvas (e.g. the knowledge graph's
  // bipartite layout, which grows with document/madde count) start framed
  // correctly instead of at DecisionFlow's fixed 560x700.
  baseWidth?: number;
  baseHeight?: number;
}) {
  const initialCamera: Camera = { centerX: baseWidth / 2, centerY: baseHeight / 2, scale: 1 };
  const [camera, setCamera] = useState<Camera>(initialCamera);
  const [dragging, setDragging] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef(camera);
  const pointers = useRef(new Map<number, Point>());
  const dragStart = useRef<DragStart | null>(null);
  const pinchStart = useRef<PinchStart | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === "undefined") return;
    let previousSize = "";
    const observer = new ResizeObserver(([entry]) => {
      const nextSize = `${Math.round(entry.contentRect.width)}x${Math.round(entry.contentRect.height)}`;
      if (!previousSize) {
        previousSize = nextSize;
        return;
      }
      if (nextSize === previousSize) return;
      previousSize = nextSize;
      cameraRef.current = initialCamera;
      setCamera(initialCamera);
    });
    observer.observe(canvas);
    return () => observer.disconnect();
    // baseWidth/baseHeight are stable per mount for every caller today; re-running
    // this on their change would also need to re-derive initialCamera, which is
    // intentionally not memoised.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateCamera = (next: Camera) => {
    cameraRef.current = next;
    setCamera(next);
  };

  const dimensionsAt = (scale: number) => ({
    width: baseWidth / scale,
    height: baseHeight / scale,
  });

  const viewBoxAt = (value: Camera) => {
    const dimensions = dimensionsAt(value.scale);
    return {
      ...dimensions,
      x: value.centerX - dimensions.width / 2,
      y: value.centerY - dimensions.height / 2,
    };
  };

  const renderedGeometry = (scale: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    const width = Math.max(1, rect?.width ?? baseWidth);
    const height = Math.max(1, rect?.height ?? baseHeight);
    const dimensions = dimensionsAt(scale);
    const pixelsPerUnit = Math.min(width / dimensions.width, height / dimensions.height);
    return {
      rect: rect ?? ({ left: 0, top: 0, width, height } as DOMRect),
      dimensions,
      pixelsPerUnit,
      offsetX: (width - dimensions.width * pixelsPerUnit) / 2,
      offsetY: (height - dimensions.height * pixelsPerUnit) / 2,
    };
  };

  const graphPointAt = (clientPoint: Point, value = cameraRef.current): Point => {
    const viewBox = viewBoxAt(value);
    const geometry = renderedGeometry(value.scale);
    return {
      x:
        viewBox.x +
        (clientPoint.x - geometry.rect.left - geometry.offsetX) /
          geometry.pixelsPerUnit,
      y:
        viewBox.y +
        (clientPoint.y - geometry.rect.top - geometry.offsetY) /
          geometry.pixelsPerUnit,
    };
  };

  const cameraForAnchor = (anchor: Point, clientPoint: Point, scale: number): Camera => {
    const geometry = renderedGeometry(scale);
    const xInsideView =
      (clientPoint.x - geometry.rect.left - geometry.offsetX) /
      geometry.pixelsPerUnit;
    const yInsideView =
      (clientPoint.y - geometry.rect.top - geometry.offsetY) /
      geometry.pixelsPerUnit;
    return {
      scale,
      centerX: anchor.x - xInsideView + geometry.dimensions.width / 2,
      centerY: anchor.y - yInsideView + geometry.dimensions.height / 2,
    };
  };

  const zoomAt = (nextScale: number, clientPoint?: Point) => {
    const current = cameraRef.current;
    const scale = clampScale(nextScale);
    if (scale === current.scale) return;
    if (!clientPoint) {
      updateCamera({ ...current, scale });
      return;
    }
    const anchor = graphPointAt(clientPoint, current);
    updateCamera(cameraForAnchor(anchor, clientPoint, scale));
  };

  const reset = () => updateCamera(initialCamera);

  const beginPointer = (event: PointerEvent<HTMLDivElement>) => {
    if ((event.target as Element).closest(".node")) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = pointerPoint(event);
    pointers.current.set(event.pointerId, point);
    const activePointers = [...pointers.current.values()];

    if (activePointers.length === 1) {
      const current = cameraRef.current;
      dragStart.current = {
        point,
        centerX: current.centerX,
        centerY: current.centerY,
        unitsPerPixel: 1 / renderedGeometry(current.scale).pixelsPerUnit,
      };
      pinchStart.current = null;
      setDragging(true);
      return;
    }

    if (activePointers.length === 2) {
      const center = midpoint(activePointers[0], activePointers[1]);
      pinchStart.current = {
        distance: Math.max(1, distance(activePointers[0], activePointers[1])),
        scale: cameraRef.current.scale,
        anchor: graphPointAt(center),
      };
      dragStart.current = null;
    }
  };

  const movePointer = (event: PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return;
    const point = pointerPoint(event);
    pointers.current.set(event.pointerId, point);
    const activePointers = [...pointers.current.values()];

    if (activePointers.length === 2 && pinchStart.current) {
      const start = pinchStart.current;
      const center = midpoint(activePointers[0], activePointers[1]);
      const scale = clampScale(
        start.scale * (distance(activePointers[0], activePointers[1]) / start.distance),
      );
      updateCamera(cameraForAnchor(start.anchor, center, scale));
      return;
    }

    if (activePointers.length === 1 && dragStart.current) {
      const start = dragStart.current;
      updateCamera({
        ...cameraRef.current,
        centerX: start.centerX - (point.x - start.point.x) * start.unitsPerPixel,
        centerY: start.centerY - (point.y - start.point.y) * start.unitsPerPixel,
      });
    }
  };

  const endPointer = (event: PointerEvent<HTMLDivElement>) => {
    pointers.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    pinchStart.current = null;

    const remaining = [...pointers.current.values()];
    if (remaining.length === 1) {
      const current = cameraRef.current;
      dragStart.current = {
        point: remaining[0],
        centerX: current.centerX,
        centerY: current.centerY,
        unitsPerPixel: 1 / renderedGeometry(current.scale).pixelsPerUnit,
      };
    } else {
      dragStart.current = null;
      setDragging(false);
    }
  };

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const direction = event.deltaY < 0 ? 1 : -1;
    zoomAt(cameraRef.current.scale + direction * SCALE_STEP, {
      x: event.clientX,
      y: event.clientY,
    });
  };

  const handleKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.currentTarget !== event.target) return;
    const current = cameraRef.current;
    const panAmount = 28 / current.scale;
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomAt(current.scale + SCALE_STEP);
    } else if (event.key === "-") {
      event.preventDefault();
      zoomAt(current.scale - SCALE_STEP);
    } else if (event.key === "0") {
      event.preventDefault();
      reset();
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      updateCamera({ ...current, centerX: current.centerX - panAmount });
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      updateCamera({ ...current, centerX: current.centerX + panAmount });
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      updateCamera({ ...current, centerY: current.centerY - panAmount });
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      updateCamera({ ...current, centerY: current.centerY + panAmount });
    }
  };

  const viewBox = viewBoxAt(camera);

  return (
    <div className="graph-container decision-graph-container interactive-graph">
      <div className="graph-toolbar" role="toolbar" aria-label="Grafik görünümü kontrolleri">
        <IconButton
          icon={<Minus />}
          aria-label="Grafiği küçült"
          title="Küçült"
          disabled={camera.scale <= MIN_SCALE}
          onClick={() => zoomAt(cameraRef.current.scale - SCALE_STEP)}
        />
        <output aria-live="polite" aria-label={`Yakınlaştırma %${Math.round(camera.scale * 100)}`}>
          %{Math.round(camera.scale * 100)}
        </output>
        <IconButton
          icon={<Plus />}
          aria-label="Grafiği büyüt"
          title="Büyüt"
          disabled={camera.scale >= MAX_SCALE}
          onClick={() => zoomAt(cameraRef.current.scale + SCALE_STEP)}
        />
        <IconButton icon={<RotateCcw />} aria-label="Grafik görünümünü sıfırla" tooltip="Sıfırla" onClick={reset} />
      </div>

      <div ref={canvasRef} className="graph-canvas">
        <div
          className={`graph-pan-surface ${dragging ? "is-dragging" : ""}`}
          role="region"
          tabIndex={0}
          aria-label="Etkileşimli teknik grafik"
          aria-describedby="graph-interaction-help"
          onPointerDown={beginPointer}
          onPointerMove={movePointer}
          onPointerUp={endPointer}
          onPointerCancel={endPointer}
          onWheel={handleWheel}
          onKeyDown={handleKeyboard}
        >
          <svg
            ref={svgRef}
            width="100%"
            height="100%"
            viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label={ariaLabel}
            data-testid="interactive-graph-svg"
          >
            {children}
          </svg>
        </div>
      </div>
      <p id="graph-interaction-help" className="graph-interaction-help">
        Sürükleyerek taşıyın · Tekerlek veya +/− ile yakınlaştırın · 0 ile sıfırlayın
      </p>
    </div>
  );
}

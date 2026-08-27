import { useEffect, useRef, useState } from "react";
import { MarkdownMessage } from "./MarkdownMessage";

const FRAME_INTERVAL_MS = 24;
const MAX_ANIMATION_STEPS = 220;

export function AnimatedMessageText({
  text,
  animate = false,
  onProgress,
}: {
  text: string;
  animate?: boolean;
  onProgress?: () => void;
}) {
  const animationTarget = useRef<string | null>(animate ? text : null);
  const [visibleLength, setVisibleLength] = useState(animate ? Math.min(1, text.length) : text.length);

  useEffect(() => {
    if (animate && animationTarget.current !== text) {
      animationTarget.current = text;
      setVisibleLength(Math.min(1, text.length));
    } else if (!animate && animationTarget.current !== text) {
      animationTarget.current = null;
      setVisibleLength(text.length);
      return;
    }

    if (animationTarget.current !== text) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      animationTarget.current = null;
      setVisibleLength(text.length);
      return;
    }

    const charactersPerFrame = Math.max(1, Math.ceil(text.length / MAX_ANIMATION_STEPS));
    const timer = window.setInterval(() => {
      setVisibleLength((current) => {
        const next = Math.min(text.length, current + charactersPerFrame);
        if (next >= text.length) {
          window.clearInterval(timer);
          animationTarget.current = null;
        }
        return next;
      });
      onProgress?.();
    }, FRAME_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [animate, onProgress, text]);

  const isAnimating = visibleLength < text.length;
  if (!isAnimating) {
    return <div className="markdown-content"><MarkdownMessage text={text} /></div>;
  }

  return (
    <div className="markdown-content">
      <div aria-hidden="true">
        <MarkdownMessage text={text.slice(0, visibleLength)} />
        <span className="streaming-caret" />
      </div>
      <span className="sr-only">{text}</span>
    </div>
  );
}

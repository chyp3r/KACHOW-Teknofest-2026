/** Geçen süreyi kısa, okunur bir etikete çevirir: `"3 sn"`, `"1:05"`.
 *
 * ThinkingBubble ile DocumentTable'ın analiz sayacı aynı biçimi kullanır --
 * modül-yerel iki kopya yerine tek kaynak. */
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}:${seconds.toString().padStart(2, "0")}` : `${seconds} sn`;
}

/** Capitalizes only the first character, Turkish-aware ("i" → "İ"). */
export function capitalizeFirst(value: string): string {
  if (!value) return value;
  const first = value.slice(0, 1);
  const upper = first.toLocaleUpperCase("tr-TR");
  return upper === first ? value : upper + value.slice(1);
}

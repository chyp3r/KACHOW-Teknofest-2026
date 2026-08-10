import type { PaginatedResponse } from "../types/api";

export async function collectPages<T>(
  load: (page: number) => Promise<PaginatedResponse<T>>,
): Promise<PaginatedResponse<T>> {
  const first = await load(1);
  const items = [...first.items];
  for (let page = 2; page <= first.pages; page += 1) {
    const next = await load(page);
    items.push(...next.items);
  }
  return { ...first, items };
}

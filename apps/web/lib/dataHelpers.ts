/**
 * Shared helpers for defensively reading loosely-typed API responses.
 *
 * The backend list endpoints return either a bare array or an object with an
 * `items` array, and field names vary (snake_case vs camelCase, id vs *_id).
 * These primitives were previously copy-pasted across the dashboard, invoices,
 * vendors, and alerts pages; they now live in one place.
 */
export type UnknownRecord = Record<string, unknown>;

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function asObject(value: unknown): UnknownRecord {
  return value && typeof value === "object" ? (value as UnknownRecord) : {};
}

/**
 * Normalize a list response to an array, accepting either `[...]` or
 * `{ items: [...] }`. (For any real response these two forms are mutually
 * exclusive, so the order of preference does not affect the result.)
 */
export function extractItems(raw: unknown): unknown[] {
  const obj = asObject(raw);

  if (Array.isArray(obj.items)) {
    return obj.items;
  }

  return asArray(raw);
}

/**
 * Return the first present (non-null/undefined) value among `keys`, coerced to
 * a string. Mirrors the `obj.a ?? obj.b ?? obj.c` pattern: the FIRST present
 * key wins and only its value is type-checked.
 *
 * @param numberToString  when true, numeric values are stringified; otherwise a
 *                        non-string first value yields the fallback.
 * @param fallback        returned when no key yields a usable value ("" or "—").
 */
export function pickString(
  obj: UnknownRecord,
  keys: string[],
  opts: { numberToString?: boolean; fallback?: string } = {},
): string {
  const { numberToString = false, fallback = "" } = opts;
  let v: unknown = undefined;
  for (const key of keys) {
    if (obj[key] !== undefined && obj[key] !== null) {
      v = obj[key];
      break;
    }
  }
  if (typeof v === "string") return v;
  if (numberToString && typeof v === "number") return String(v);
  return fallback;
}

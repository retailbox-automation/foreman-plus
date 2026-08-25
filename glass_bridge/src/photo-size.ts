/**
 * Photo size selection + degradation ladder.
 *
 * The SDK's PhotoRequestOptions (verified verbatim in
 * @mentra/sdk/dist/index.js.map, PhotoRequestOptions):
 *   small:  640x480   (VGA)  — ultra-fast transfers
 *   medium: 1280x720  (720p) — good balance (DEFAULT when no size is passed)
 *   large:  1920x1080 (1080p)— high quality
 *   full:   native sensor resolution — maximum detail (slower transfer)
 * (NB: our delivered "default" photos measure 1280x960 (4:3), not the 1280x720
 * the doc-comment claims — the doc and the hardware disagree; trust the pixels.)
 *
 * Why a ladder: requestPhoto has a hardcoded 30s SDK timeout and the BT link is
 * slow (N12b — even the default size times out sometimes). A bigger photo makes
 * that strictly worse, so any explicit size must be able to fall back DOWN
 * rather than return nothing.
 */

export type PhotoSize = "small" | "medium" | "large" | "full";

export const PHOTO_SIZES: readonly PhotoSize[] = ["small", "medium", "large", "full"] as const;

/** Ordered largest→smallest, for building fallback ladders. */
const DESCENDING: readonly PhotoSize[] = ["full", "large", "medium", "small"] as const;

/** Parse an untrusted value (env var, HTTP body) into a PhotoSize. */
export function parsePhotoSize(v: unknown): PhotoSize | undefined {
  if (typeof v !== "string") return undefined;
  const s = v.trim().toLowerCase();
  return (PHOTO_SIZES as readonly string[]).includes(s) ? (s as PhotoSize) : undefined;
}

/**
 * Build the attempt ladder for a requested size.
 *
 * `undefined` means "send no size option at all" — the SDK default. It is kept
 * distinct from an explicit "medium" so we never change the default request
 * shape by accident.
 *
 * Ladder rules:
 *  - no size requested → [default, small]   (unchanged legacy behaviour, N12b)
 *  - "small" requested → [small]            (nothing smaller to fall back to)
 *  - otherwise         → [requested, …each smaller size…]
 */
export function photoSizeLadder(size?: PhotoSize): Array<PhotoSize | undefined> {
  if (!size) return [undefined, "small"];
  const smaller = DESCENDING.slice(DESCENDING.indexOf(size) + 1);
  return [size, ...smaller];
}

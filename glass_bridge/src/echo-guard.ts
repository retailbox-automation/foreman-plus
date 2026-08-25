/**
 * echo-guard.ts — ring buffer of recently-spoken TTS text, used to detect
 * when a glasses-mic transcript is actually our own voice being picked up
 * (I-3 fix).
 *
 * The original bridge kept a SINGLE `lastSpokenText` slot that `speakTracked`
 * overwrote on every call. With sentence-by-sentence reply speech
 * (SentenceStream feeding `/brain/reply` one sentence at a time), a later
 * spoken sentence overwrites the slot before the glasses mic finishes
 * picking up an EARLIER one — so an echo of that earlier sentence no longer
 * matches `lastSpokenText` and slips through the filter, occasionally
 * re-triggering a voice command via the echo path (2026-07-13: TTS itself
 * started/stopped a stream).
 *
 * `EchoGuard` instead keeps every text spoken within the last `windowMs`
 * and flags a heard transcript as an echo if it substantially overlaps ANY
 * of them, not just the most recent one.
 *
 * Pure logic, no I/O — testable without booting the MentraOS session.
 */

const DEFAULT_WINDOW_MS = 15_000;
const OVERLAP_THRESHOLD = 0.6;

/**
 * Punctuation becomes a SPACE, not nothing. Deleting it silently welded
 * hyphenated phrases into one token — "фото-видео-стриму" turned into
 * "фотовидеостриму" — which on 2026-08-04 cost the guard a real echo: the
 * heard fragment had two long words, ASR had mangled the first one, and one
 * match out of two fell under the threshold. The reply was then aborted by
 * the barge-in path and the assistant answered its own voice.
 */
function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-zа-яё0-9]+/gi, " ")
    .trim();
}

export class EchoGuard {
  private readonly windowMs: number;
  private readonly now: () => number;
  private history: Array<{ text: string; atMs: number }> = [];

  constructor(opts?: { windowMs?: number; now?: () => number }) {
    this.windowMs = opts?.windowMs ?? DEFAULT_WINDOW_MS;
    this.now = opts?.now ?? Date.now;
  }

  /** Record a text we just spoke (or are about to speak) into the ear. */
  push(text: string): void {
    const atMs = this.now();
    this.history.push({ text: normalize(text), atMs });
    this.prune(atMs);
  }

  /**
   * Does `text` substantially overlap anything spoken within the last
   * `windowMs`? Mirrors the original single-slot heuristic (≥60% of the
   * heard text's words appear in the spoken text) but checks it against
   * every still-fresh entry, not just the latest.
   */
  isEcho(text: string): boolean {
    const t = normalize(text);
    if (t.length < 4) return false;
    const words = t.split(/\s+/).filter((w) => w.length > 2);
    if (words.length === 0) return false;

    const nowMs = this.now();
    this.prune(nowMs);
    for (const entry of this.history) {
      const hits = words.filter((w) => entry.text.includes(w)).length;
      if (hits / words.length >= OVERLAP_THRESHOLD) return true;
    }
    return false;
  }

  private prune(nowMs: number): void {
    this.history = this.history.filter((e) => nowMs - e.atMs < this.windowMs);
  }
}

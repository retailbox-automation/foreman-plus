/** Voice-command matching for the Foreman glasses intake. Pure, testable. */

export type Command = "photo" | "submit" | "reset" | "stream_on" | "stream_off" | null;

const PHOTO_RE =
  /(сфоткай|сфотографируй|сделай (ещё )?фото|ещё фото|(take|make|snap|shoot|grab) (a |another |a new |one more )?(photo|picture|pic|shot)|another (photo|picture|shot)|new (photo|picture)|capture (it|this|that))/i;
const SUBMIT_RE =
  /(отправляй|отправить заявку|заявку в работу|send it( in| off)?|submit( the)?( job| request)?|file it)/i;
const RESET_RE =
  /(новая заявка|начни заново|сбрось заявку|new job|start over|scrap (it|that))/i;
const STREAM_ON_RE =
  /(start (live view|video|stream|streaming)|turn on (live view|video)|начни (стрим|видео)|включи (видео|стрим)|live view on)/i;
const STREAM_OFF_RE =
  /(stop (live view|video|stream|streaming)|turn off (live view|video)|выключи (видео|стрим)|останови (стрим|видео)|live view off)/i;

// Wake/sleep for the attention gate. The glasses mic hears EVERYTHING in the
// room (live 25.08: it transcribed and answered Mikhail's unrelated meeting),
// so the assistant must be opt-in per conversation, not always-on.
// Wake is deliberately EXPENSIVE: an address ("hey mentra" / "Foreman, ...").
// Bare "ассистент"/"assistant" was removed the same evening — the word came up
// in Mikhail's unrelated Russian meeting and woke the gate mid-call.
// NB: JS \b is ASCII-only and never matches Cyrillic (old glasses project
// gotcha) — boundaries are spelled out by hand.
const WAKE_NAMES = "(?:foreman|форман|mentra|ментра)";
const NB = "[^а-яёa-z0-9]"; // non-word boundary that also works for Cyrillic
const WAKE_RE = new RegExp(
  `(?:^|${NB})(?:hey|привет|эй|окей|ok)[ ,]+${WAKE_NAMES}(?:${NB}|$)` +
  `|^${NB}*${WAKE_NAMES}(?:${NB}|$)`, "i");
const SLEEP_RE = /\b(be quiet|quiet|mute|go to sleep|stop listening|тихо|замолчи|хватит|усни)\b/i;

export function matchesWake(text: string): boolean { return WAKE_RE.test(text); }
export function matchesSleep(text: string): boolean { return SLEEP_RE.test(text); }

export function matchCommand(text: string): Command {
  if (SUBMIT_RE.test(text)) return "submit";
  if (PHOTO_RE.test(text)) return "photo";
  if (STREAM_OFF_RE.test(text)) return "stream_off";
  if (STREAM_ON_RE.test(text)) return "stream_on";
  if (RESET_RE.test(text)) return "reset";
  return null;
}

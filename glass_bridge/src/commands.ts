/** Voice-command matching for the Foreman glasses intake. Pure, testable. */

export type Command = "photo" | "submit" | "reset" | "stream_on" | "stream_off" | null;

const PHOTO_RE =
  /(сфоткай|сфотографируй|сделай фото|take a photo|take photo|snap a photo|capture (it|this|that))/i;
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
// "mentra" included: live 25.08 Mikhail's instinct was "Hey Mentra".
const WAKE_RE = /\b(hey )?(foreman|форман|ассистент|assistant|mentra|ментра)\b/i;
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

/** Voice-command matching for the Foreman glasses intake. Pure, testable. */

export type Command = "photo" | "submit" | "reset" | null;

const PHOTO_RE =
  /(сфоткай|сфотографируй|сделай фото|take a photo|take photo|snap a photo|capture (it|this|that))/i;
const SUBMIT_RE =
  /(отправляй|отправить заявку|заявку в работу|send it( in| off)?|submit( the)?( job| request)?|file it)/i;
const RESET_RE =
  /(новая заявка|начни заново|сбрось заявку|new job|start over|scrap (it|that))/i;

export function matchCommand(text: string): Command {
  if (SUBMIT_RE.test(text)) return "submit";
  if (PHOTO_RE.test(text)) return "photo";
  if (RESET_RE.test(text)) return "reset";
  return null;
}

/**
 * is-backchannel.ts — recognise short filler acknowledgements.
 *
 * Live 07-15: while the assistant was mid-reply, Mikhail's natural
 * backchannel ("угу", "супер", "так", "да") counted as a new utterance and
 * (a) triggered barge-in — cancelling the rest of the answer — and (b) got
 * forwarded to the brain as a bogus query. Result: "он не отвечает" (his own
 * filler killed the reply). Such fillers must NOT barge-in and must NOT reach
 * the brain.
 *
 * Conservative: only true when the WHOLE utterance is composed of filler
 * tokens — "Да, покажи календарь" (content after "да") stays a real request.
 */

const FILLERS = new Set([
  // ru acknowledgements / thinking noises
  "угу", "ага", "ага", "да", "дада", "так", "ок", "окей", "океюшки",
  "ясно", "понятно", "понял", "поняла", "хорошо", "ладно", "супер",
  "мгм", "мхм", "эм", "ммм", "мм", "э", "ээ", "а", "ну", "вот", "тсс",
  "угуугу", "супермегапупер",
  // en
  "yeah", "yep", "yes", "ok", "okay", "mhm", "mmm", "uh", "um", "uhhuh",
  "right", "sure", "cool", "nice",
  // Mentra en-US ASR renders these as separate tokens ("Mm-hm." → mm hm)
  "hm", "hmm", "mm", "mmhm", "mhmm", "uhm", "alright", "gotcha", "got", "it",
]);

/**
 * True if the utterance is nothing but filler acknowledgements (so it should
 * neither barge-in on a reply nor be sent to the brain).
 */
export function isBackchannel(text: string): boolean {
  const words = text
    .toLowerCase()
    .replace(/[^\p{L}\s]/gu, " ") // strip punctuation/digits, keep letters
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);

  if (words.length === 0) return false; // nothing to suppress
  return words.every((w) => FILLERS.has(w));
}

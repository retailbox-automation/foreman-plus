/** In-memory state of one field job being captured, and the /run payload.
 *  Pure data + builders — no SDK, no network. */

export interface JobState {
  jobId: string;
  photo: { data: Buffer; mimeType: string } | null;
  transcript: string[];
}

export function newJob(now: Date = new Date()): JobState {
  const stamp = now.toISOString().replace(/[-:T]/g, "").slice(2, 12);
  return { jobId: `J-G${stamp}`, photo: null, transcript: [] };
}

export function setPhoto(job: JobState, data: Buffer, mimeType = "image/jpeg"): void {
  job.photo = { data, mimeType };
}

export function addUtterance(job: JobState, text: string): void {
  const t = text.trim();
  if (t) job.transcript.push(t);
}

export function jobReady(job: JobState): { ok: boolean; missing: string[] } {
  const missing: string[] = [];
  if (!job.photo) missing.push("photo");
  if (job.transcript.length === 0) missing.push("voice notes");
  return { ok: missing.length === 0, missing };
}

/** RunAgentRequest body for the ADK api_server POST /run (buffered).
 *  Shape verified against docs/stack/adk-core.md §RunAgentRequest and the
 *  cloud leg of SPIKE-2026-08-19-multimodal-adk (inlineData base64). */
export function buildRunPayload(job: JobState, appName: string, userId: string): object {
  const parts: object[] = [
    {
      text:
        `Field intake for job ${job.jobId}, captured hands-free via camera glasses. ` +
        `The photo is what the technician is looking at. Technician's spoken notes:\n` +
        job.transcript.map((t) => `- ${t}`).join("\n") +
        `\nExtract the equipment facts and the reported issue, record them in memory ` +
        `for job ${job.jobId}, then hand off to the estimator for a scope estimate. ` +
        `End with a ONE-SENTENCE spoken summary for the technician.`,
    },
  ];
  if (job.photo) {
    parts.push({
      inlineData: {
        mimeType: job.photo.mimeType,
        data: job.photo.data.toString("base64"),
      },
    });
  }
  return {
    app_name: appName,
    user_id: userId,
    session_id: job.jobId,
    new_message: { role: "user", parts },
  };
}

/** Pull the last non-empty text part out of the /run response (list[Event]). */
export function extractReply(events: unknown): string {
  if (!Array.isArray(events)) return "";
  let last = "";
  for (const ev of events) {
    const parts = (ev as { content?: { parts?: { text?: string }[] } })?.content?.parts;
    if (!parts) continue;
    for (const p of parts) {
      if (typeof p.text === "string" && p.text.trim()) last = p.text.trim();
    }
  }
  return last;
}

/** Trim a fleet reply down to something speakable (~2 sentences, no markdown). */
export function speakable(reply: string, maxLen = 320): string {
  const plain = reply
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[*_#`>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (plain.length <= maxLen) return plain;
  const cut = plain.slice(0, maxLen);
  const stop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
  return stop > 40 ? cut.slice(0, stop + 1) : cut;
}

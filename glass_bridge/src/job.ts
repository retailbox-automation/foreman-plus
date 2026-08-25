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

type Part = {
  text?: string;
  functionCall?: { name?: string; args?: Record<string, unknown> };
  functionResponse?: { name?: string; response?: Record<string, unknown> };
};

interface FleetOutcome {
  facts: { predicate: string; value: string }[];
  approved: number;
  rejected: { predicate: string; reason: string }[];
  estimate: { hours?: number; parts?: string[] } | null;
}

const SPOKEN_PREDICATES = ["equipment_brand", "equipment_model", "manufacture_date", "issue"];

/** Walk the /run event list and pull out what a technician wants to hear:
 *  which facts the gate approved/rejected and the estimator's numbers.
 *  Order of calls/responses is preserved by ADK, so verdict i belongs to
 *  record_fact call i within one author. */
export function summarizeEvents(events: unknown): FleetOutcome {
  const out: FleetOutcome = { facts: [], approved: 0, rejected: [], estimate: null };
  if (!Array.isArray(events)) return out;
  const pendingCalls: { predicate: string; value: string }[] = [];
  for (const ev of events) {
    const parts = (ev as { content?: { parts?: Part[] } })?.content?.parts ?? [];
    for (const p of parts) {
      const fc = p.functionCall;
      if (fc?.name === "record_fact") {
        const predicate = String(fc.args?.predicate ?? "");
        const value = String(fc.args?.value ?? "");
        pendingCalls.push({ predicate, value });
        if (predicate === "estimate") out.estimate = parseEstimate(value) ?? out.estimate;
        continue;
      }
      const fr = p.functionResponse;
      if (fr?.name === "record_fact") {
        const call = pendingCalls.shift();
        const verdict = String(fr.response?.verdict ?? "");
        if (verdict === "approved") {
          out.approved += 1;
          if (call && SPOKEN_PREDICATES.includes(call.predicate)) out.facts.push(call);
        } else if (call) {
          out.rejected.push({ predicate: call.predicate, reason: String(fr.response?.reason ?? "") });
        }
        continue;
      }
      if (p.text && out.estimate === null) {
        const m = p.text.match(/\{[\s\S]*?"hours"[\s\S]*?\}/);
        if (m) out.estimate = parseEstimate(m[0]);
      }
    }
  }
  return out;
}

function parseEstimate(raw: string): FleetOutcome["estimate"] {
  try {
    const j = JSON.parse(raw) as { hours?: unknown; parts?: unknown };
    const hours = typeof j.hours === "number" ? j.hours : undefined;
    const parts = Array.isArray(j.parts) ? j.parts.map(String) : undefined;
    return hours === undefined && parts === undefined ? null : { hours, parts };
  } catch {
    return null;
  }
}

function joinNatural(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** Deterministic spoken summary: never reads JSON aloud, always mentions the
 *  gate verdicts (the product's differentiator), falls back to fleet prose. */
export function renderSpoken(events: unknown): string {
  const o = summarizeEvents(events);
  const bits: string[] = [];
  const model = o.facts.find((f) => f.predicate === "equipment_model")?.value;
  const brand = o.facts.find((f) => f.predicate === "equipment_brand")?.value;
  const made = o.facts.find((f) => f.predicate === "manufacture_date")?.value;
  const unit = [brand && !model?.toLowerCase().includes(brand.toLowerCase()) ? brand : "", model]
    .filter(Boolean).join(" ");
  if (unit) bits.push(`Logged ${unit}${made ? `, made ${made}` : ""}.`);
  if (o.approved > 0 || o.rejected.length > 0) {
    let gate = `Gate approved ${o.approved} fact${o.approved === 1 ? "" : "s"}`;
    if (o.rejected.length > 0) {
      gate += `, rejected ${o.rejected.length}: ${o.rejected[0].predicate} — ${speakable(o.rejected[0].reason, 90)}`;
    }
    bits.push(gate + ".");
  }
  if (o.estimate) {
    const h = o.estimate.hours;
    const est = [
      h !== undefined ? `${h} hour${h === 1 ? "" : "s"}` : "",
      o.estimate.parts?.length ? `parts: ${joinNatural(o.estimate.parts)}` : "",
    ].filter(Boolean).join(", ");
    if (est) bits.push(`Estimate: ${est}.`);
  }
  if (bits.length > 0) return bits.join(" ");
  return speakable(extractReply(events).replace(/\{[\s\S]*\}/g, " "));
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

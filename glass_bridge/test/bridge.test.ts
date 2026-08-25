import { describe, expect, test } from "bun:test";
import { matchCommand } from "../src/commands.js";
import {
  addUtterance, buildRunPayload, extractReply, jobReady, newJob, renderSpoken, setPhoto,
  speakable, summarizeEvents,
} from "../src/job.js";

// Shape captured from a live /run on 2026-08-25 (foreman → gate → estimator).
const LIVE_EVENTS = [
  { author: "foreman", content: { parts: [
    { functionCall: { name: "record_fact", args: { subject: "job:J-1", predicate: "equipment_model", value: "Rheem 82V40-2" } } },
    { functionCall: { name: "record_fact", args: { subject: "job:J-1", predicate: "manufacture_date", value: "05/2004" } } },
    { functionCall: { name: "record_fact", args: { subject: "job:J-1", predicate: "issue", value: "No hot water" } } },
  ] } },
  { author: "foreman", content: { parts: [
    { functionResponse: { name: "record_fact", response: { verdict: "approved", reason: "ok" } } },
    { functionResponse: { name: "record_fact", response: { verdict: "approved", reason: "ok" } } },
    { functionResponse: { name: "record_fact", response: { verdict: "rejected", reason: "Conflicts with existing fact: issue already recorded as intermittent." } } },
  ] } },
  { author: "foreman", content: { parts: [{ functionCall: { name: "transfer_to_agent", args: { agent_name: "estimator" } } }] } },
  { author: "estimator", content: { parts: [
    { functionCall: { name: "record_fact", args: { subject: "job:J-1", predicate: "estimate", value: "{\"job\": \"J-1\", \"hours\": 2, \"parts\": [\"lower heating element\", \"thermostat\"]}" } } },
  ] } },
  { author: "estimator", content: { parts: [{ functionResponse: { name: "record_fact", response: { verdict: "approved" } } }] } },
  { author: "estimator", content: { parts: [{ text: "```json\n{\"job\": \"J-1\", \"hours\": 2, \"parts\": [\"lower heating element\", \"thermostat\"]}\n```\nThe repair is estimated at two hours." }] } },
];

describe("fleet outcome → spoken", () => {
  test("summarizeEvents pairs verdicts with calls and parses the estimate", () => {
    const o = summarizeEvents(LIVE_EVENTS);
    expect(o.approved).toBe(3);
    expect(o.rejected).toEqual([{ predicate: "issue", reason: "Conflicts with existing fact: issue already recorded as intermittent." }]);
    expect(o.facts.map((f) => f.predicate)).toEqual(["equipment_model", "manufacture_date"]);
    expect(o.estimate).toEqual({ hours: 2, parts: ["lower heating element", "thermostat"] });
  });

  test("renderSpoken never reads JSON, mentions the gate and the estimate", () => {
    const s = renderSpoken(LIVE_EVENTS);
    expect(s).not.toContain("{");
    expect(s).toContain("Logged Rheem 82V40-2, made 05/2004.");
    expect(s).toContain("Gate approved 3 facts, rejected 1: issue");
    expect(s).toContain("Estimate: 2 hours, parts: lower heating element and thermostat.");
  });

  test("renderSpoken reads an estimate out of bare text JSON", () => {
    const s = renderSpoken([{ content: { parts: [{ text: "{\"hours\": 1}\nOne hour, no parts needed." }] } }]);
    expect(s).toBe("Estimate: 1 hour.");
  });

  test("renderSpoken falls back to prose when there are no tool events or JSON", () => {
    const s = renderSpoken([{ content: { parts: [{ text: "**Done.** Nothing to record for this one." }] } }]);
    expect(s).toBe("Done. Nothing to record for this one.");
    expect(renderSpoken([])).toBe("");
  });
});

describe("commands", () => {
  test("submit beats photo when both could match", () => {
    expect(matchCommand("ok send it in")).toBe("submit");
    expect(matchCommand("отправляй заявку")).toBe("submit");
  });
  test("photo commands ru/en", () => {
    expect(matchCommand("сфоткай это")).toBe("photo");
    expect(matchCommand("take a photo of the plate")).toBe("photo");
    expect(matchCommand("capture this")).toBe("photo");
    // live 25.08: Mikhail's actual phrasing was missed and the brain lied
    expect(matchCommand("Make another photo.")).toBe("photo");
    expect(matchCommand("take one more picture")).toBe("photo");
    expect(matchCommand("сделай ещё фото")).toBe("photo");
    expect(matchCommand("grab a shot of this")).toBe("photo");
  });
  test("reset and no-command", () => {
    expect(matchCommand("start over please")).toBe("reset");
    expect(matchCommand("the compressor is rattling")).toBe(null);
  });
});

describe("job state", () => {
  test("readiness names what's missing", () => {
    const job = newJob();
    expect(jobReady(job)).toEqual({ ok: false, missing: ["photo", "voice notes"] });
    setPhoto(job, Buffer.from("jpg"));
    expect(jobReady(job).missing).toEqual(["voice notes"]);
    addUtterance(job, "  water heater leaking  ");
    expect(jobReady(job).ok).toBe(true);
    expect(job.transcript).toEqual(["water heater leaking"]);
  });

  test("run payload carries text + inlineData and session ids", () => {
    const job = newJob(new Date("2026-08-25T15:00:00Z"));
    setPhoto(job, Buffer.from("jpegbytes"), "image/jpeg");
    addUtterance(job, "unit is from 2004");
    const p = buildRunPayload(job, "foreman_app", "glass-tech") as {
      app_name: string; session_id: string;
      new_message: { parts: { text?: string; inlineData?: { data: string } }[] };
    };
    expect(p.app_name).toBe("foreman_app");
    expect(p.session_id).toBe(job.jobId);
    expect(p.new_message.parts[0].text).toContain("unit is from 2004");
    expect(p.new_message.parts[1].inlineData!.data)
      .toBe(Buffer.from("jpegbytes").toString("base64"));
  });
});

describe("reply extraction", () => {
  test("takes the LAST non-empty text across events", () => {
    const events = [
      { content: { parts: [{ text: "thinking..." }] } },
      { content: { parts: [{ functionCall: { name: "record_fact" } }] } },
      { content: { parts: [{ text: "Scope: replace anode rod, ~$450." }] } },
    ];
    expect(extractReply(events)).toBe("Scope: replace anode rod, ~$450.");
    expect(extractReply([])).toBe("");
    expect(extractReply({ not: "a list" })).toBe("");
  });

  test("speakable strips markdown and cuts at a sentence", () => {
    const first = "**Bold** opening sentence that is comfortably past forty characters long. ";
    const s = speakable(first + "word ".repeat(80) + ". Tail here.", 120);
    expect(s).not.toContain("*");
    expect(s.length).toBeLessThanOrEqual(120);
    expect(s.endsWith(".")).toBe(true);
    // no sentence boundary before the cut → hard cut, still bounded
    const hard = speakable("x".repeat(500), 120);
    expect(hard.length).toBe(120);
  });
});

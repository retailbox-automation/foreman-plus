import { describe, expect, test } from "bun:test";
import { matchCommand } from "../src/commands.js";
import {
  addUtterance, buildRunPayload, extractReply, jobReady, newJob, setPhoto, speakable,
} from "../src/job.js";

describe("commands", () => {
  test("submit beats photo when both could match", () => {
    expect(matchCommand("ok send it in")).toBe("submit");
    expect(matchCommand("отправляй заявку")).toBe("submit");
  });
  test("photo commands ru/en", () => {
    expect(matchCommand("сфоткай это")).toBe("photo");
    expect(matchCommand("take a photo of the plate")).toBe("photo");
    expect(matchCommand("capture this")).toBe("photo");
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

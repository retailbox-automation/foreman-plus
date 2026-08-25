import { describe, expect, test } from "bun:test";
import { GlassIntakeCore, type BrainClient, type FleetClient, type GlassSession } from "../src/core.js";

const FLEET_EVENTS = [
  { author: "foreman", content: { parts: [
    { functionCall: { name: "record_fact", args: { predicate: "equipment_model", value: "Rheem 82V40-2" } } },
  ] } },
  { author: "foreman", content: { parts: [{ functionResponse: { name: "record_fact", response: { verdict: "approved" } } }] } },
  { author: "estimator", content: { parts: [{ text: "{\"hours\": 2, \"parts\": [\"thermostat\"]}" }] } },
];

class FakeSession implements GlassSession {
  spoken: string[] = [];
  requestPhotoImpl: () => Promise<{ buffer: Buffer; mimeType: string; size: number }> =
    async () => ({ buffer: Buffer.from("req-jpeg"), mimeType: "image/jpeg", size: 8 });
  audio = { speak: async (t: string) => { this.spoken.push(t); } };
  camera = { requestPhoto: async () => this.requestPhotoImpl() };
}

class FakeFleet implements FleetClient {
  sessions: string[] = [];
  payloads: object[] = [];
  fail = false;
  async ensureSession(id: string) { this.sessions.push(id); }
  async run(payload: object) {
    this.payloads.push(payload);
    if (this.fail) throw new Error("boom");
    return FLEET_EVENTS;
  }
}

class FakeBrain implements BrainClient {
  frames: Buffer[] = [];
  asked: string[] = [];
  async pushFrame(b: Buffer) { this.frames.push(b); }
  async ask(t: string) { this.asked.push(t); return `re: ${t}`; }
}

function rig(opts: { brain?: FakeBrain; fleet?: FakeFleet } = {}) {
  const fleet = opts.fleet ?? new FakeFleet();
  const core = new GlassIntakeCore({
    appName: "foreman_app", userId: "glass-tech", foreman: fleet,
    brain: opts.brain ?? null, reassureAfterMs: [], log: () => {},
  });
  return { core, fleet, session: new FakeSession() };
}

const jpeg = () => new Uint8Array([0xff, 0xd8, 1, 2, 3]).buffer as ArrayBuffer;

describe("happy path: button photo → notes → send it", () => {
  test("submits photo + notes and speaks the rendered fleet outcome", async () => {
    const { core, fleet, session } = rig();
    await core.onPhotoBroadcast(session, jpeg());
    expect(session.spoken).toEqual(["Photo captured."]);
    expect(await core.onUtterance(session, "no hot water since yesterday")).toBe("note");
    expect(await core.onUtterance(session, "ok send it")).toBe("submit");
    expect(fleet.sessions.length).toBe(1);
    const p = fleet.payloads[0] as { new_message: { parts: { inlineData?: object; text?: string }[] } };
    expect(p.new_message.parts[0].text).toContain("no hot water since yesterday");
    expect(p.new_message.parts[1].inlineData).toBeDefined();
    expect(session.spoken.at(-1)).toBe("Logged Rheem 82V40-2. Gate approved 1 fact. Estimate: 2 hours, parts: thermostat.");
    // job rolled over after a successful submit
    expect(core.job.photo).toBeNull();
    expect(core.job.transcript).toEqual([]);
  });
});

describe("guards", () => {
  test("send it without a photo names what's missing and does not call the fleet", async () => {
    const { core, fleet, session } = rig();
    await core.onUtterance(session, "the fan is loud");
    await core.onUtterance(session, "send it");
    expect(fleet.payloads.length).toBe(0);
    expect(session.spoken.at(-1)).toBe("Not yet — I still need: photo.");
  });

  test("our own speech echoed back by the mic is ignored", async () => {
    const { core, session } = rig();
    await core.onPhotoBroadcast(session, jpeg());
    expect(await core.onUtterance(session, "Photo captured.")).toBe("echo");
    expect(core.job.transcript).toEqual([]);
  });

  test("duplicate photo_taken within 10s is dropped; empty payload ignored", async () => {
    const { core, session } = rig();
    await core.onPhotoBroadcast(session, jpeg());
    await core.onPhotoBroadcast(session, new Uint8Array([9, 9]).buffer as ArrayBuffer);
    await core.onPhotoBroadcast(session, undefined);
    expect(session.spoken).toEqual(["Photo captured."]);
    expect(core.job.photo!.data.length).toBe(5);
  });

  test("fleet failure keeps the capture and tells the tech to retry", async () => {
    const fleet = new FakeFleet();
    fleet.fail = true;
    const { core, session } = rig({ fleet });
    await core.onPhotoBroadcast(session, jpeg());
    await core.onUtterance(session, "compressor rattles");
    await core.onUtterance(session, "send it");
    expect(session.spoken.at(-1)).toBe("Sending failed. Your capture is safe — say send it to retry.");
    expect(core.job.photo).not.toBeNull();
    expect(core.job.transcript).toEqual(["compressor rattles"]);
  });

  test("start over resets the job", async () => {
    const { core, session } = rig();
    await core.onPhotoBroadcast(session, jpeg());
    expect(await core.onUtterance(session, "start over")).toBe("reset");
    expect(core.job.photo).toBeNull();
  });
});

describe("voice-command photo (requestPhoto ladder)", () => {
  test("falls down the size ladder, then gives up with a spoken hint", async () => {
    const { core, session } = rig();
    let calls = 0;
    session.requestPhotoImpl = async () => { calls += 1; throw new Error("timeout"); };
    expect(await core.onUtterance(session, "take a photo")).toBe("photo");
    expect(calls).toBeGreaterThan(1);
    expect(session.spoken.at(-1)).toBe("Photo did not come through. Try the camera button.");
  });

  test("success on first try stores the photo", async () => {
    const { core, session } = rig();
    await core.onUtterance(session, "сфоткай");
    expect(core.job.photo!.data.toString()).toBe("req-jpeg");
    expect(session.spoken).toEqual(["Photo captured."]);
  });
});

describe("photo-mode brain", () => {
  test("photo is pushed as the brain's frame; questions are answered aloud", async () => {
    const brain = new FakeBrain();
    const { core, session } = rig({ brain });
    await core.onPhotoBroadcast(session, jpeg());
    await Bun.sleep(0);
    expect(brain.frames.length).toBe(1);
    await core.onUtterance(session, "what am I looking at?");
    expect(brain.asked).toEqual(["what am I looking at?"]);
    expect(session.spoken.at(-1)).toBe("re: what am I looking at?");
    // the question is still kept as a voice note for the intake
    expect(core.job.transcript).toEqual(["what am I looking at?"]);
  });
});

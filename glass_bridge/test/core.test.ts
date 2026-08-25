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
  camera: GlassSession["camera"] = { requestPhoto: async () => this.requestPhotoImpl() };
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

function rig(opts: { brain?: FakeBrain; fleet?: FakeFleet; awake?: boolean; awakeIdleMs?: number } = {}) {
  const fleet = opts.fleet ?? new FakeFleet();
  const core = new GlassIntakeCore({
    appName: "foreman_app", userId: "glass-tech", foreman: fleet,
    brain: opts.brain ?? null, reassureAfterMs: [], log: () => {},
    awakeIdleMs: opts.awakeIdleMs,
  });
  core.awake = opts.awake ?? true; // most scenarios assume an engaged tech
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

describe("camera button → requestPhoto (photo_taken broadcast is dead on this firmware)", () => {
  test("short press captures via requestPhoto; long press ignored; double-click debounced", async () => {
    const { core, session } = rig();
    let calls = 0;
    session.requestPhotoImpl = async () => { calls += 1; return { buffer: Buffer.from("btn-jpeg"), mimeType: "image/jpeg", size: 8 }; };
    await core.onButtonPress(session, "camera", "long");
    expect(calls).toBe(0);
    await core.onButtonPress(session, "camera", "short");
    await core.onButtonPress(session, "camera", "short"); // second click within 3s
    expect(calls).toBe(1);
    expect(core.job.photo!.data.toString()).toBe("btn-jpeg");
  });
});

describe("fillers", () => {
  test("backchannel is neither a note nor a brain question", async () => {
    const brain = new FakeBrain();
    const { core, session } = rig({ brain });
    expect(await core.onUtterance(session, "Mm-hm.")).toBe("filler");
    expect(await core.onUtterance(session, "Okay, sounds good.")).toBe("note"); // has content → stays
    expect(core.job.transcript).toEqual(["Okay, sounds good."]);
    expect(brain.asked).toEqual(["Okay, sounds good."]);
  });
});

describe("attention gate (the meeting-in-the-room incident, 25.08)", () => {
  test("asleep: ambient speech is neither noted nor answered, commands still work", async () => {
    const brain = new FakeBrain();
    const { core, session } = rig({ brain, awake: false });
    expect(await core.onUtterance(session, "waiting for a van and Jesse maybe")).toBe("asleep");
    expect(core.job.transcript).toEqual([]);
    expect(brain.asked).toEqual([]);
    await core.onUtterance(session, "take a photo");
    expect(core.job.photo).not.toBeNull(); // explicit command pierces the gate
  });

  test("wake word wakes and speaks; sleep word sleeps", async () => {
    const { core, session } = rig({ awake: false });
    expect(await core.onUtterance(session, "hey foreman")).toBe("woke");
    expect(session.spoken).toEqual(["Listening."]);
    expect(core.awake).toBe(true);
    expect(await core.onUtterance(session, "be quiet now")).toBe("slept");
    expect(core.awake).toBe(false);
  });

  test("wake word carrying a command executes the command immediately", async () => {
    const { core, session } = rig({ awake: false });
    await core.onUtterance(session, "foreman, take a photo");
    expect(core.job.photo).not.toBeNull();
    expect(core.awake).toBe(true);
  });

  test("auto-sleep after idle window", async () => {
    const { core, session } = rig({ awakeIdleMs: 1 });
    await core.onUtterance(session, "first note");
    await Bun.sleep(5);
    expect(await core.onUtterance(session, "ambient chatter later")).toBe("asleep");
  });
});

describe("live view (managed stream)", () => {
  test("start waits for a real #EXTM3U manifest, then hooks the brain", async () => {
    const brain = new FakeBrain();
    const streams: string[] = [];
    (brain as FakeBrain & { startStream(u: string): Promise<void> }).startStream =
      async (u: string) => { streams.push(u); };
    const { core, session } = rig({ brain });
    session.camera.startManagedStream = async () => ({ hlsUrl: "https://cf/x/manifest.m3u8" });
    session.camera.stopManagedStream = async () => {};
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response("#EXTM3U\n#EXT-X-VERSION:3")) as unknown as typeof fetch;
    try {
      expect(await core.startLiveView(session)).toBe(true);
    } finally { globalThis.fetch = realFetch; }
    expect(streams).toEqual(["https://cf/x/manifest.m3u8"]);
    expect(session.spoken.at(-1)).toBe("Live view is on. I can see what you see now.");
    await core.stopLiveView(session);
    expect(core.streamInfo).toBeNull();
  });

  test("start on a connection without managed streaming says so", async () => {
    const { core, session } = rig();
    expect(await core.startLiveView(session)).toBe(false);
    expect(session.spoken.at(-1)).toBe("Live view is not supported on this connection.");
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

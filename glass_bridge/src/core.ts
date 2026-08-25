/** Glasses-intake logic with the MentraOS SDK abstracted away, so the exact
 *  event → job → submit → speak wiring is unit-testable with a fake session.
 *  index.ts only maps SDK events onto these methods. */
import { EchoGuard } from "./echo-guard.js";
import { isBackchannel } from "./is-backchannel.js";
import { matchCommand, matchesSleep, matchesWake } from "./commands.js";
import { photoSizeLadder, type PhotoSize } from "./photo-size.js";
import {
  addUtterance, buildRunPayload, jobReady, newJob, renderSpoken, setPhoto, type JobState,
} from "./job.js";

/** The slice of AppSession the core touches (structural, for tests). */
export interface GlassSession {
  audio: { speak: (text: string, opts?: Record<string, unknown>) => Promise<unknown> };
  camera: {
    requestPhoto: (opts?: { size?: PhotoSize; compress?: "none" | "medium" | "heavy" }) => Promise<{ buffer: Buffer; mimeType: string; size: number }>;
    startManagedStream?: (opts?: { quality?: "720p" | "1080p" }) => Promise<{ hlsUrl: string; dashUrl?: string; previewUrl?: string }>;
    stopManagedStream?: () => Promise<unknown>;
  };
}

export interface FleetClient {
  ensureSession(sessionId: string): Promise<void>;
  run(payload: object): Promise<unknown>;
}

export interface BrainClient {
  pushFrame(jpeg: Buffer): Promise<void>;
  ask(text: string): Promise<string>;
  reset?(): Promise<void>;
  startStream?(hlsUrl: string): Promise<void>;
  stopStream?(): Promise<void>;
}

export interface CoreOptions {
  appName: string;
  userId: string;
  foreman: FleetClient;
  brain?: BrainClient | null;
  photoSize?: PhotoSize;
  /** Reassurance timers while the fleet runs (ms). Tests pass []. */
  reassureAfterMs?: number[];
  /** Auto-sleep after this much silence while awake (default 3 min). */
  awakeIdleMs?: number;
  log?: (msg: string) => void;
}

export class GlassIntakeCore {
  job: JobState = newJob();
  /** Survives job rollover — /debug/photo.jpg and the brain's eyes. */
  lastPhoto: { data: Buffer; mimeType: string; at: number } | null = null;
  streamInfo: { hlsUrl: string; previewUrl?: string; startedAt: string } | null = null;
  private lastPhotoAt = 0;
  private submitting = false;
  private startingStream = false;
  /** Attention gate: asleep by default — the room is full of speech that is
   *  not for us. Explicit commands and the camera button always work. */
  awake = false;
  private lastAwakeActivity = Date.now(); // NOT 0: a 0 epoch trips auto-sleep on the first utterance
  private readonly awakeIdleMs: number;
  private readonly echoGuard = new EchoGuard();
  private readonly log: (msg: string) => void;

  constructor(private readonly o: CoreOptions) {
    this.log = o.log ?? ((m) => console.log(m));
    this.awakeIdleMs = o.awakeIdleMs ?? 180_000;
  }

  /** photo_taken broadcast (system camera button = ONE shutter). */
  async onPhotoBroadcast(session: GlassSession, data: ArrayBuffer | undefined, mime = "image/jpeg"): Promise<void> {
    if (!data || data.byteLength === 0) return;
    if (Date.now() - this.lastPhotoAt <= 10_000) return; // dedupe vs requestPhoto
    this.lastPhotoAt = Date.now();
    setPhoto(this.job, Buffer.from(data), mime);
    this.lastPhoto = { data: Buffer.from(data), mimeType: mime, at: Date.now() };
    this.log(`[photo] captured via photo_taken broadcast (${data.byteLength} bytes)`);
    await this.speak(session, "Photo captured.");
    this.shareFrameWithBrain();
  }

  /** Camera button. Live 25.08.2026: the system photo's `photo_taken`
   *  broadcast does NOT reach the app on this firmware (matches the old
   *  project's BACKLOG N12b), so the button must drive requestPhoto itself.
   *  The system camera still fires — two shutters — but that is the
   *  platform's Cloud SDK limitation, not a choice. */
  async onButtonPress(session: GlassSession, buttonId: string, pressType: string): Promise<void> {
    this.log(`[button] ${buttonId} ${pressType}`);
    if (pressType !== "short") return; // long = system (video / power)
    if (Date.now() - this.lastPhotoAt <= 3_000) return; // debounce double-clicks
    await this.capturePhoto(session);
  }

  /** Final transcript. Returns what it did (for tests/logs). */
  async onUtterance(
    session: GlassSession, text: string,
  ): Promise<"echo" | "photo" | "submit" | "reset" | "note" | "filler" | "asleep" | "woke" | "slept"> {
    const t = text.trim();
    if (!t) return "echo";
    if (this.echoGuard.isEcho(t)) return "echo";
    this.log(`[voice] ${t}`);
    // "Mm-hm" / "okay" are not questions: keep them out of the notes and
    // never wake the brain on them (live 25.08: every filler got a reply,
    // and TTS is serial → answers queued up as "it lags / doesn't answer").
    if (isBackchannel(t)) return "filler";

    // Attention gate. The mic hears the whole room; while asleep we neither
    // take notes nor answer — but explicit commands still work.
    if (this.awake && Date.now() - this.lastAwakeActivity > this.awakeIdleMs) {
      this.awake = false;
      this.log("[gate] auto-sleep after idle");
    }
    if (matchesSleep(t)) {
      if (this.awake) { this.awake = false; await this.speak(session, "Going quiet."); }
      return "slept";
    }
    const cmd = matchCommand(t);
    if (!this.awake && matchesWake(t)) {
      this.awake = true;
      this.lastAwakeActivity = Date.now();
      // A wake that carries a real command falls through to it below.
      if (cmd === null) { await this.speak(session, "Listening."); return "woke"; }
    }

    if (cmd === "photo") { await this.capturePhoto(session); return "photo"; }
    if (cmd === "submit") { await this.submit(session); return "submit"; }
    if (cmd === "stream_on") { void this.startLiveView(session); return "note"; }
    if (cmd === "stream_off") { void this.stopLiveView(session); return "note"; }
    if (cmd === "reset") {
      this.job = newJob();
      if (this.o.brain?.reset) void this.o.brain.reset().catch(() => {});
      await this.speak(session, "Fresh job started.");
      return "reset";
    }
    if (!this.awake) return "asleep";
    this.lastAwakeActivity = Date.now();
    addUtterance(this.job, t);
    if (this.o.brain) await this.forwardToBrain(session, t);
    return "note";
  }

  private photoInFlight: Promise<boolean> | null = null;

  /** Explicit voice-command photo — requestPhoto with the size ladder. */
  async capturePhoto(session: GlassSession): Promise<boolean> {
    const run = this.capturePhotoInner(session);
    this.photoInFlight = run;
    try {
      return await run;
    } finally {
      if (this.photoInFlight === run) this.photoInFlight = null;
    }
  }

  private async capturePhotoInner(session: GlassSession): Promise<boolean> {
    const attempts = photoSizeLadder(this.o.photoSize);
    for (let i = 0; i < attempts.length; i++) {
      const want = attempts[i];
      try {
        // compress:'medium' (SDK option, found in 2.1.29 d.ts) shrinks the
        // transfer — live 25.08 the UNcompressed default timed out over BT
        // and we fell to 640x480; compression keeps resolution instead.
        const photo = await session.camera.requestPhoto(
          want ? { size: want, compress: "medium" } : { compress: "medium" });
        setPhoto(this.job, photo.buffer, photo.mimeType);
        this.lastPhoto = { data: photo.buffer, mimeType: photo.mimeType, at: Date.now() };
        this.lastPhotoAt = Date.now();
        this.log(`[photo] requestPhoto ok (${photo.size} bytes, size=${want ?? "default"})`);
        await this.speak(session, "Photo captured.");
        this.shareFrameWithBrain();
        return true;
      } catch (err) {
        this.log(`[photo] attempt ${i} (${want ?? "default"}) failed: ${String(err)}`);
      }
    }
    await this.speak(session, "Photo did not come through. Try the camera button.");
    return false;
  }

  async submit(session: GlassSession): Promise<void> {
    if (this.submitting) { await this.speak(session, "Already sending."); return; }
    const ready = jobReady(this.job);
    if (!ready.ok) {
      await this.speak(session, `Not yet — I still need: ${ready.missing.join(" and ")}.`);
      return;
    }
    this.submitting = true;
    const job = this.job;
    // The fleet takes 25-60s (measured live 25.08); silence that long reads
    // as "it died" in the ear — reassure on a timer until the run returns.
    const reassure = (this.o.reassureAfterMs ?? [20_000, 45_000]).map((ms) =>
      setTimeout(() => { void this.speak(session, "Still working — the estimator is on it."); }, ms));
    try {
      await this.speak(session, "Sending to the fleet.");
      await this.o.foreman.ensureSession(job.jobId);
      const t0 = Date.now();
      const events = await this.o.foreman.run(buildRunPayload(job, this.o.appName, this.o.userId));
      reassure.forEach(clearTimeout);
      const reply = renderSpoken(events);
      this.log(`[submit] ${job.jobId} done in ${Math.round((Date.now() - t0) / 1000)}s → ${reply}`);
      await this.speak(session, reply || "The fleet has it. Scope is on the dashboard.");
      this.job = newJob(); // next capture starts clean
    } catch (err) {
      reassure.forEach(clearTimeout);
      this.log(`[submit] failed: ${String(err)}`);
      await this.speak(session, "Sending failed. Your capture is safe — say send it to retry.");
    } finally {
      this.submitting = false;
    }
  }

  /** Managed stream (Mentra Cloud → Cloudflare HLS). "Live" from the SDK is
   *  claimed before media actually flows (docs/2026-07-13-stream-404-research
   *  in the glasses project), so the ONLY readiness signal we trust is the
   *  HLS manifest itself answering with #EXTM3U. */
  async startLiveView(session: GlassSession): Promise<boolean> {
    if (!session.camera.startManagedStream) {
      await this.speak(session, "Live view is not supported on this connection.");
      return false;
    }
    if (this.streamInfo || this.startingStream) {
      await this.speak(session, "Live view is already running.");
      return false;
    }
    this.startingStream = true;
    try {
      await this.speak(session, "Starting live view.");
      const urls = await session.camera.startManagedStream({ quality: "720p" });
      this.log(`[stream] managed started, HLS: ${urls.hlsUrl}`);
      const ready = await this.waitForManifest(urls.hlsUrl, 90_000);
      if (!ready) {
        this.log("[stream] HLS manifest never came up (the July NAT gotcha)");
        await session.camera.stopManagedStream?.().catch(() => {});
        await this.speak(session, "Live view did not come up. Photo mode still works.");
        return false;
      }
      this.streamInfo = { hlsUrl: urls.hlsUrl, previewUrl: urls.previewUrl, startedAt: new Date().toISOString() };
      if (this.o.brain?.startStream) {
        await this.o.brain.startStream(urls.hlsUrl).catch((e) => this.log(`[stream] brain hookup failed: ${e}`));
      }
      await this.speak(session, "Live view is on. I can see what you see now.");
      return true;
    } catch (err) {
      this.log(`[stream] start failed: ${String(err)}`);
      await this.speak(session, "Live view failed to start.");
      return false;
    } finally {
      this.startingStream = false;
    }
  }

  async stopLiveView(session: GlassSession): Promise<void> {
    try { await session.camera.stopManagedStream?.(); } catch { /* already down */ }
    if (this.o.brain?.stopStream) await this.o.brain.stopStream().catch(() => {});
    const was = this.streamInfo !== null;
    this.streamInfo = null;
    if (was) await this.speak(session, "Live view is off.");
  }

  private async waitForManifest(url: string, budgetMs: number): Promise<boolean> {
    const deadline = Date.now() + budgetMs;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(url, { signal: AbortSignal.timeout(5_000) });
        if (res.ok && (await res.text()).includes("#EXTM3U")) return true;
      } catch { /* not up yet */ }
      await new Promise((r) => setTimeout(r, 2_000));
    }
    return false;
  }

  private shareFrameWithBrain(): void {
    if (!this.o.brain || !this.job.photo) return;
    this.o.brain.pushFrame(this.job.photo.data)
      .catch((err) => this.log(`[live-brain] frame push failed: ${String(err)}`));
  }

  private brainBusy = false;
  /** Depth-1 queue: while the brain is busy, keep only the LATEST question
   *  (live 25.08: silent drops ate "can you see it now?" — the tech's actual
   *  question — and the stale earlier reply read as a wrong answer). */
  private queuedQuestion: string | null = null;

  private async forwardToBrain(session: GlassSession, text: string): Promise<void> {
    if (!this.o.brain) return;
    if (this.brainBusy) {
      this.queuedQuestion = text;
      this.log("[live-brain] busy, queued: " + text.slice(0, 40));
      return;
    }
    this.brainBusy = true;
    try {
      let question: string | null = text;
      while (question !== null) {
        // A question asked while a photo is in flight should SEE that photo —
        // live 25.08 "can you see it now?" raced the 7-35s transfer and the
        // brain kept answering about the previous (blurry) frame.
        if (this.photoInFlight) {
          await Promise.race([this.photoInFlight, new Promise((r) => setTimeout(r, 35_000))])
            .catch(() => { /* capture failure already spoken */ });
        }
        try {
          const reply = await this.o.brain.ask(question);
          if (reply) await this.speak(session, reply);
        } catch (err) {
          this.log(`[live-brain] forward failed: ${String(err)}`);
        }
        question = this.queuedQuestion;
        this.queuedQuestion = null;
      }
    } finally {
      this.brainBusy = false;
    }
  }

  // NB: public — index.ts debug routes speak through the same echo-guard path.
  async speak(session: GlassSession, text: string): Promise<void> {
    this.echoGuard.push(text);
    try {
      await session.audio.speak(text);
      this.echoGuard.push(text); // window restarts after playback too
    } catch (err) {
      this.log(`[speak] failed: ${String(err)}`);
    }
  }
}

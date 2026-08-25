/** Glasses-intake logic with the MentraOS SDK abstracted away, so the exact
 *  event → job → submit → speak wiring is unit-testable with a fake session.
 *  index.ts only maps SDK events onto these methods. */
import { EchoGuard } from "./echo-guard.js";
import { isBackchannel } from "./is-backchannel.js";
import { matchCommand } from "./commands.js";
import { photoSizeLadder, type PhotoSize } from "./photo-size.js";
import {
  addUtterance, buildRunPayload, jobReady, newJob, renderSpoken, setPhoto, type JobState,
} from "./job.js";

/** The slice of AppSession the core touches (structural, for tests). */
export interface GlassSession {
  audio: { speak: (text: string, opts?: Record<string, unknown>) => Promise<unknown> };
  camera: { requestPhoto: (opts?: { size?: PhotoSize }) => Promise<{ buffer: Buffer; mimeType: string; size: number }> };
}

export interface FleetClient {
  ensureSession(sessionId: string): Promise<void>;
  run(payload: object): Promise<unknown>;
}

export interface BrainClient {
  pushFrame(jpeg: Buffer): Promise<void>;
  ask(text: string): Promise<string>;
}

export interface CoreOptions {
  appName: string;
  userId: string;
  foreman: FleetClient;
  brain?: BrainClient | null;
  photoSize?: PhotoSize;
  /** Reassurance timers while the fleet runs (ms). Tests pass []. */
  reassureAfterMs?: number[];
  log?: (msg: string) => void;
}

export class GlassIntakeCore {
  job: JobState = newJob();
  private lastPhotoAt = 0;
  private submitting = false;
  private readonly echoGuard = new EchoGuard();
  private readonly log: (msg: string) => void;

  constructor(private readonly o: CoreOptions) {
    this.log = o.log ?? ((m) => console.log(m));
  }

  /** photo_taken broadcast (system camera button = ONE shutter). */
  async onPhotoBroadcast(session: GlassSession, data: ArrayBuffer | undefined, mime = "image/jpeg"): Promise<void> {
    if (!data || data.byteLength === 0) return;
    if (Date.now() - this.lastPhotoAt <= 10_000) return; // dedupe vs requestPhoto
    this.lastPhotoAt = Date.now();
    setPhoto(this.job, Buffer.from(data), mime);
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
  async onUtterance(session: GlassSession, text: string): Promise<"echo" | "photo" | "submit" | "reset" | "note" | "filler"> {
    const t = text.trim();
    if (!t) return "echo";
    if (this.echoGuard.isEcho(t)) return "echo";
    this.log(`[voice] ${t}`);
    // "Mm-hm" / "okay" are not questions: keep them out of the notes and
    // never wake the brain on them (live 25.08: every filler got a reply,
    // and TTS is serial → answers queued up as "it lags / doesn't answer").
    if (isBackchannel(t)) return "filler";
    const cmd = matchCommand(t);
    if (cmd === "photo") { await this.capturePhoto(session); return "photo"; }
    if (cmd === "submit") { await this.submit(session); return "submit"; }
    if (cmd === "reset") {
      this.job = newJob();
      await this.speak(session, "Fresh job started.");
      return "reset";
    }
    addUtterance(this.job, t);
    if (this.o.brain) await this.forwardToBrain(session, t);
    return "note";
  }

  /** Explicit voice-command photo — requestPhoto with the size ladder. */
  async capturePhoto(session: GlassSession): Promise<boolean> {
    const attempts = photoSizeLadder(this.o.photoSize);
    for (let i = 0; i < attempts.length; i++) {
      const want = attempts[i];
      try {
        const photo = await session.camera.requestPhoto(want ? { size: want } : undefined);
        setPhoto(this.job, photo.buffer, photo.mimeType);
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

  private shareFrameWithBrain(): void {
    if (!this.o.brain || !this.job.photo) return;
    this.o.brain.pushFrame(this.job.photo.data)
      .catch((err) => this.log(`[live-brain] frame push failed: ${String(err)}`));
  }

  private brainBusy = false;

  private async forwardToBrain(session: GlassSession, text: string): Promise<void> {
    if (!this.o.brain) return;
    // One question in flight at a time: a reply that arrives while the tech
    // is already saying the next thing would just queue behind it in TTS.
    if (this.brainBusy) { this.log("[live-brain] busy, dropping: " + text.slice(0, 40)); return; }
    this.brainBusy = true;
    try {
      const reply = await this.o.brain.ask(text);
      if (reply) await this.speak(session, reply);
    } catch (err) {
      this.log(`[live-brain] forward failed: ${String(err)}`);
    } finally {
      this.brainBusy = false;
    }
  }

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

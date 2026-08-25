/**
 * foreman-glass-bridge — Mentra Live glasses → Foreman+ intake (Cloud Run).
 *
 * Hands-free field capture: the technician looks at the unit, presses the
 * camera button ONCE (the system photo reaches us via the photo_taken
 * broadcast — we never call requestPhoto on the button, that's the
 * double-shutter), talks, then says "send it" → photo + voice notes go to the
 * ADK fleet's POST /run and the scope summary is spoken back into the ear.
 *
 * Stateless infra: everything in memory, no disk — runs on Cloud Run
 * (min-instances=1; MentraOS holds a long-lived session WebSocket).
 * Optional live-guidance: LIVE_BRAIN_URL forwards non-command utterances to
 * the Gemini Live brain (live_brain/) and speaks its replies.
 */
import "dotenv/config";
import { AppServer, AppSession, TranscriptionData } from "@mentra/sdk";
import { EchoGuard } from "./echo-guard.js";
import { matchCommand } from "./commands.js";
import { parsePhotoSize, photoSizeLadder, type PhotoSize } from "./photo-size.js";
import {
  addUtterance, buildRunPayload, jobReady, newJob, renderSpoken, setPhoto,
  type JobState,
} from "./job.js";
import { ForemanClient, LiveBrainClient } from "./foreman.js";

const PACKAGE_NAME = process.env.PACKAGE_NAME ?? "com.retailbox.foreman";
const API_KEY = process.env.MENTRAOS_API_KEY ?? "";
const PORT = Number(process.env.PORT ?? 8080);
const FOREMAN_URL = process.env.FOREMAN_RUN_URL ?? "";
const APP_NAME = process.env.FOREMAN_APP_NAME ?? "foreman_app";
const USER_ID = process.env.FOREMAN_USER_ID ?? "glass-tech";
const LIVE_BRAIN_URL = process.env.LIVE_BRAIN_URL ?? "";
const DEFAULT_PHOTO_SIZE: PhotoSize | undefined = parsePhotoSize(process.env.PHOTO_SIZE);
const LANGS = (process.env.TRANSCRIBE_LANGS ?? "").split(",").map((s) => s.trim()).filter(Boolean);

if (!API_KEY) throw new Error("MENTRAOS_API_KEY is required");
if (!FOREMAN_URL) throw new Error("FOREMAN_RUN_URL is required");

class ForemanGlassBridge extends AppServer {
  private job: JobState = newJob();
  private lastPhotoAt = 0;
  private submitting = false;
  private readonly echoGuard = new EchoGuard();
  private readonly foreman = new ForemanClient(FOREMAN_URL, APP_NAME, USER_ID);
  private readonly brain = LIVE_BRAIN_URL ? new LiveBrainClient(LIVE_BRAIN_URL) : null;

  protected override async onSession(
    session: AppSession, sessionId: string, userId: string,
  ): Promise<void> {
    console.log(`[session] connected: ${sessionId} user=${userId} job=${this.job.jobId}`);

    // --- photo: SINGLE shutter. The camera button takes the system photo;
    // the frame reaches every subscriber via the photo_taken broadcast.
    session.events.onPhotoTaken((p) => {
      const data = (p as unknown as { photoData?: ArrayBuffer }).photoData;
      const mime = (p as { mimeType?: string }).mimeType ?? "image/jpeg";
      if (!data || data.byteLength === 0) return;
      if (Date.now() - this.lastPhotoAt <= 10_000) return; // dedupe vs requestPhoto
      this.lastPhotoAt = Date.now();
      setPhoto(this.job, Buffer.from(data), mime);
      console.log(`[photo] captured via photo_taken broadcast (${data.byteLength} bytes)`);
      this.speak(session, "Photo captured.");
      this.shareFrameWithBrain();
    });

    // --- voice ---
    const onFinal = async (data: TranscriptionData): Promise<void> => {
      if (!data.isFinal) return;
      const text = (data.text ?? "").trim();
      if (!text) return;
      if (this.echoGuard.isEcho(text)) return;
      console.log(`[voice] ${text}`);
      const cmd = matchCommand(text);
      if (cmd === "photo") { await this.capturePhoto(session); return; }
      if (cmd === "submit") { await this.submit(session); return; }
      if (cmd === "reset") {
        this.job = newJob();
        await this.speak(session, "Fresh job started.");
        return;
      }
      addUtterance(this.job, text);
      if (LIVE_BRAIN_URL) await this.forwardToLiveBrain(session, text);
    };
    if (LANGS.length > 0) {
      for (const lang of LANGS) session.events.onTranscriptionForLanguage(lang, onFinal);
    } else {
      session.events.onTranscription(onFinal);
    }
  }

  /** Explicit voice-command photo ("take a photo") — requestPhoto with the
   *  size ladder (30s SDK timeout on slow BT → retry smaller). */
  private async capturePhoto(session: AppSession): Promise<void> {
    const attempts = photoSizeLadder(DEFAULT_PHOTO_SIZE);
    for (let i = 0; i < attempts.length; i++) {
      const want = attempts[i];
      try {
        const photo = await session.camera.requestPhoto(want ? { size: want } : undefined);
        setPhoto(this.job, photo.buffer, photo.mimeType);
        this.lastPhotoAt = Date.now();
        console.log(`[photo] requestPhoto ok (${photo.size} bytes, size=${want ?? "default"})`);
        await this.speak(session, "Photo captured.");
        this.shareFrameWithBrain();
        return;
      } catch (err) {
        console.error(`[photo] attempt ${i} (${want ?? "default"}) failed:`, err);
      }
    }
    await this.speak(session, "Photo did not come through. Try the camera button.");
  }

  private async submit(session: AppSession): Promise<void> {
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
    const reassure = [20_000, 45_000].map((ms) =>
      setTimeout(() => { this.speak(session, "Still working — the estimator is on it."); }, ms));
    try {
      await this.speak(session, "Sending to the fleet.");
      await this.foreman.ensureSession(job.jobId);
      const t0 = Date.now();
      const events = await this.foreman.run(buildRunPayload(job, APP_NAME, USER_ID));
      reassure.forEach(clearTimeout);
      const reply = renderSpoken(events);
      console.log(`[submit] ${job.jobId} done in ${Math.round((Date.now() - t0) / 1000)}s → ${reply}`);
      await this.speak(session, reply || "The fleet has it. Scope is on the dashboard.");
      this.job = newJob(); // next capture starts clean
    } catch (err) {
      reassure.forEach(clearTimeout);
      console.error("[submit] failed:", err);
      await this.speak(session, "Sending failed. Your capture is safe — say send it to retry.");
    } finally {
      this.submitting = false;
    }
  }

  /** Photo-mode guidance: the captured photo becomes the brain's current
   *  frame, so "what is this unit?" gets answered by Gemini Live without a
   *  video stream (works away from home / off LAN). Best-effort. */
  private shareFrameWithBrain(): void {
    if (!this.brain || !this.job.photo) return;
    this.brain.pushFrame(this.job.photo.data)
      .catch((err) => console.error("[live-brain] frame push failed:", err));
  }

  private async forwardToLiveBrain(session: AppSession, text: string): Promise<void> {
    if (!this.brain) return;
    try {
      const reply = await this.brain.ask(text);
      if (reply) await this.speak(session, reply);
    } catch (err) {
      console.error("[live-brain] forward failed:", err);
    }
  }

  private async speak(session: AppSession, text: string): Promise<void> {
    this.echoGuard.push(text);
    try {
      await session.audio.speak(text);
      this.echoGuard.push(text); // window restarts after playback too
    } catch (err) {
      console.error("[speak] failed:", err);
    }
  }
}

const server = new ForemanGlassBridge({
  packageName: PACKAGE_NAME,
  apiKey: API_KEY,
  port: PORT,
  healthCheck: true,
});
server.start().then(() => {
  console.log(`[bridge] ${PACKAGE_NAME} listening on :${PORT} → ${FOREMAN_URL}`);
});

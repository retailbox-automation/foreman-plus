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
 * Optional photo-mode guidance: LIVE_BRAIN_URL gets each captured photo as
 * the Gemini Live brain's current frame and answers non-command questions.
 *
 * All logic lives in core.ts (unit-tested with a fake session); this file
 * only maps SDK events onto it.
 */
import "dotenv/config";
import { AppServer, AppSession, TranscriptionData } from "@mentra/sdk";
import { parsePhotoSize } from "./photo-size.js";
import { ForemanClient, LiveBrainClient } from "./foreman.js";
import { GlassIntakeCore } from "./core.js";

const PACKAGE_NAME = process.env.PACKAGE_NAME ?? "com.retailbox.foreman";
const API_KEY = process.env.MENTRAOS_API_KEY ?? "";
const PORT = Number(process.env.PORT ?? 8080);
const FOREMAN_URL = process.env.FOREMAN_RUN_URL ?? "";
const APP_NAME = process.env.FOREMAN_APP_NAME ?? "foreman_app";
const USER_ID = process.env.FOREMAN_USER_ID ?? "glass-tech";
const LIVE_BRAIN_URL = process.env.LIVE_BRAIN_URL ?? "";
const LANGS = (process.env.TRANSCRIBE_LANGS ?? "").split(",").map((s) => s.trim()).filter(Boolean);

if (!API_KEY) throw new Error("MENTRAOS_API_KEY is required");
if (!FOREMAN_URL) throw new Error("FOREMAN_RUN_URL is required");

class ForemanGlassBridge extends AppServer {
  private readonly core = new GlassIntakeCore({
    appName: APP_NAME,
    userId: USER_ID,
    foreman: new ForemanClient(FOREMAN_URL, APP_NAME, USER_ID),
    brain: LIVE_BRAIN_URL ? new LiveBrainClient(LIVE_BRAIN_URL) : null,
    photoSize: parsePhotoSize(process.env.PHOTO_SIZE),
  });

  protected override async onSession(
    session: AppSession, sessionId: string, userId: string,
  ): Promise<void> {
    console.log(`[session] connected: ${sessionId} user=${userId} job=${this.core.job.jobId}`);

    session.events.onButtonPress((btn) => {
      void this.core.onButtonPress(session, String(btn.buttonId), String(btn.pressType));
    });

    session.events.onPhotoTaken((p) => {
      const data = (p as unknown as { photoData?: ArrayBuffer }).photoData;
      const mime = (p as { mimeType?: string }).mimeType ?? "image/jpeg";
      void this.core.onPhotoBroadcast(session, data, mime);
    });

    const onFinal = async (data: TranscriptionData): Promise<void> => {
      if (!data.isFinal) return;
      await this.core.onUtterance(session, data.text ?? "");
    };
    if (LANGS.length > 0) {
      for (const lang of LANGS) session.events.onTranscriptionForLanguage(lang, onFinal);
    } else {
      session.events.onTranscription(onFinal);
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
  console.log(`[bridge] ${PACKAGE_NAME} listening on :${PORT} → ${FOREMAN_URL}` +
    (LIVE_BRAIN_URL ? ` (brain: ${LIVE_BRAIN_URL})` : ""));
});

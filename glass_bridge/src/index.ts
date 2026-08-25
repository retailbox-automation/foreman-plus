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

const DEBUG_KEY = process.env.DEBUG_KEY ?? "";

/** Ring buffer of structured events — the full reconstructable trace of what
 *  the glasses heard, what we decided, and what we said. Also mirrored to
 *  stdout as one-line JSON (grep GTRACE). */
const TRACE_MAX = 600;
const traceBuf: Array<Record<string, unknown>> = [];
function pushTrace(kind: string, data: Record<string, unknown>): void {
  const ev = { ts: new Date().toISOString(), kind, ...data };
  traceBuf.push(ev);
  if (traceBuf.length > TRACE_MAX) traceBuf.shift();
  console.log("GTRACE " + JSON.stringify(ev));
}

class ForemanGlassBridge extends AppServer {
  private readonly core = new GlassIntakeCore({
    appName: APP_NAME,
    userId: USER_ID,
    foreman: new ForemanClient(FOREMAN_URL, APP_NAME, USER_ID),
    brain: LIVE_BRAIN_URL ? new LiveBrainClient(LIVE_BRAIN_URL) : null,
    photoSize: parsePhotoSize(process.env.PHOTO_SIZE),
    trace: pushTrace,
  });
  private currentSession: AppSession | null = null;
  private glassesState: Record<string, unknown> | null = null;

  constructor(opts: ConstructorParameters<typeof AppServer>[0]) {
    super(opts);
    if (DEBUG_KEY) this.setupDebugRoutes();
  }

  /** Operator remote control: lets us trigger photo/stream/say and pull the
   *  captured JPEG while the technician is hands-free (or away). Enabled only
   *  when DEBUG_KEY is set; wrong/missing key answers 404 (route invisible). */
  private setupDebugRoutes(): void {
    type Req = { get(h: string): string | undefined; body?: Record<string, unknown> };
    type Res = {
      status(c: number): Res; json(b: unknown): void;
      set(h: string, v: string): Res; send(b: unknown): void; end(): void;
    };
    const app = this.getExpressApp() as unknown as {
      get(p: string, h: (req: Req, res: Res) => void): void;
      post(p: string, h: (req: Req, res: Res) => void): void;
    };
    const guarded = (h: (req: Req, res: Res, s: AppSession) => void | Promise<void>) =>
      (req: Req, res: Res): void => {
        if (req.get("x-debug-key") !== DEBUG_KEY) { res.status(404).end(); return; }
        const s = this.currentSession;
        if (!s) { res.status(503).json({ ok: false, error: "no glasses session" }); return; }
        void h(req, res, s);
      };

    app.get("/debug/trace", guarded(async (req, res) => {
      const n = Math.min(Number((req as unknown as { query?: { n?: string } }).query?.n ?? 100), TRACE_MAX);
      res.json({ ok: true, events: traceBuf.slice(-n) });
    }));

    app.get("/debug/state", guarded(async (_req, res, s) => {
      const sess = s as unknown as {
        getWifiStatus?: () => unknown;
        device?: { state?: { getSnapshot?: () => unknown } };
      };
      res.json({
        ok: true,
        awake: this.core.awake,
        job: { id: this.core.job.jobId, notes: this.core.job.transcript.length, hasPhoto: !!this.core.job.photo },
        lastPhoto: this.core.lastPhoto
          ? { bytes: this.core.lastPhoto.data.length, mimeType: this.core.lastPhoto.mimeType, ageS: Math.round((Date.now() - this.core.lastPhoto.at) / 1000) }
          : null,
        stream: this.core.streamInfo,
        wifi: sess.getWifiStatus?.() ?? null,
        device: sess.device?.state?.getSnapshot?.() ?? null,
        glasses: this.glassesState,
      });
    }));

    app.post("/debug/photo", guarded(async (_req, res, s) => {
      const ok = await this.core.capturePhoto(s);
      res.json({ ok, lastPhoto: this.core.lastPhoto ? { bytes: this.core.lastPhoto.data.length } : null });
    }));

    app.get("/debug/photo.jpg", guarded(async (_req, res) => {
      const p = this.core.lastPhoto;
      if (!p) { res.status(404).json({ ok: false, error: "no photo yet" }); return; }
      res.set("content-type", p.mimeType).send(p.data);
    }));

    app.post("/debug/stream/start", guarded(async (_req, res, s) => {
      const ok = await this.core.startLiveView(s);
      res.json({ ok, stream: this.core.streamInfo });
    }));

    app.post("/debug/stream/stop", guarded(async (_req, res, s) => {
      await this.core.stopLiveView(s);
      res.json({ ok: true });
    }));

    app.post("/debug/say", guarded(async (req, res, s) => {
      const text = String(req.body?.text ?? "").trim();
      if (!text) { res.status(400).json({ ok: false, error: "text required" }); return; }
      await this.core.speak(s, text);
      res.json({ ok: true });
    }));

    app.post("/debug/utterance", guarded(async (req, res, s) => {
      const text = String(req.body?.text ?? "").trim();
      const acted = await this.core.onUtterance(s, text);
      res.json({ ok: true, acted });
    }));
  }

  protected override async onSession(
    session: AppSession, sessionId: string, userId: string,
  ): Promise<void> {
    this.currentSession = session;
    console.log(`[session] connected: ${sessionId} user=${userId} job=${this.core.job.jobId}`);
    pushTrace("session", { phase: "connected", sessionId, userId });
    try {
      (session.events as unknown as { onDisconnected?: (h: (info: unknown) => void) => void })
        .onDisconnected?.((info) => pushTrace("session", { phase: "disconnected", info: String(info).slice(0, 200) }));
    } catch { /* trace only */ }
    try {
      (session as unknown as { onGlassesConnectionState?: (h: (st: unknown) => void) => void })
        .onGlassesConnectionState?.((st) => { this.glassesState = st as Record<string, unknown>; });
    } catch { /* older SDK shape — state stays null */ }
    try {
      session.camera.onManagedStreamStatus?.((st) => {
        const s = st as { status?: string; hlsUrl?: string; message?: string };
        console.log(`[stream] status=${s.status}${s.message ? ` msg=${s.message}` : ""}${s.hlsUrl ? ` hls=${s.hlsUrl}` : ""}`);
      });
    } catch { /* logging only */ }

    session.events.onButtonPress((btn) => {
      void this.core.onButtonPress(session, String(btn.buttonId), String(btn.pressType));
    });

    session.events.onPhotoTaken((p) => {
      const data = (p as unknown as { photoData?: ArrayBuffer }).photoData;
      const mime = (p as { mimeType?: string }).mimeType ?? "image/jpeg";
      void this.core.onPhotoBroadcast(session, data, mime);
    });

    const onFinal = async (data: TranscriptionData): Promise<void> => {
      // Interims prove the ASR pipeline is ALIVE even when finals are scarce —
      // the exact blind spot of the 20:50 "went silent" incident.
      if (!data.isFinal) {
        pushTrace("interim", { text: (data.text ?? "").slice(0, 120) });
        return;
      }
      pushTrace("transcript", { text: data.text ?? "" });
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

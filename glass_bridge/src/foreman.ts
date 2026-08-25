/** Clients for the Foreman services on Cloud Run (auth-only).
 *  Auth = Google ID token: SA key locally (GOOGLE_APPLICATION_CREDENTIALS),
 *  runtime service account on Cloud Run — both via google-auth-library. */
import { GoogleAuth, IdTokenClient } from "google-auth-library";

/** Lazily-built ID-token client for one audience (service URL). */
export class IdTokenCaller {
  private idClient: IdTokenClient | null = null;

  constructor(protected readonly baseUrl: string) {}

  protected async client(): Promise<IdTokenClient> {
    if (!this.idClient) {
      this.idClient = await new GoogleAuth().getIdTokenClient(this.baseUrl);
    }
    return this.idClient;
  }

  protected async postJson(path: string, data: object, timeoutMs: number): Promise<unknown> {
    const c = await this.client();
    const res = await c.request({
      url: `${this.baseUrl}${path}`, method: "POST", data, timeout: timeoutMs,
    });
    return res.data;
  }
}

export class ForemanClient extends IdTokenCaller {
  constructor(
    baseUrl: string,
    private readonly appName: string,
    private readonly userId: string,
  ) {
    super(baseUrl);
  }

  /** Create the ADK session for a job; 400/409 "already exists" is fine. */
  async ensureSession(sessionId: string): Promise<void> {
    const path = `/apps/${this.appName}/users/${this.userId}/sessions/${sessionId}`;
    try {
      await this.postJson(path, {}, 30_000);
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status !== 400 && status !== 409) throw err;
    }
  }

  /** POST /run (buffered) — returns the raw list[Event] JSON. */
  async run(payload: object, timeoutMs = 120_000): Promise<unknown> {
    return this.postJson("/run", payload, timeoutMs);
  }
}

/** Gemini Live guidance brain (live_brain/server.py) — photo-mode Q&A. */
export class LiveBrainClient extends IdTokenCaller {
  /** Give the brain the latest photo as its "eyes". */
  async pushFrame(jpeg: Buffer): Promise<void> {
    await this.postJson("/frame", { image_b64: jpeg.toString("base64") }, 20_000);
  }

  async ask(text: string): Promise<string> {
    // 75s: a native take_photo inside the turn adds capture (up to ~35s) +
    // a follow-up model turn on top of the base answer time.
    const body = (await this.postJson("/utterance", { text }, 75_000)) as { reply?: string };
    return body?.reply ?? "";
  }

  /** Fresh conversation for a fresh job. Best-effort. */
  async reset(): Promise<void> {
    await this.postJson("/reset", {}, 20_000);
  }

  /** Point the brain's eyes at a live HLS stream (ffmpeg on the brain side). */
  async startStream(hlsUrl: string): Promise<void> {
    await this.postJson("/stream", { url: hlsUrl }, 20_000);
  }

  async stopStream(): Promise<void> {
    const c = await this.client();
    await c.request({ url: `${this.baseUrl}/stream`, method: "DELETE", timeout: 20_000 });
  }
}

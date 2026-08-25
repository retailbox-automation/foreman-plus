/** Client for the Foreman ADK api_server on Cloud Run (auth-only).
 *  Auth = Google ID token: SA key locally (GOOGLE_APPLICATION_CREDENTIALS),
 *  runtime service account on Cloud Run — both via google-auth-library. */
import { GoogleAuth, IdTokenClient } from "google-auth-library";

export class ForemanClient {
  private idClient: IdTokenClient | null = null;

  constructor(
    private readonly baseUrl: string,
    private readonly appName: string,
    private readonly userId: string,
  ) {}

  private async client(): Promise<IdTokenClient> {
    if (!this.idClient) {
      this.idClient = await new GoogleAuth().getIdTokenClient(this.baseUrl);
    }
    return this.idClient;
  }

  /** Create the ADK session for a job; 400/409 "already exists" is fine. */
  async ensureSession(sessionId: string): Promise<void> {
    const c = await this.client();
    const url =
      `${this.baseUrl}/apps/${this.appName}/users/${this.userId}/sessions/${sessionId}`;
    try {
      await c.request({ url, method: "POST", data: {} });
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status !== 400 && status !== 409) throw err;
    }
  }

  /** POST /run (buffered) — returns the raw list[Event] JSON. */
  async run(payload: object, timeoutMs = 120_000): Promise<unknown> {
    const c = await this.client();
    const res = await c.request({
      url: `${this.baseUrl}/run`,
      method: "POST",
      data: payload,
      timeout: timeoutMs,
    });
    return res.data;
  }
}

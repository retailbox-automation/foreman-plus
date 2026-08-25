/**
 * Glasses-free e2e of the bridge's submit path: builds the exact /run payload
 * the bridge sends (nameplate photo + spoken notes), authenticates the same
 * way (ID token via ADC), hits the REAL Foreman Cloud Run, prints the spoken
 * reply + latency. Run from glass_bridge/:
 *   GOOGLE_APPLICATION_CREDENTIALS=~/.gcp-keys/foreman-agent.json \
 *   bun scripts/simulate_submit.ts [photo.jpg]
 */
import { readFileSync } from "node:fs";
import { ForemanClient } from "../src/foreman.js";
import { addUtterance, buildRunPayload, newJob, renderSpoken, setPhoto } from "../src/job.js";

const url = process.env.FOREMAN_RUN_URL ?? "https://foreman-hello-112293816563.us-central1.run.app";
const appName = process.env.FOREMAN_APP_NAME ?? "foreman_app";
const userId = process.env.FOREMAN_USER_ID ?? "glass-tech";
const photoPath = process.argv[2] ?? "../spikes/assets/nameplate.jpg";

const job = newJob();
setPhoto(job, readFileSync(photoPath), "image/jpeg");
addUtterance(job, "Water heater in the garage, no hot water since yesterday.");
addUtterance(job, "Breaker looks fine, tank is warm at the top only.");
addUtterance(job, "Homeowner says it's original to the house.");

const client = new ForemanClient(url, appName, userId);
console.log(`[sim] job=${job.jobId} → ${url}`);
const t0 = Date.now();
await client.ensureSession(job.jobId);
const events = await client.run(buildRunPayload(job, appName, userId));
const dt = ((Date.now() - t0) / 1000).toFixed(1);
const n = Array.isArray(events) ? events.length : -1;
const reply = renderSpoken(events);
console.log(`[sim] ${n} events in ${dt}s`);
console.log(`[sim] SPOKEN → ${reply || "(empty reply — bridge would say fallback line)"}`);

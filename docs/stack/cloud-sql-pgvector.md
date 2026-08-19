# Cloud SQL for PostgreSQL + pgvector — Cheatsheet (Foreman+ hackathon stack)

Sources (live-fetched 2026-08-19, official docs unless marked):
- https://docs.cloud.google.com/sql/docs/postgres/generate-manage-vector-embeddings (pgvector usage)
- https://docs.cloud.google.com/sql/docs/postgres/extensions (extension version matrix)
- https://docs.cloud.google.com/sql/docs/postgres/connect-auth-proxy (Auth Proxy v2)
- https://docs.cloud.google.com/sql/docs/postgres/connect-connectors (Python Connector)
- https://docs.cloud.google.com/sql/docs/postgres/configure-ip (public IP / authorized networks)
- https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/backups (backups/PITR)
- https://docs.cloud.google.com/sql/docs/postgres/quotas (connection limits)
- https://cloud.google.com/sql/pricing (official pricing page — fetch was truncated by the tool; cross-checked via WebSearch/bytebase, see pricing section)
- https://www.bytebase.com/dbcost/cloudsql-pricing/ (third-party aggregator, cross-check only, marked UNVERIFIED where used alone)

---

## 1. Connection paths

### Option A — Public IP + Authorized Networks (simplest, NOT what we should use for judging window)
- Enable in Console: instance → **Connections → Networking** tab → check "Public IP" → add CIDR ranges under "Authorized networks".
- Instance gets a **static IPv4** once public IP is enabled — that address doesn't change.
- ⚠️ **Authorized networks do NOT auto-update.** If a developer's home/office IP changes (very common on residential ISPs / laptop on different wifi), you must manually re-add the new CIDR in Console/`gcloud sql instances patch --authorized-networks=...` or every connection attempt fails silently with a timeout (looks like a network/firewall issue, not an auth issue — don't misdiagnose it as a Postgres problem).
- Google's own doc explicitly recommends: **"If you configure your instance to accept connections using its public IP address, also configure it to use SSL"** — i.e. public IP + authorized networks is the least-recommended pattern; docs point at Auth Proxy / connectors instead without giving a side-by-side risk table (UNVERIFIED beyond that one line).
- **Practical fix for a hackathon team with changing IPs:** don't rely on authorized networks at all — use the Cloud SQL Auth Proxy or the Python Connector (both tunnel over IAM-authenticated HTTPS, no IP allowlisting needed). Reserve public-IP+authorized-networks only for CI/Cloud Run's static egress IP if you go that route.

### Option B — Cloud SQL Auth Proxy v2 (recommended for local dev)
Install (macOS, verified from live docs, version pinned to what the doc showed — **re-check `v2.25.2` is still current before using**, `curl -O` fetch will grab whatever's live at storage.googleapis.com regardless of the pinned string below):
```bash
# Apple Silicon (M1/M2/M3/M4)
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.25.2/cloud-sql-proxy.darwin.arm64
chmod +x cloud-sql-proxy

# Intel Mac
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.25.2/cloud-sql-proxy.darwin.amd64
chmod +x cloud-sql-proxy
```
Run:
```bash
./cloud-sql-proxy --port 5432 INSTANCE_CONNECTION_NAME
# INSTANCE_CONNECTION_NAME format: PROJECT_ID:REGION:INSTANCE_ID
# e.g. foreman-hackathon:us-central1:foreman-db

# with an explicit service account key instead of ADC:
./cloud-sql-proxy --credentials-file PATH_TO_KEY_FILE INSTANCE_CONNECTION_NAME &
```
- Listens on `127.0.0.1:PORT` (5432 = standard Postgres port; pick another if you already have local Postgres running).
- **Required IAM role:** `roles/cloudsql.client` (contains `cloudsql.instances.connect`). Grant to the identity running the proxy (your user account via ADC, or the service account in `--credentials-file`).
- No public IP or authorized-networks entry needed — the proxy authenticates via IAM and tunnels over a secure channel. This is the right default for a shared hackathon team with changing IPs.

### Option C — Cloud SQL Python Connector (for our asyncpg codebase, no proxy process to run)
```bash
pip install "cloud-sql-python-connector[asyncpg]"
```
- Package supports `asyncpg` directly (doc confirms: "The drivers that PostgreSQL supports are pg8000 and asyncpg") but Google's own doc page only shows a **SQLAlchemy-wrapped example**, not a bare-asyncpg snippet — UNVERIFIED exact call signature from docs, so use the pattern below (standard community/GitHub `cloud-sql-python-connector` usage, cross-check against `google-cloud-sql-connector` repo before shipping):
```python
from google.cloud.sql.connector import Connector, IPTypes
import asyncpg

async def get_conn():
    connector = Connector()
    conn: asyncpg.Connection = await connector.connect_async(
        "PROJECT:REGION:INSTANCE",
        "asyncpg",
        user="foreman",
        password="...",       # or omit + use enable_iam_auth=True for IAM DB auth
        db="foreman",
        ip_type=IPTypes.PUBLIC,   # or PRIVATE
    )
    return conn, connector
```
- **Auth modes:** (1) built-in Postgres user/password (`user`/`password` args), or (2) **IAM database authentication** (`enable_iam_auth=True`, no password, uses `gcloud auth application-default login` / ADC — requires the DB user to be an IAM principal, set up via `gcloud sql users create ... --type=cloud_iam_user`).
- For our stack (no ORM, direct asyncpg pool): wrap `connector.connect_async` in an `asyncpg.create_pool(connect=...)`-style factory, or just hold one connection per worker — verify against our actual `db.py` before hackathon demo, this doc's example is SQLAlchemy-only.

---

## 2. pgvector on Cloud SQL for Postgres — enabling + indexing

**Version support (from live docs, `extensions` page):**
| Postgres version | Max pgvector version |
|---|---|
| 13 and later | **0.8.0** |
| 12 | up to 0.7.4 |
| 11 | up to 0.5.1 |

Our instance runs **Postgres 16** per project context → pgvector **0.8.0** available. ✅ supported.

**Enable:**
```sql
CREATE EXTENSION vector;
-- pgvector is referred to as "vector" in all SQL, including CREATE EXTENSION.
```

**Column + basic query:**
```sql
ALTER TABLE facts ADD COLUMN embedding vector(768);  -- 768 = text-embedding-004 dim; adjust to whatever Gemini embedding model dim we use

SELECT id, content
FROM facts
ORDER BY embedding <-> '[0.01, 0.02, ...]'::vector
LIMIT 10;
```

**Distance operators / operator classes** (from live docs):
| Operator class | Distance | Operator (standard pgvector, confirm on our instance — docs page only explicitly named `<->` and the ops-class names) |
|---|---|---|
| `vector_l2_ops` | Euclidean (L2) | `<->` |
| `vector_ip_ops` | (negative) inner product | `<#>` |
| `vector_cosine_ops` | Cosine distance | `<=>` |

⚠️ Doc fetch only confirmed `<->` explicitly in the text extracted; `<#>`/`<=>` are standard pgvector operators for those op classes (cross-checked against pgvector project conventions, not literally re-quoted from the Google page — verify once against our live instance with `\dAo` or a smoke query before relying on it in code).

**HNSW index (recommended over IVFFlat for pgvector ≥0.5, better recall/build without needing pre-populated data):**
```sql
CREATE INDEX ON facts
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```
- `m` (max connections per graph node): recommended range **5–48**, default **16**.
- `ef_construction` (candidate list size during build): default **64** (higher = better recall, slower build).
- Swap `vector_cosine_ops` for `vector_l2_ops` / `vector_ip_ops` per distance metric chosen.
- No documented minimum machine type/memory requirement for the index itself (doc silent) — but HNSW build is memory-hungry; **on `db-f1-micro` (0.6GB shared RAM) expect slow/failing builds on anything beyond a few thousand rows.** UNVERIFIED exact row-count ceiling — test with our real fact volume before demo day, don't assume it scales.

**IVFFlat (alternative, needs `lists` param and existing data to train on — NOT covered in the Cloud SQL doc page we fetched, this is standard pgvector syntax, UNVERIFIED against Cloud SQL specifically):**
```sql
CREATE INDEX ON facts
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
-- rule of thumb: lists = rows / 1000 for < 1M rows; needs ANALYZE after bulk load
```
- **Recommendation for hackathon scale (likely low thousands of facts):** skip indexing entirely, brute-force `ORDER BY embedding <-> $1 LIMIT k` is fine under ~50-100k rows and avoids the recall/tuning complexity of either index. Add HNSW only if profiling shows it's needed.

---

## 3. db-f1-micro limits

- **Concurrent operations cap:** doc states "Micro and small tier machine types limit the number of concurrent operations" — **f1-micro is explicitly capped at 20 concurrent operations** (live-quoted from `quotas` doc).
- **max_connections:** no published fixed number or formula — Google states it's auto-derived from the machine type's memory/core allocation at instance-creation time. **Query it directly, don't assume a number:**
  ```sql
  SELECT * FROM pg_settings WHERE name = 'max_connections';
  ```
- Combined ceiling: `max_connections + autovacuum_max_workers + max_worker_processes` must not exceed **262142** (irrelevant at f1-micro scale, just noted for completeness).
- **Practical implication for our stack:** with ADK's `DatabaseSessionService` + our own asyncpg pool + the Auth Proxy, **use a small connection pool (e.g. `min_size=1, max_size=5`)** on f1-micro — don't let asyncpg's default pool sizing or multiple agent workers exhaust connections. Not SLA-covered either way (see pricing/support note below).
- f1-micro / g1-small are **not covered by the Cloud SQL SLA** (from pricing search result, cross-check only — UNVERIFIED against the official SLA page, but consistent with GCP's general shared-core exclusion pattern).

---

## 4. Backups / PITR on the cheapest tier

- Doc text found **no explicit restriction** blocking automated backups or PITR on shared-core (`db-f1-micro`) instances — both features appear available regardless of machine type (UNVERIFIED as an explicit positive confirmation; the doc simply didn't mention a machine-type gate, absence of a restriction ≠ documented guarantee — test it live: enable backups on the actual instance and confirm PITR options appear in Console before relying on it).
- Backup retention: configurable **1 day to 10 years** depending on backup option chosen; default retention value not stated in the fetched page — check Console on our actual instance.
- Don't manually delete automated backups — PITR depends on the backup chain.
- **For a 13-day hackathon build with a ~1-month judging window:** PITR is nice-to-have insurance, not critical. Recommendation: enable automated daily backups (cheap, see pricing below) and skip configuring long PITR log retention to save transaction-log storage cost — daily backup + short PITR window (1 day) is enough to recover from an agent bug that corrupts the facts table.

---

## 5. Pricing (verify against the live calculator before final budget — figures below are cross-checked from a third-party aggregator, NOT a direct official-page quote, because the official pricing page fetch returned truncated content twice)

| Item | Price (us-central1, on-demand) | Source confidence |
|---|---|---|
| `db-f1-micro` instance | **~$8/month** (~$0.011/hr) | UNVERIFIED — bytebase aggregator, not official page |
| `db-g1-small` instance | **~$26/month** (~$0.036/hr) | UNVERIFIED — same |
| Dedicated-core Enterprise edition (for scale reference) | $0.0413/vCPU-hr + $0.007/GB-RAM-hr | UNVERIFIED — WebSearch snippet, not re-confirmed on official page |
| SSD storage | Not confirmed live (official Cloud SQL SSD storage has historically been ~$0.17/GB-month in us-central1 — **this number is from training knowledge, NOT verified this session, treat as a rough placeholder**) | ⚠️ UNVERIFIED |
| Backup storage | Not confirmed live at all this session | ⚠️ UNVERIFIED |
| Cloud SQL free tier | No dedicated Cloud SQL "always free" tier found in the fetched material (the $300 GCP trial credit is general, not Cloud SQL-specific) | UNVERIFIED absence — didn't find one, doesn't prove none exists |

**Action item before submission:** run the actual GCP Pricing Calculator (console, not WebFetch — the official page didn't render cleanly for this tool) for `db-f1-micro`, 10GB SSD, daily backups, us-central1, and paste the real number into this doc. Budget for the campaign: our $150 GCP promo credit (pending, per project CLAUDE.md) comfortably covers a db-f1-micro instance running the full 03.08–01.10 window (~2 months) even at the higher $26/mo g1-small tier (~$52 total), so **cost is not a binding constraint** — don't over-engineer for savings.

**Keeping the instance alive Sep 1 – Oct 1 (judging window):** no special action needed beyond not deleting/stopping the instance — Cloud SQL instances don't auto-suspend on idle by default (unlike some serverless products). If cost-conscious, `gcloud sql instances patch INSTANCE --activation-policy=NEVER` stops billing for compute (not storage) between demo recording and judging, then flip back to `ALWAYS` if judges need a live demo URL — but check judging criteria first (rule 39: don't damage demo readiness to save single-digit dollars).

---

## 6. Gotchas summary (read before building)

1. **Authorized networks don't follow you** — if the dev team's IPs change, every new IP needs a manual add. Use Auth Proxy or Python Connector instead; treat public-IP+allowlist as fallback only.
2. **pgvector needs Postgres 13+ for the current 0.8.0 version** — we're on 16, fine, but if anyone spins up a fresh instance accidentally on an older default version, extension version silently caps lower.
3. **No official Cloud SQL asyncpg-only code sample** — Google's docs show SQLAlchemy; our bare-asyncpg integration pattern above is inferred/standard, verify signatures against the installed `cloud-sql-python-connector` package (`pip show` + read source) before relying on it in the codebase, don't hand-wave the exact `connect_async` kwargs.
4. **f1-micro caps at 20 concurrent operations** — keep our asyncpg pool small; a burst of parallel agent tool-calls hitting the DB could exhaust this on the cheapest tier. If the multi-agent fleet gets busy during demo, consider bumping to `db-g1-small` (still ~$26/mo, still trivial vs. the $150 credit) rather than debugging connection-exhaustion errors live.
5. **HNSW index build cost on f1-micro is unverified at our scale** — test with real data volume before demo day; brute-force `ORDER BY <->` is the safer default until proven necessary to index.
6. **PITR/backup machine-type gating is unconfirmed** — enable backups on the real instance early and eyeball the Console to confirm PITR options actually appear, don't assume from doc silence.
7. **Official pricing page didn't render for WebFetch (truncated twice)** — the $/GB storage and backup numbers above are placeholders from memory/third-party aggregation, not this-session-verified. Pull real numbers from the GCP Console pricing calculator before finalizing any cost claims in the submission's "production readiness" narrative (judging criterion, 30% weight).


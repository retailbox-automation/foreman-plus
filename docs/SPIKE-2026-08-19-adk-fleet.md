# SPIKE 2 — ADK hello-fleet + DatabaseSessionService (19.08.2026)

**Вопрос:** ложится ли наш паттерн «флот агентов + общая память в Postgres» на Google ADK?

## РЕЗУЛЬТАТ: PASSED ЦЕЛИКОМ (обе ноги)
Финальное доказательство: Cloud Run `foreman-hello` (rev 00004+) с `--session_service_uri` на Cloud SQL — сессия `final-proof-1` создана, ход 1 (Carrier 24ABC636A003, 2015) прошёл через флот; принудительная НОВАЯ ревизия (00005, убивает всё in-memory) → follow-up в той же сессии: «Carrier 24ABC636A003 from 2015» — **память пережила смену ревизии, recall из Cloud SQL**. Независимая сверка psql: 2 сессии, по 8 событий. Архитектура «Cloud Run флот + Cloud SQL память» работает end-to-end.

## Результат: PASSED (локальная нога)

Скрипт: `spikes/adk_hello_fleet.py` (ADK 2.7.1, Python 3.14, `gemini-3.6-flash` по API-ключу).

Доказано за один прогон:
1. **Флот на ADK:** root-агент `foreman` с `sub_agents=[estimator]`; foreman сам вызвал `transfer_to_agent`, estimator вернул structured JSON scope (модель поняла Rheem 82V40-2 из текста).
2. **Память в Postgres:** `DatabaseSessionService(db_url="postgresql+asyncpg://…/foreman_spike")` создал 5 таблиц (`sessions`, `events`, `app_states`, `user_states`, `adk_internal_metadata`), 8 событий за 2 хода — проверено прямым `psql`, не выводом скрипта.
3. **Память переживает рестарт:** второй Runner с НОВЫМ инстансом сервиса перечитал сессию из БД и ответил на «which model did I report» → «Rheem 82V40-2, 2004, 20 years old».

## Гочи
- `DatabaseSessionService` требует extra: `pip install 'google-adk[db]' psycopg2-binary asyncpg greenlet` — голый `google-adk` падает на ImportError sqlalchemy.
- Драйвер в URL — `postgresql+asyncpg://` (сервис принимает `db_url` ИЛИ готовый `AsyncEngine`).
- ADK предупреждает: мульти-агент без `context_cache_config` пересылает весь промпт некэшированным после каждого transfer — на проде включить per-agent cache (экономия токенов/латентности).
- `GOOGLE_API_KEY` обязателен (ADK читает его, не `GEMINI_API_KEY`) + `GOOGLE_GENAI_USE_VERTEXAI=FALSE`.
- Наш собственный слой (bi-temporal память + write-gate) будет ЖИТЬ РЯДОМ в той же Cloud SQL: ADK-таблицы = session state, наши таблицы = долгая память с гейтом. Конфликта схем нет.

## Cloud-нога (19.08, после re-auth): Cloud Run PASSED
- ✅ Биллинг привязан (`014E5C-0C7AB8-05E6C6`), `billingEnabled: true` — квота 18.08 сработала.
- ✅ **Cloud Run деплой:** `adk deploy cloud_run … foreman_app` → https://foreman-hello-112293816563.us-central1.run.app (закрыт auth, max-instances=1). Живая проба `/run` с identity token: foreman → `transfer_to_agent` → estimator вернул JSON — флот работает В ОБЛАКЕ на gemini-3.6-flash.
- ✅ Cloud SQL `foreman-pg` (POSTGRES_16, db-f1-micro, us-central1, IP 136.119.47.192, пароль в Keychain `foreman-cloudsql-pg`, БД `foreman`): локальный спайк против неё PASSED; Cloud Run перевешан через unix-socket `?host=/cloudsql/foreman-hackathon:us-central1:foreman-pg` + `--add-cloudsql-instances`.
- Гоча №5: **дефолтный Dockerfile `adk deploy` ставит ГОЛЫЙ google-adk** → на `--session_service_uri postgresql+…` контейнер падает `ModuleNotFoundError: sqlalchemy` (упавшая ревизия НЕ получает трафик — старая живёт). Фикс: `foreman_app/requirements.txt` с `google-adk[db]==2.7.1`, `asyncpg`, `greenlet` — ADK подхватывает его в образ.

## Cloud-гочи (кровью)
1. 🔴 **`adk deploy cloud_run` возвращает exit 0 при УПАВШЕМ деплое** — правду смотреть в логе («Deployment failed»), zeabur-класс.
2. **Новым GCP-проектам дефолтный compute SA не даёт прав Cloud Build** → `PERMISSION_DENIED ... could not resolve source`. Фикс: `gcloud projects add-iam-policy-binding … --member=serviceAccount:<N>-compute@developer.gserviceaccount.com --role=roles/cloudbuild.builds.builder`.
3. 🔴 **Ключ формата `AQ.…` (bound-SA) игнорирует `GOOGLE_GENAI_USE_VERTEXAI=FALSE`** — genai ходит Vertex-поверхностью: сначала 403 `aiplatform.googleapis.com` disabled (включить API), затем 404 «gemini-3.6-flash not found in us-central1» — регион берётся из метаданных Cloud Run. Фикс: env **`GOOGLE_CLOUD_LOCATION=global`** (локально работало именно потому, что дефолт-локация была global).
4. Каждый `gcloud run services update` = новая ревизия = **in-memory сессии стёрты** («Session not found») — лишний аргумент за DatabaseSessionService.

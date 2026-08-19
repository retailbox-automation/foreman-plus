# SPIKE 2 — ADK hello-fleet + DatabaseSessionService (19.08.2026)

**Вопрос:** ложится ли наш паттерн «флот агентов + общая память в Postgres» на Google ADK?

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

## Осталось в спайке (cloud-нога) — гейт: gcloud re-auth admin@
- Cloud SQL for PostgreSQL: тот же скрипт с `db_url` на Cloud SQL (public IP / connector).
- Cloud Run: обернуть foreman в `adk api_server` / FastAPI, задеплоить hello-endpoint.
- Billing: квота GRANTED письмом 18.08 11:02 ET → привязать billing account к `foreman-hackathon`.

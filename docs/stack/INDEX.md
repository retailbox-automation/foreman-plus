# Stack docs — индекс и поправки (19.08.2026)

Шпаргалки написаны research-фанаутом (7 агентов, live-verified) + прогнан completeness-критик.
Читать соответствующий файл ПЕРЕД работой с областью — они заменяют поход в интернет.

| Файл | Область |
|---|---|
| `adk-core.md` | ADK 2.7: Agent/tools/Runner/events, CLI, REST api_server |
| `adk-sessions-state.md` | Sessions/state/memory/artifacts, DatabaseSessionService |
| `genai-sdk.md` | google-genai: Client-роутинг, config, мультимодалка, эмбеддинги, лимиты |
| `cloud-run.md` | Deploy, ревизии, env-семантика, Cloud SQL socket, auth, цены |
| `cloud-sql-pgvector.md` | Подключения, pgvector, db-f1-micro лимиты, цены |
| `firestore.md` | Native mode, python client, auth, квоты (вторая GCP-галочка) |
| `a2a-observability.md` | A2A endpoint/RemoteA2aAgent + OTel/Cloud Trace (--otel_to_cloud) |

## Поправки критика (сильнее текста файлов)
1. **Модель = `gemini-3.7-flash`** (переключено 19.08, тесты 19/19): 3.7-flash — «New Stable», та же цена ($0.75/$3.75 за 1M), тот же контекст (1M/65K), та же мультимодалка; 3.6-flash уже «previous-generation». Гоча: 3.7 отвергает `thinking_level="MINIMAL"` (у 3.6/3.5-lite это дефолт) — thinking-конфиг задавать явно.
2. **Cloud SQL подключение:** на Cloud Run — ТОЛЬКО unix-socket DSN через `--add-cloudsql-instances` (уже в проде, см. cloud-run.md §3). Python Connector из cloud-sql-pgvector.md — только для локалки; НЕ добавлять зависимость в контейнер.
3. **pgvector размерность:** пример `vector(768)` в cloud-sql-pgvector.md ссылается на text-embedding-004, которого у нас НЕТ. Наш эмбеддер — `gemini-embedding-2` (с 25.08.2026; до этого `gemini-embedding-001`, все строки пере-эмбеднуты `backfill_embeddings.py --all`); при создании колонки жёстко спарить размерность с `output_dimensionality=…` в КАЖДОМ embed-вызове. Гоча id: `gemini-embedding-2` — только на `location=global`; на `us-central1` он же зовётся `gemini-embedding-2-preview`; REST `:predict` → 404, работает `embedContent` (genai SDK).
4. **`adk deploy` без `--session_service_uri` молча падает в in-memory сессии** (авто-детект K_SERVICE, подтверждено кодом service_factory.py) — флаг ОБЯЗАТЕЛЕН в каждой команде деплоя.

## Консолидированные зависимости контейнера (foreman_app/requirements.txt)
Сейчас: `google-adk[db]==2.7.1`, `asyncpg`, `greenlet` (`[db]` НЕ тянет asyncpg — подтверждено metadata).
При добавлении фич: A2A → `google-adk[a2a]` · Firestore → `google-cloud-firestore` · OTel → роли ниже.

## IAM-роли runtime-SA (сводно)
Выдано: compute-SA `roles/cloudbuild.builds.builder` (деплой) + editor (легаси). foreman-agent@ = editor (наш ключ).
Понадобятся при добавлении: `roles/datastore.user` (Firestore) · `roles/cloudtrace.agent` + `roles/logging.logWriter` (OTel, UNVERIFIED) · `roles/run.invoker` (service-to-service A2A).

## Открытые действия (из гэпов критика)
- [ ] **Спайк: мультимодалка ЧЕРЕЗ ADK Runner** (фото+аудио в `new_message` → сериализация Blob в DatabaseSessionService) — самая рискованная непроверенная точка стека; сырой genai-вызов проверен 18.08, ADK-путь НЕТ.
- [ ] Реальные rate-limits смотреть на aistudio.google.com/rate-limit под oskola7 (статических цифр Google больше не публикует) — ДО нагрузочного демо.
- [ ] При подъёме `max-instances` >1 — retry-паттерн на `StaleSessionError` (optimistic concurrency DatabaseSessionService) — риск на судейском демо.

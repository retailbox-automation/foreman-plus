# Ready-made скан (rule 46) — что берём готовым, что строим сами

> Live-скан 18.08.2026, workflow wf_92ace0f5 (6 углов, 76 tool-вызовов; лицензии/звёзды/даты — проверены live через gh api, не по памяти). Полный сырой результат: task `w704mflzb`. Правила хакатона РАЗРЕШАЮТ open source + starter templates с disclosure; всё take-* ниже — Apache-2.0/MIT, попадает в disclosure-секцию сабмита.

## TAKE-AS-BASE (каркас билда)
| Что | Лицензия/живость | Что закрывает |
|---|---|---|
| **google/adk-samples → ambient-expense-agent** | Apache-2.0, repo 10.2k★, push вчера | ПОЧТИ готовый скелет Foreman+: Pub/Sub-триггер → ADK-граф → **auto-approve мелкого / LLM-risk + human-in-loop крупного** (ровно наш $-порог!) + **Terraform: 2×Cloud Run + Pub/Sub + IAM + IAP** — снимает большой кусок GCP-обучения |
| **google/agents-cli** | Apache-2.0, 5.7k★, push 04.08 | Скелет проекта: run/deploy/eval/CI-CD, встроенные skills под Claude Code. ⚠️ agent-starter-pack DEPRECATED в его пользу — не стартовать на ASP |
| **google/adk-python** | Apache-2.0, 21k★, push сегодня | Сам ADK + **встроенный `google_maps_grounding` tool** (Maps без своей обвязки!) + `adk web` dev-UI + VertexAiMemoryBankService |
| **adk-samples → safety-plugins** | Apache-2.0, push вчера | Guardrails как ADK Plugin: agent-as-judge + **прямой вызов Model Armor** — пункт Fleet-чеклиста почти даром |
| **xyflow / React Flow** | MIT, 38k★, push сегодня | Канвас node/edge для live-графа флота (наш wow «зажигается узел за узлом»); agent-семантика поверх — своя (~день) |

## TAKE-COMPONENT
- **Codelab agentic-rag-toolbox-cloudsql + googleapis/mcp-toolbox** (16k★) — готовый рецепт: SQL+pgvector semantic search как тул агента → прайсбук-поиск почти дословно (сменить домен).
- **Codelab persistent-adk-cloudsql** — session state + долгосрочная память на Cloud SQL.
- **adk-samples → invoice-processing** — 9-агентный пайплайн classification→validation→output→audit — шаблон валидации квоты И база DeskZero.
- **adk-samples → memory-bank** — PreloadMemoryTool паттерн («флот помнит клиента»).
- **a2a-samples → adk_expense_reimbursement** (repo 1.7k★, push вчера) — A2A human-in-loop reference.
- **openinference-instrumentation-google-adk** (Arize, Apache-2.0, PyPI v0.1.20) — OTel-спаны ADK без ручной инструментации → Observability-пункт Fleet. ⚠️ Phoenix/Langfuse UI — лицензии нечистые (Elastic-style) → спаны лить в **Cloud Trace** (плюс: ещё один GCP-продукт в Built With).
- **protectai/llm-guard** (MIT) — локальный fallback-сканер, если Model Armor заквотится к судейству.
- **PDF-квоты:** ecmonline/invoice-generator (MIT, weasyprint+yaml) + fortunto2/invoice-pdf-crm (MIT, Pydantic-модели line items).
- **luminati-io/Home-Depot-dataset-sample** — 1001 SKU с ценами как seed-структура синтетического прайсбука.
- **Gemini Cookbook → Pdf_structured_outputs_on_invoices** (Apache-2.0) — канонический extraction-паттерн (DeskZero).
- **actualbudget/actual** (MIT, 28k★) — референс ledger-схемы для DeskZero (Firefly III/beancount = AGPL/GPL, вендорить нельзя).

## REJECT (зафиксировано, чтобы не переискивать)
- **SalesShortcut** (Grand Prize прошлого ADK-хакатона) — **ЛИЦЕНЗИИ НЕТ** (all rights reserved) → только смотреть архитектуру глазами, код не трогать; клон и так прочтётся вторичным.
- agent-starter-pack (deprecated) · pipecat (чужой оркестрационный слой поверх ADK — разбавит «meaningfully built on ADK») · NeMo Guardrails (свой DSL, тяжёлый lift) · Langfuse/Phoenix как UI (тяжёлый селф-хост + лицензия) · AgentOps (нет ADK-интеграции, остывает) · rebuff (мёртв 2 года) · chancery (25★, слишком юн для зависимости) · open-material-data (мёртв, не в тему) · RSMeans и photo-to-quote SaaS (QuoteIQ/SimplyWise/EstimationPro — проприетарные; но: **доказывают рыночный спрос на ровно нашу фичу** → в нарратив заявки).

## GAPS = наша работа (и это хорошо: совпадает с тем, что судьи ценят как новизну)
1. **Мультимодальный «фото+голос → structured job scope» — опенсорса НЕ СУЩЕСТВУЕТ** (весь рынок — закрытые SaaS). Это ядро и главный дифференциатор Foreman+.
2. Открытого прайсбука по трейдам нет → синтетический (seed: Home Depot SKU + LLM-генерация правдоподобных цен).
3. E2E-цепочка field-service quoting (scope→price→travel→send/escalate→book→follow-up) не собрана нигде.
4. Fleet-трек: Agent Registry + Identity/revocation — зрелого OSS нет → тонкий свой слой (таблица в Cloud SQL: agent_id/version/capabilities/status + API-key-per-agent + revocation-флаг) — «meaningfully built», не обёртка.
5. Live-граф флота: React Flow + Firestore onSnapshot — ~1 день своей сборки, готового виджета нет.
6. Travel-cost логика (rate × время из Maps-тула) — своя поверх grounding-тула.
7. Не дочекан clawnify/open-fieldservice (rate-limit) — лицензию проверить перед любым использованием.

## Что это делает с feasibility Foreman+
Было 3.0 (главный страх — GCP-механика с нуля). Стало заметно лучше: Terraform+Cloud Run+Pub/Sub каркас — готовый (ambient-expense-agent), Maps — встроенный тул, pgvector-серч — рецепт codelab, guardrails —官 плагин, observability — pip-пакет. Незакрытый риск остаётся один: **мультимодальный вызов (фото+аудио) → структурированный скоуп** — он и есть verify-спайк дня 1.

## Mentra-очки (решение-рекомендация 18.08, ждёт ОК Михаила)
Очки Mentra = устройство захвата в демо-видео (hands-free кадр «смотрю и говорю — квота ушла»), НЕ интеграционная зависимость: intake принимает фото+аудио файлами откуда угодно, файлы в видео реально сняты очками — честно без live-стриминга. MentraOS SDK-мост — опциональный stretch дня 11-12 + строка в README. Нарратив-контроль: очки в кадре ≤10 сек, суть заявки — флот.

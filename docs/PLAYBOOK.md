# PLAYBOOK — All Things Agentic Hackathon (Google)

> Синтез deep-research 18.08.2026 (workflow wf_cc854129, 6 углов × sonnet, все страницы live-verified).
> Полный сырой результат: task-output `wmf4tfbg5` (session tmp) — ключевое перенесено сюда.

## 0. Вердикт-рамка
Идём. Rules-гейт 4/4 PASS. Главный риск — НЕ выбор трека, а **нулевой опыт Gemini/GCP при 13 днях** ⇒ выбирать путь с минимальным net-new обучением: концепт = наша тема (флот+память+governance), стек = самый поддержанный Google-путь (ADK).

## 1. Жёсткие факты комплаенса (все verified-live)
- **Gemini 3.5 or newer** (verbatim) через Gemini API или Vertex AI. ⚠️ **Gemini 3.5 Pro публично НЕ доступен** (Aug 2026, «coming soon») — GA: **Gemini 3.6 Flash и 3.5 Flash-Lite** → архитектуру строить на Flash-tier с первого дня.
- **Agent Framework (≥1 из списка): Google ADK / GenAI SDK / Antigravity SDK / GenKit 3.** 🔴 **LangGraph НЕ в списке** — «звали Gemini через LangChain» галочку НЕ закрывает. Безопасно: core agent loop на **ADK** (+ raw `google-genai` под капотом).
- **GCP-сервис (≥1): Cloud Run / Cloud SQL / Firestore / GKE / Pub/Sub.**
- **Видео ≤4 мин** (судятся только первые 4), EN или сабы, YouTube/Vimeo, **ОБЯЗАН показать backend живьём на Google Cloud** (консоль/Cloud Run dashboard/Vertex-логи/.run URL в кадре) — жёстче CRDB-хакатона. Голое screen-recording без нарратива = риск DQ (прецедент 100 Agents).
- **Архитектурная диаграмма — ОБЯЗАТЕЛЬНА** (не бонус): Gemini connection + backend + database + frontend.
- **Репо: можно ПРИВАТНЫЙ** — доступ `testing@devpost.com` + `cloudhackathons@google.com`. README со spin-up.
- **Один проект = максимум ОДИН приз** («Each Project is eligible for up to one (1) Prize»); Category выбирается в форме сабмита — стратегия «свипнуть несколько категорий» не работает.
- **Newly created 03–31.08**; pre-existing код раскрывать; recycled-проект (перенос FleetMemory-кода wholesale) = DQ-класс — только паттерны, rebuild Google-native.
- **Кредиты $150 НЕ автоматические**: форма forms.gle/5PtXmw1dSbDnpYke9, **дедлайн 28.08 12:00 PT «or while supplies last»**, ревью до 72 бизнес-часов ⇒ подать НЕМЕДЛЕННО (день 1).
- Судьи не названы (плейсхолдер); прокси их вкуса = resources-таб + воркшопы.
- Скоринг: база 5.0 (Innovation&Operational Utility **40%** / Architectural Discipline **30%** / Demo&Production Readiness **30%**) + бонусы: +0.2 published content, +0.2 соц-пост #AllThingsAgenticHackathon, +0.2 за каждую доп. Google AI модель (кап этой корзины 0.6). ⚠️ суммарный кап бонусов (1.0 vs 0.6) — перепроверить построчно перед сабмитом.
- **Воркшопы:** 20.08 «Build a Self-Evolving Agent», **27.08 «Architecting Agent Memory»** (session state + vector search — НАША тема; смотреть запись, не терять билд-день). Discord: discord.gg/HP4BhW3hnp.

## 2. Треки — что судят (verbatim-основа)
| Трек | Приз | Суть | Наш фит |
|---|---|---|---|
| Taskmaster | $20k | workflow-агент «not just a chatbot», multi-step background workflows | средний |
| Collaborative Partner | $20k | адаптивный агент: clarifying questions, feedback loop, stateful dialogue+RAG | средний |
| **Fortified Enterprise Fleet** | $20k | **чеклист = наша архитектура**: Agent Registry (discovery/versioning) · Agent Runtime & Memory Bank (persistent context) · Agent Identity/Gateway/Model Armor (security) · Agent Observability (OTel-audit) | **максимальный** |
| Startup Excellence | $20k | требует incorporated org + corporate email (мы проходим: Retailbox + admin@) — пул уже, чем у остальных | высокий (фильтр по entity) |
| Individual/Hobbyist | $10k×2 | спец-категория поверх треков; team-cap не найден verbatim — уточнить в FAQ/Discord | запасной |
| Best Architectural Design | $5k×2 | «decoupling, managing state and memory» — наш конёк, но платит меньше | fallback |

**Реко ставки: Fortified Enterprise Fleet.** Обоснование: (а) track-чеклист покрывается нашими прод-паттернами почти 1:1 (память+гейт из FleetMemory-опыта; identity/audit — паттерны AIM-флота, обезличенно); (б) при нулевом GCP-опыте это единственный трек, где новое — только стек, а не ещё и продукт-стори. Риск: имя трека («Fleet») притянет конкурентов той же ниши. Alt: Startup Excellence (тот же $20k, пул отфильтрован по incorporation). Решение — за Михаилом.

## 3. Рекомендуемый стек (минимум net-new, всё названо в их списках)
- **ADK (Python)** — core agent loop (флагман Google, ADK 2.5: graph Workflows, human-in-the-loop, MCP+A2A нативно). `DatabaseSessionService` (Postgres/asyncpg) = checkpointer-аналог.
- **Gemini 3.6 Flash / 3.5 Flash-Lite** (GenAI SDK под капотом; Pro недоступен). Free-tier RPM (5–15) убьёт live-демо multi-call цикла ⇒ **биллинг включить рано**, Flash-tier дёшев.
- **Cloud SQL for PostgreSQL + pgvector** — наш bi-temporal слой памяти + write-gate на СВОИХ таблицах (Vertex Memory Bank = managed чёрный ящик, наш verifier туда не встроить — Memory Bank можно name-check'нуть как сравнение). Alt-upgrade: AlloyDB AI (ScaNN), если останется время.
- **Firestore** — session/short-term state (вторая GCP-галочка).
- **Cloud Run** — хостинг (аналог нашей Lambda; cold start: min-instances=1 только на демо/судейство, иначе 0 — беречь кредиты).
- **A2A protocol между агентами флота** (нативен в ADK) — дешёвый сильный сигнал Architectural Discipline: их собственный протокол вместо внутреннего вызова.
- **Embedding-модель Google** (Vertex embeddings / EmbeddingGemma) — нужна нам всё равно для recall ⇒ бонус «additional Google AI model» почти бесплатно. +Gemma как классификатор шага, если ляжет органично (ещё +0.2).
- ⚠️ Ребрендинг: Vertex AI → **Gemini Enterprise Agent Platform** (Apr 2026); Agent Engine→Agent Runtime, Memory Bank→Agent Platform Memory Bank. Старые туториалы валидны под новыми именами.

## 4. Паттерны победителей Google-хакатонов (разбор ADK Hackathon: 10.4k участников → 477 сабмитов ≈ 4.6% конверсия)
Отличия от AWS/DB-вендорских:
1. **Одна мощная архитектурная диаграмма > галерея UI-скриншотов** (Grand Prize SalesShortcut: вся галерея = 1 диаграмма).
2. **Хедлайн-метрика = топология агентов** (34 агента: 21 LLM/7 Seq/1 Par/2 Custom/1 Loop; 5 микросервисов; 16 тулов) — НЕ бизнес-цифры. Регионалы добавляют одну societal-масштаб цифру (Edu.AI: 3.9M студентов ENEM).
3. **Отдельная секция «Bonuses»** у Grand Prize: PR/issues в ADK-репо + Medium/LinkedIn-посты. Экосистемный вклад коррелирует именно с ТОП-призом. (У нас уже есть жанр: LangGraph#8620.)
4. **Built With из 8–9 Google-продуктов** — широта стека видима и вознаграждается.
5. Нарратив «How Each Agent Works» — агенты как персонажи с ролями.

## 5. Конкуренты
Gallery не опубликована (0 видимых), соц-чаттера нет, форум-тред без ответов. Участников 4,862 (растёт). Прокси-оценка сабмитов: ~220–250. Прямых «agentic memory / write-gate» проектов в видимых источниках нет — но это НЕ полный census. Re-check gallery: 28–31.08 и после закрытия.

## 6. План (13 дней)
- **18–19.08 — День 1:** форма кредитов $150 (СРОЧНО) · GCP-проект + биллинг · Devpost-регистрация (SSO oskola7) · выбор трека+концепта с Михаилом · **verify-спайк ADK**: quickstart + DatabaseSessionService на Cloud SQL + один Gemini 3.6 Flash вызов + деплой hello-agent на Cloud Run (самое рискованное предположение: «наш паттерн ложится на ADK»).
- **20–24.08:** ядро — схема памяти (bi-temporal + gate journal) на Cloud SQL/pgvector · write-gate + verifier на Gemini · 2–3 агента флота на ADK, связь по A2A · registry+observability слой (OTel-логи) под чеклист трека.
- **25–27.08:** фронт-дашборд (наш проверенный жанр: журнал гейта + вердикты + чаты) · red-team прогон (жанр 4.6: цифра + найденные дыры) · воркшоп 27.08 в записи.
- **28–29.08:** видео (≤4 мин, GCP-консоль в кадре, нарратив; freezedetect; YT Audio Library) · диаграмма · README · галерея (1 главная диаграмма + скрины) · блог-пост (+0.2) + соц-пост (+0.2) · **САБМИТ 29.08** (буфер 2 дня).
- **30–31.08:** буфер + re-check gallery + финальная перечитка rules построчно.
- **01.09:** вотчер на demo URL (до 01.10); DB-триал/биллинг — проверить, что кластер переживает судейство (урок CRDB!).

## 7. Открытые вопросы
1. Трек (реко: Fortified Enterprise Fleet) — Михаил.
2. Концепт-обёртка поверх трека (продукт-стори; предложения готовятся после выбора трека).
3. Репо public vs private (private разрешён; public = наш open-source-credibility play) — Михаил.
4. Individual/Hobbyist: team-size cap — уточнить в FAQ/Discord (если пойдём туда).
4b. Механика спец-категорий (Best Multimodal UX / Best Architectural Design): выбираются полем формы или присуждаются судьями поверх? — уточнить в Discord/FAQ; влияет на очки-рычаг (CAPTURE-DEVICES §«Очки как скоринговый рычаг»).
5. Кап бонусов 0.6 vs 1.0 — перечитать rules построчно перед сабмитом.
6. Полный список из 8 cost-optimization рекомендаций организаторов (вытащено 4: Flash-приоритет, scale-to-zero, budget alerts, auth на эндпоинтах) — дочитать resources.

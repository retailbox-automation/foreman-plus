# Retailbox — All Things Agentic Hackathon (Google)

**Что это:** участие в allthingsagentichackathon.devpost.com (Google, $180k pool). **Решение Михаила 18.08.2026: участвуем** (приоритет смещён с Agents for Humans 14.09 — тот остаётся опцией после 31.08).

## Ключевые даты
- **Окно кода/сабмишена: 03–31.08.2026** («newly created during the Submission Period» — код пишем только в окне; мы стартуем 18.08, легально).
- **Дедлайн: 31.08.2026 17:00 PDT (20:00 EDT).** Внутренний таргет сабмита: 28–29.08 (буфер).
- Judging: 01.09–01.10 · Winners: ~08.10. Календарь: 3 события поставлены 18.08 (Tasks cal).

## Правила (rules-чек живьём 18.08, WebFetch /rules) — 4/4 PASS
1. **AI-policy:** AI coding assistants разрешены явно; «disclose any other pre-existing code».
2. **Newly created:** проект создаётся в окне 03–31.08; pre-existing код раскрывать.
3. **IP:** «solely owned by the Entrant» — наш код наш; Google получает только non-exclusive license на evaluation/promo (стандартный Devpost-грант).
4. **Лицензия:** open-source НЕ обязателен; **репо может быть ПРИВАТНЫМ** — доступ testing@devpost.com + cloudhackathons@google.com.

## Обязательный стек (все три условия)
- **Gemini** (через Gemini API или Vertex AI) — точную мин. версию уточняет research (плашка «3.5 or newer» из первого фетча — перепроверить);
- **≥1 Google Agent Framework:** Google ADK / GenAI SDK / Antigravity SDK / GenKit;
- **≥1 Google Cloud сервис:** Cloud Run / Cloud SQL / Firestore / GKE / Pub/Sub и т.п.
- $150 промо-кредитов GCP участникам.

## Сабмишен-требования
Репо (можно private, доступ судьям) · видео **≤4 мин** (YouTube/Vimeo, EN или сабы, Google Cloud «in action» в кадре) · text description · **архитектурная диаграмма** · README со spin-up инструкциями · demo URL «highly encouraged».

## Судейство (веса!)
1. Innovation & Operational Utility — **40%** (real-world friction, autonomous execution)
2. Architectural Discipline & Tech Stack — **30%** (design, modularity, state management)
3. Demo & Production Readiness — **30%**
Бонусы: +0.2 блог/подкаст · +0.2 соц-пост #AllThingsAgenticHackathon · +0.2 доп. Google AI модели (max +0.6).

## Треки
Grand $50k · Taskmaster $20k · Collaborative Partner $20k · Fortified Enterprise Fleet $20k · Startup Excellence $20k · **Individual/Hobbyist $10k×2 (соло)** · Best Architectural Design $5k×2 · Best Multimodal UX $5k×2 · HM $2k×5. Выбор ставки — по итогам research (угол max-benefit).

## Методология
По skill `hackathon-entry` + `~/.claude/projects/-Users-oskolamicheal/memory/hackathon-winning-methodology-2026-07.md`. Действующий пример цикла: `~/Projects/Retailbox - CockroachDB Hackathon/` (FleetMemory, SUBMITTED 14.08). Скаутинг-хаб — там же (`docs/HACKATHON-SCOUTING-2026-08-17.md`).

## Статус / решения
- 2026-08-18: кампания стартована. Rules-чек 4/4 PASS. **Deep-research ЗАВЕРШЁН** (6 углов, все live-verified) → **`docs/PLAYBOOK.md` = канон** (стек, треки, паттерны победителей, план 13 дней). Папка + git init (main). Календарь ×3.
- 🔴 **СРОЧНО (не гейтится ничем): форма кредитов $150** — forms.gle/5PtXmw1dSbDnpYke9, дедлайн 28.08 12:00 PT «or while supplies last», ревью до 72 бизнес-часов.
- 🔴 **Gemini 3.5 Pro публично НЕдоступен** (Aug 2026) — строить на **Gemini 3.6 Flash / 3.5 Flash-Lite**. LangGraph требование framework НЕ закрывает — core loop на **ADK**.
- 2026-08-18 (вечер): **Grand Prize-стратегия зафиксирована**: Foreman скейлится на гранд имеющимися осями (цифра масштаба + топология 12-15 агентов + 8-9 продуктов + ecosystem-вклад + все бонусы), «искать проблему поактуальнее» — ложный рычаг (прецедент: гранд ADK Hackathon = sales-автоматизация с архитектурой, societal-цифры брали только регионалки). **Устройства захвата** → `docs/CAPTURE-DEVICES-2026-08-18.md`: intake device-agnostic, телефон = основной, Mentra = кадр видео ≤10 сек, **Google Android XR glasses в окно недоступны** (релиз осень 2026, проверено live) → строка нарратива «ready for Android XR shipping this fall».
- 2026-08-18: **репо = ПУБЛИЧНЫЙ MIT (решение Михаила)**. Концепт-панель (8 кандидатов × 3 адверсарных судьи): **Foreman №1 единогласно (4.12)** → реко «Foreman+» (усиленный) — `docs/CONCEPT-PANEL-2026-08-18.md` + HTML-сводка открыта Михаилу. **Ready-made скан выполнен** → `docs/READY-MADE-SCAN-2026-08-18.md`: каркас = adk-samples/ambient-expense-agent (auto-approve/escalate + Terraform) + agents-cli + встроенный Maps-тул + safety-plugins (Model Armor) + React Flow; мультимодальный intake «фото+голос→scope» опенсорсом НЕ существует = наш дифференциатор. ⚠️ SalesShortcut без лицензии — код не трогать. Mentra-очки: устройство захвата в демо-видео, НЕ зависимость (SDK-мост = stretch).
- 2026-08-18 (вечер): ✅ **РЕШЕНО МИХАИЛОМ: концепт = Foreman+, трек = Startup Excellence** («Согласовано» + выбор в AskUserQuestion). NOT pending. Билд стартован.
- 2026-08-18 (день 1): ✅ **Devpost-регистрация на хакатон ВЫПОЛНЕНА** («Thanks for registering!», участник #4895; анкета: Working solo, org RetailBox Automation, Discord NA, GEAR No, маркетинг-опцию не ставили). ✅ **Форма кредитов $150 ПОДАНА** («Your response has been recorded»; email oskola7@gmail.com, в поле трека назван билд-трек The Taskmaster — форма автодеклайнит без трека С ХАКАТОН-СТРАНИЦЫ, Startup Excellence = призовая категория при сабмите, не билд-трек). ⏳ pending external: код кредитов ≤72 бизнес-часов → проверка: `python3 ~/.claude/scripts/gmail_imap.py search --account oskola7 --query 'FROM "devpost" SUBJECT "credit"' --days 4` (+ вариант FROM google). 🔴 Кредит-код: **redeem ДО 03.09**, 90 дней на использование.
- 2026-08-18 (день 1, продолжение): ✅ **ГЛАВНЫЙ СПАЙК PASSED** → `docs/SPIKE-2026-08-18-multimodal.md`: один вызов gemini-3.5-flash с фото+аудио → structured scope за 14.9s на free tier; vision прочитал ШИЛЬДИК (Rheem 82V40-2, serial, 05/2004) — ядро Foreman+ подтверждено, риск концепта снят. ✅ GCP-проект **foreman-hackathon** + SA foreman-agent@ + Gemini-ключ (bound-SA, формат `AQ.…`; Keychain `gemini-foreman-spike` + .env). Модели live: 3.5/3.6/**3.7**-flash. Гочи: AI Studio key-creation = анти-абьюз стена → путь через Cloud Console Credentials; ключ ОБЯЗАН быть bound к SA. 🔴 **Billing quota борды исчерпана (5 проектов)** → quota increase ПОДАН (~2 бизнес-дня); до тех пор free tier (image-gen закрыт, Cloud Run/SQL ждут).
- 2026-08-19 (день 2): ✅ **Billing quota GRANTED** (письмо Google Cloud Compliance на admin@ 18.08 11:02 ET; NOT pending) → можно привязывать биллинг к foreman-hackathon. ✅ **СПАЙК 2 PASSED (локальная нога)** → `docs/SPIKE-2026-08-19-adk-fleet.md`: ADK 2.7.1 флот foreman→estimator на gemini-3.6-flash + `DatabaseSessionService` на Postgres, память пережила рестарт (verified psql). Гочи: нужен `google-adk[db]`+asyncpg; `GOOGLE_API_KEY`, не GEMINI_. ⏳ cloud-нога (Cloud SQL + Cloud Run) гейтится re-auth gcloud admin@ (токен протух, нужен живой SSO-клик).
- ⏳ pending external: код кредитов $150 (форма подана 18.08, ≤72 бизнес-ч, redeem до 03.09; на 19.08 письма НЕТ — проверен весь inbox) — чек: `gmail_imap.py search --account oskola7 --query 'SUBJECT "credit"' --days 4`. Дальше: cloud-нога спайка → схема БД → флот.

## Гочи (пополнять)
- Devpost-вход: **Google SSO oskola7@gmail.com в дефолтном CfT-профиле** (:9224/:9225), НЕ сброс пароля (ложный гейт 11-14.08, см. CRDB CLAUDE.md).
- Клиентский код/имена — НИКОГДА в репо кампании (уйдёт судьям): только обезличенные паттерны.
- Видео: канон + лицензии музыки → `~/Projects/Retailbox - CockroachDB Hackathon/docs/VIDEO-CRAFT-NOTES.md` (freezedetect, YouTube Audio Library, новая заливка = новый URL).

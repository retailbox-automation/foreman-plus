# SPIKE 18.08.2026 — мультимодальный intake (фото+голос → structured scope) ✅ PASSED

## Что проверяли
Самое рискованное техпредположение Foreman+ (гейт на весь концепт): может ли ОДИН вызов Gemini принять фото с объекта + голосовую заметку техника и вернуть структурированный job scope по схеме.

## Сетап
- Фото: РЕАЛЬНОЕ (наша инспекция 14.06) — водогрей Rheem 40gal 2004 г. в гараже.
- Аудио: голосовая заметка техника, синтез `say -v Daniel` → AIFF («dripping for a week, drain valve corroded, wants it replaced, access through garage»).
- Вызов: REST `generativelanguage.googleapis.com` / **gemini-3.5-flash** `generateContent`, обе модальности `inline_data` в одном contents, `response_schema` (OBJECT: problem/likely_cause/severity/trade/materials[]/labor_hours/voice_summary/photo_observations[]), temp 0.2.
- Скрипт: python3 stdlib (urllib), без SDK. Ассеты: session scratchpad `spike/`.

## Результат (14.9s, 1389 in / 343 out токенов, FREE TIER)
- **Vision прочитал ШИЛЬДИК с фото**: «Rheemglas Fury EverKleen, Model 82V40-2, Serial RH 0504B01826, 40 US Gallons, manufacture 05/2004 (~20 лет)» — и даже pest-inspection наклейку 3/30/17. Это уровень демо-wow сам по себе.
- **Audio понят полностью**: неделя протечки, корродированный вентиль, клиент хочет замену (не ремонт), доступ через гараж.
- **Синтез модальностей**: likely_cause связал возраст юнита (из фото) с жалобой (из аудио); materials = новый 40-gal electric heater + install kit; labor 3h; severity medium.
- Схема соблюдена строго, JSON валиден с первого вызова.

## Вердикт
**Ядро Foreman+ технически подтверждено в день 1.** Главный риск концепта (feasibility 3.0 у судей) снят: мультимодальный intake работает лучше ожиданий — реальная шильдик-экстракция даёт материал для killer-демо («фотографируешь — флот знает модель и возраст оборудования»).

## Инфраструктура, созданная по ходу (все verified)
- GCP-проект **`foreman-hackathon`** (org retailbox-automation.com). Gemini API enabled.
- Service account **`foreman-agent@foreman-hackathon.iam.gserviceaccount.com`**.
- API-ключ `foreman-spike`: **bound к SA, restricted до Gemini API**. Хранение: Keychain `gemini-foreman-spike` + `.env` проекта (gitignored). Формат ключа **`AQ.…`** (SA-bound), НЕ `AIza`.
- Доступные модели по ключу (live): gemini-3.5-flash, 3.5-flash-lite, **3.6-flash, 3.7-flash**, 3.1-pro-preview и др. — комплаенс-пол «3.5 or newer» закрыт с запасом.

## Гочи (кровью)
1. **AI Studio «Create key» = анти-абьюз стена** («The request is suspicious») даже на нативных кликах; «Create project» из AI Studio тихо no-op. Рабочий путь: **Cloud Console → APIs & Services → Credentials → Create credentials → API key**.
2. **Gemini API key ОБЯЗАН быть bound к service account** (новая механика 2026): в диалоге сначала чекбокс «Authenticate API calls through a service account», потом restrictions=Gemini API, потом выбрать/создать SA. Без SA Gemini API в списке restrictions disabled.
3. 🔴 **Billing quota exhausted**: биллинг-аккаунт 014E5C-0C7AB8-05E6C6 упёрся в лимит 5 проектов → «Unable to enable billing». **Quota increase request ПОДАН** (10 проектов, форма support.google.com/code/contact/billing_quota_increase, ответ ~2 бизнес-дня). До одобрения проект живёт на free tier: text/vision модели работают (10 RPM/250 RPD Flash), **image-gen закрыт** (limit 0 — paid only). Cloud Run/Cloud SQL потребуют биллинг → ждём квоту или $150-кредиты (redeem создаст свой биллинг-путь — проверить при получении кода).
4. Free-tier лимиты хватило на спайк; для мульти-агент demo нужен биллинг (как и предсказал research).

## Следующие шаги
ADK hello-fleet спайк (pip install google-adk, DatabaseSessionService) — можно на текущем ключе · дождаться кредитов ($150, форма подана) и/или billing quota → Cloud Run деплой.

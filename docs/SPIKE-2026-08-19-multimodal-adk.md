# SPIKE 3 — мультимодальный intake ЧЕРЕЗ ADK Runner ✅ PASSED (обе ноги)

**Риск-точка №1 из docs/stack/INDEX.md:** сырой Gemini-вызов с фото+аудио был проверен 18.08,
но путь через ADK (Runner → флот с tools → DatabaseSessionService) — нет. Теперь да.

## Локальная нога (тест: `tests/test_multimodal_intake.py`, live)
`new_message = Content(parts=[text, Blob(image/jpeg), Blob(audio/aiff)])` через `Runner.run_async`:
- foreman **прочитал шильдик с ФОТО** (модель, серийник `RH 0504B01826`, 05/2004 — в тексте их НЕТ),
  жалобу взял из ГОЛОСА (`say -v Daniel` AIFF), записал всё через write-gate;
- estimator прочитал память, дал оценку, записал через гейт;
- сессия с бинарями **пережила персист в Postgres** (fresh service перечитал).

## Облачная нога (Cloud Run rev 00009, gemini-3.7-flash)
REST `/run` с `inlineData` base64 (~1.1MB payload) → **6 approved-фактов в Cloud SQL**:
equipment_model `Rheem 82V40-2`, serial, manufacture_date — с фото; issue, access_location — из
голоса; estimate — от estimator. Полный продакшн-путь «телефон → REST → флот → память» работает.

## Гочи
1. **OCR шильдика варьирует одну букву между прогонами** (82V40-2 ↔ 82VH40-2) — асерты/сверки
   строить по стабильным частям (серийник стабилен), в проде — нормализация против каталога моделей.
2. **Бинари хранятся INLINE в events** (~1.6MB на intake в таблице events) — для демо ок; продовая
   нота: фото → artifact service (`gs://`, флаг `--artifact_service_uri`), в events только ссылка.
3. `create_session` с существующим id → `AlreadyExistsError` (Postgres-персист!) — id генерить.
4. Аудио `audio/aiff` Gemini ест напрямую, конвертация не нужна.

## Демо-эффект
«Фотографируешь шильдик + наговариваешь проблему → через 20 секунд у флота в памяти модель,
серийник, возраст юнита и структурированная оценка работ, каждая запись — через верифицируемый
гейт с журналом». Это и есть killer-кадр видео.

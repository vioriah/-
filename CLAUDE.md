# Тренажёр 日本語初歩 — контекст для Claude Code

Этот файл — передача работы из облачной сессии Claude Code (claude.ai/code) в локальный терминал.
Полный журнал того диалога (сообщения пользователя и ответы Claude, без вывода инструментов,
ключ API вычищен) пользователь хранит локально как `docs/handoff/dialog.md`. Этот файл в git не
добавлять (он в `.gitignore`): репозиторий публичный. Читайте журнал, если нужно понять, почему
что-то сделано именно так.

## Кто пользователь и чего хочет

- Студент 1 курса, проходит учебник «日本語初歩» (Japan Foundation, 34 урока) в вузе, есть пробелы.
- Цели: грамматика как единая система и автоматизм; кандзи (Anki, онъёми и кунъёми, примеры); слова;
  интерактивные способы вместо многочасовой зубрёжки; аудирование и говорение.
- Работает в основном с iPad (Safari и Chrome); Cloudflare и GitHub настраивает через браузер.
- Общение по-русски. В облачной сессии был включён стиль «caveman»: ответ первым, без вступлений
  и повторов, факты, код, пути и числа дословно. Коммиты, документация и вопросы пользователю —
  полными предложениями.

## Что есть в репозитории

Репозиторий `vioriah/-` (публичный). Рабочая ветка `claude/japanese-grammar-kanji-vocab-9acemd`,
она же ветка по умолчанию. PR не создавать, пока пользователь не попросит.

| Путь | Что это |
|---|---|
| `grammar/grammar_system.md` | Вся грамматика как одна схема: 8 вопросов о сказуемом, §0–§11, таблицы форм, частиц, связок, модальности, залога, 敬語; §10 — карта уроков (её парсит `lesson_topics()` в `build_trainer.py`) |
| `grammar/sentences.tsv` | 224 фразы: `lesson, pattern, jp, ru, furigana` |
| `grammar/particle_slots.json` | 438 пропусков частиц `[idx, offset, particle]` для упражнения |
| `data/vocab.tsv` | 1223 слова: `lesson, type, kana, kanji, ru, pos` (pos: v5, v1, vs, vk, adj-i, adj-na); опечатки исходного docx исправлены |
| `data/kanji_core.txt` | 383 кандзи по таблице 新出漢字表 учебника: `кандзи|значение|он|кун|доп. примеры`, маркеры уроков `@N`; 母 перенесён в урок 12; чтения сверены с KANJIDIC2/JMdict |
| `data/textbook_kanji_words.txt`, `data/extra_glossary.tsv` | Слова-примеры к кандзи |
| `data/kanjivg/*.svg` | Порядок черт KanjiVG (CC BY-SA 3.0, атрибуция в README папки) |
| `anki/nihongo_shoho.apkg` | Колода: 1183 слова, 383 кандзи, 224 фразы, 3580 карточек, озвучка через `{{tts ja_JP:…}}`, стабильные GUID |
| `trainer/template.html` | Исходник тренажёра (один HTML, весь JS внутри) |
| `trainer/index.html` | Собранный тренажёр (≈815 КБ, данные встроены). Руками не править — пересобирать |
| `worker/` | Посредник на Cloudflare Workers для Claude на сайте (`worker.js`, `wrangler.toml`, README) |
| `.github/workflows/pages.yml` | Публикация на GitHub Pages при пуше `trainer/index.html` или `.apkg` |
| `tools/` | Скрипты сборки и проверки (ниже) |

## Сборка

```sh
pip install genanki            # колода
# нужен pandoc в PATH (карта грамматики в тренажёре)
python tools/build_anki.py      # → anki/nihongo_shoho.apkg
python tools/build_trainer.py   # → trainer/index.html
python tools/build_trainer.py --artifact /путь/trainer_artifact.html   # версия для артефакта claude.ai (без <head>)
```

Вспомогательные скрипты (нужны только при изменении данных):

- `tools/add_furigana.py [--force]` — фуригана для новых фраз в `sentences.tsv`; нужно `pip install fugashi unidic-lite`.
  Ошибки в числах, счётных словах и 日本 исправляет список `FIXES`; новые строки проверяйте глазами.
- `tools/make_particle_slots.py` — пересоздаёт `particle_slots.json` (отфильтрованы と в начале,
  では в ではありません, の-номинализатор).
- `tools/check_kanji.py [jamdict.db]` — сверка `kanji_core.txt` с таблицей учебника и KANJIDIC2
  (база jamdict скачивается отдельно, в репозитории её нет).

Исходники пользователя (сканы учебника, пособие по грамматике Пряхиной–Моргун, docx со словами)
в репозиторий не клались. У сканов был скрытый OCR-слой: страница учебника N = страница PDF N+9,
после с. 250 — N+10.

## Тренажёр (`trainer/template.html`)

Вкладки (хеш-маршруты): `cards` Карточки, `forms` Формы, `particles` Частицы, `speak` Скажи,
`listen` Слушай, `read` Чтение, `chat` Собеседник, `map` Карта грамматики.

- Оформление: пиксельный Y2K в духе Windows 95 (выбор пользователя, образец — пиксель-арт с окном Windows
  и панелью задач). Каждый `.sheet`, `.deck`, `.map` — окно: заголовок добавляет `winify()`/`winbar()`
  (тексты в `WIN`), вкладки — кнопки панели задач `.taskbar` внизу, в трее счёт за день и часы.
  Объём — через токены `--out`/`--in` (box-shadow), тени жёсткие, без скруглений. Шрифты: DotGothic16
  (японский, есть кириллица), Pixelify Sans (кириллица и латиница), Silkscreen (только латиница: заголовки
  окон, часы). Галочка «рукописный шрифт для японского» (`shoho.kyo`) подгружает Klee One.
- Заставка при входе (блок `<!--BOOT-->…<!--/BOOT-->` в шаблоне): загрузочный экран в духе Windows 95
  с пиксельным логотипом МГИМО (`trainer/boot_logo.png`, вставляется при сборке) и подписью
  «Неофициальный учебный тренажёр студента МГИМО». Один раз за сеанс (`sessionStorage shoho.boot`),
  2,6 с или до тапа/клавиши. В версию для артефакта claude.ai заставка не попадает: сборка её вырезает.
- wanakana@5.3.1 (jsdelivr) для ромадзи → кана.
- Карточки: SRS как в Anki — шаги изучения [1, 10] мин, переучивание [10] мин, выпуск 1 день,
  «Легко» 4 дня, лёгкость 2.5, смена дня в 4:00; новые чередуются между колодами пропорционально
  лимитам; вторая сторона карточки появляется только после выпуска первой. Прогресс на сайте —
  в localStorage (`shoho.*`), экспорт/импорт в файл; в артефакте — в db (`data/users/<id>/srs`, `{json: string}`).
- Микрофон (кнопка «Говорить» в «Скажи» и «Собеседнике», функция `micButton`): два способа —
  `SpeechRecognition` браузера и Whisper в браузере (`@huggingface/transformers@4.3.1`,
  `onnx-community/whisper-base`, encoder fp32 + decoder q4, WebGPU → wasm, ≈120 МБ один раз).
  На iPad распознавание Safari/Chrome давало `service-not-allowed` (выключены Siri/диктовка) —
  тогда кнопка сама переключается на Whisper. Выбор в «Настройках», ключ `shoho.mic`.
- Claude (проверка перевода в «Скажи» и «Собеседник»):
  - в артефакте claude.ai — через `window.claude.use('sample')`, ключ не нужен;
  - на сайте — через посредника: `PROXY_URL = 'https://shoho-claude.vioriahh.workers.dev'`,
    SDK `@anthropic-ai/sdk@0.133.0` из jsdelivr, заголовок `x-access-code` с кодом из «Настроек»
    (`shoho.code`); ссылка `?code=…` сохраняет код и убирает его из адреса;
  - если `PROXY_URL` пуст — посетитель вводит свой ключ Anthropic API (`shoho.key`).
  - Ответы строго в JSON (`output_config.format` json_schema): `CHECK_SCHEMA`, `CHAT_SCHEMA`.
- Артефакт: https://claude.ai/artifact/KFugmLbeZRYQyeFzP2FKXf (capabilities sample, db, user, downloads).
  Публикуется только из облачной сессии с инструментом Artifact; из терминала его не обновить.

## Посредник (`worker/worker.js`)

Развёрнут пользователем вручную через сайт Cloudflare (вставкой кода в Edit code), а не через wrangler.
Любое изменение `worker.js` пользователь должен снова вставить и нажать Deploy.

- Адрес: https://shoho-claude.vioriahh.workers.dev (открытие в браузере даёт «Нет такого адреса» — это норма).
- Переменные: секреты `API_KEY`, `ACCESS_CODE`; `UPSTREAM = https://suanzhou.top`.
- Ключ не от Anthropic: сервис 算舟云 suanzhou.top на движке new-api (перепродавец). Поэтому
  посредник шлёт ключ и в `x-api-key`, и в `Authorization: Bearer`, а `fallbacks` и beta-заголовок
  добавляет только для официального `https://api.anthropic.com`.
- Sonnet 5.5 у сервиса нет. Пользователю сказано скопировать точное имя Sonnet 5 с карточки модели
  (вероятно `claude-sonnet-5`) в переменную `MODEL`. Без неё посредник шлёт `claude-sonnet-5-5`.
- Посредник сам ставит модель, потолок `max_tokens` (8000), пропускает только `messages` и
  `output_config`, принимает запросы только с `https://vioriah.github.io`; 401/403 от API отдаёт как 502.

## Сайт

https://vioriah.github.io/-/ — GitHub Pages, источник «GitHub Actions». Сборка запускается сама
при пуше. Для ручной пересборки — Actions → «Сайт тренажёра» → Run workflow. Кнопку «Re-run jobs»
на старых запусках не нажимать: падает с `Multiple artifacts named "github-pages"` и к тому же
выложила бы старый коммит. Сайт бессрочный, пока репозиторий публичный.

## Открытые вопросы (на момент передачи)

1. Пользователь ещё не подтвердил, что задал `MODEL` в Cloudflare и что «Собеседник» отвечает.
   Если сервис не понимает `output_config.format`, «Собеседник» покажет «Ответ пришёл в неожиданном
   виде» — тогда перейти на JSON по инструкции в промпте без `output_config.format` (и разбирать
   ответ терпимее). Ошибки сервиса видны в Cloudflare: воркер → Observability → Logs.
2. Whisper на iPad не проверен на реальном устройстве (в облаке были закрыты jsdelivr и huggingface;
   проверена только цепочка с подставной моделью).
3. Ключ API пользователь дважды присылал в чат — рекомендовано заменить его на новый в кабинете
   suanzhou.top и обновить секрет `API_KEY`.
4. Необязательно: привязка Rate limiting `LIMITER` в Cloudflare (в `wrangler.toml` уже описана).
5. Синхронизация прогресса через db в артефакте и вызовы `sample` вживую не проверялись.

## Как проверять изменения

- Тренажёр: `python tools/build_trainer.py`, затем открыть `trainer/index.html` в браузере или
  прогнать Playwright. Внешние CDN (jsdelivr, huggingface) в тестах удобно подменять через `page.route`.
- Посредник: `worker.fetch(new Request(...), env)` вызывается прямо из Node 22 (есть `Request`/`Response`);
  `fetch` для upstream можно подменить.
- Не коммитить ключи: репозиторий публичный. Перед коммитом — `grep -rn "sk-" --exclude-dir=.git .`.

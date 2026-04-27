# Установка

## Предпосылки

- **Node.js.** Нужен для `statusline.js` (строка статуса в Claude Code) и для `code-transfer` (если используешь двухмашинный воркфлоу).

## Структура архива

```
claude-setup-share/
├── README.md              # главный гайд по сетапу — читать первым
├── INSTALL.md             # этот файл
└── home-claude/           # содержимое для ~/.claude/
    ├── CLAUDE.md.example
    ├── settings.json.example
    ├── statusline.js
    ├── workitems-rendering.md   # shared rules для /morning, /tasks, /my-reviews, /feedback
    ├── agents/
    └── commands/
```

> Тулза двухмашинного sync'а — `code-transfer` — теперь живёт отдельной репой: [RunkerTNF/code-transfer](https://github.com/RunkerTNF/code-transfer).

## Шаги

### 1. Скопировать содержимое `home-claude/` в `~/.claude/`

Linux/macOS:

```bash
cp -rn home-claude/agents ~/.claude/
cp -rn home-claude/commands ~/.claude/
cp -n home-claude/statusline.js ~/.claude/
cp -n home-claude/workitems-rendering.md ~/.claude/
```

Windows (Git Bash):

```bash
cp -rn home-claude/agents /c/Users/<USER>/.claude/
cp -rn home-claude/commands /c/Users/<USER>/.claude/
cp -n home-claude/statusline.js /c/Users/<USER>/.claude/
cp -n home-claude/workitems-rendering.md /c/Users/<USER>/.claude/
```

Флаг `-n` / `-rn` — «не перезаписывать существующие». Если у вас там уже что-то лежит — эти файлы не затрутся, разруливать руками.

`workitems-rendering.md` — это shared rendering-rules, на которые ссылаются workitems-команды (`/morning`, `/tasks`, `/my-reviews`, `/feedback`). Должен лежать прямо в `~/.claude/`, иначе команды не найдут правила и будут жаловаться.

### 2. Положить `CLAUDE.md` — переработать под себя

```bash
cp home-claude/CLAUDE.md.example ~/.claude/CLAUDE.md
```

**Обязательно отредактируйте.** Там прибито гвоздями:

- Двухмашинный workflow (домашний ПК + корп-ноут) и описание `code-transfer` — если у вас одна машина, убирайте весь блок про неё.
- Пути типа `C:\Users\Runker\sync-projects\...` — поменять на свои или удалить.
- Правила `.syncprotect` — убирать, если не используете `code-transfer`.
- Раздел про Windows / Git Bash — оставить, если у вас тоже Windows; иначе удалить.

Что **точно оставить**, иначе ломается workflow:

- Блок `Shared Claude tooling in ~/.claude/` (описание сабагентов и слэш-команд).
- Блок `Default review workflow` — это основа для автоматического вызова `plan-reviewer` / `code-reviewer`.
- Блок `Claude Code harness quirks` (короткая заметка про `settings.local.json`).

### 3. Настройка пермишенов

Концептуально про систему пермишенов и про то, **как тюнить allow-list по мере доверия к Claude**, написано в [README.md разделе 12](README.md). Ниже только техника.

Claude хранит пермишены в двух файлах в каждой директории `.claude/`:

| Файл | Что внутри |
|---|---|
| `settings.json` | **Курируется руками.** Долгоживущие разрешения (и запреты), которые ты осознанно добавил. |
| `settings.local.json` | **Авто-генерируется.** Сюда Claude сам пишет one-shot allow'ы, когда ты на prompt'е жмёшь «Always allow». Локальный мусорник, в гит не коммитить. |

Эта пара живёт на двух уровнях:

- **Глобальный:** `~/.claude/settings.json` (применяется всегда).
- **Проектный:** `<repo>/.claude/settings.json` (применяется только в этом проекте, имеет приоритет над глобальным).

Базовый синтаксис `settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(git status:*)",
      "Bash(ls:*)"
    ],
    "deny": [
      "Bash(rm -rf *)"
    ]
  }
}
```

- `Bash(<команда>:*)` — разрешить любой вариант `<команда> ...` без prompt'а.
- Узкие паттерны лучше широких. Никаких `Bash(*)`.
- `deny` — жёсткий запрет, побеждает `allow` при конфликте.

В архиве есть `home-claude/settings.json.example` — можно скопировать как стартовый набор глобальных пермишенов:

```bash
cp home-claude/settings.json.example ~/.claude/settings.json
```

Содержит безопасные read-only паттерны (`ls`, `stat`, `git status`, `git diff`, `git log`, ...) и моё личное предпочтение `effortLevel: xhigh` (можно убрать, если не нужно).

Поле `"autoMemoryDirectory": "~/.claude/memory"` указывает на единое место под глобальную память (см. [README раздел 2](README.md)) — без этого поля Claude свалится на дефолтный slug-based путь `~/.claude/projects/<encoded-cwd>/memory/`, который ломается при переезде/переименовании проектов.

**Не забудьте** в `home-claude/settings.json.example` поправить путь к `statusline.js`: там placeholder `/c/Users/<USER>/.claude/statusline.js`. Замените `<USER>` на свой логин; для Linux/macOS — `/home/<USER>/.claude/statusline.js`. Tilde `~` в этом поле может не разворачиваться — лучше абсолютный путь.

### 4. Плагины (опционально)

В `home-claude/settings.json.example` указаны два плагина:

- **`context7@claude-plugins-official`** — актуальная документация библиотек, чтобы Claude не галлюцинировал API по устаревшему тренинг-дата.
- **`superpowers@claude-plugins-official`** — набор продвинутых скиллов: `brainstorming`, `writing-plans`, `executing-plans`, `systematic-debugging`, `fewer-permission-prompts` и другие.

Оба — из дефолтного `claude-plugins-official` marketplace, доступного из коробки. Если у вас старый Claude Code и эти плагины не находятся — обновите Claude или удалите блок `enabledPlugins` из `settings.json`. При первом старте Claude предложит скачать включённые плагины — соглашайтесь.

### 5. Проверка

Запустите Claude Code в любой тестовой директории и проверьте, что команды доступны:

```
/init-claude
```

Если команда нашлась и начала работать — всё ок.

## Использование в новом проекте

```bash
cd /path/to/new/project
claude
```

В первой сессии:

```
/init-claude
```

Создаст локальный `CLAUDE.md` + `.claude/memory/` + `.claude/sessions/` + `.claude/settings.json`. `CLAUDE.md` он заполнит частично — то, что можно автоматически вытащить из `pyproject.toml` / `package.json` / `go.mod` и т.п. (имя проекта, рантайм, точки входа, env-переменные). А вот блоки уровня архитектуры там останутся как `TODO`-плейсхолдеры (data flow, entity relationships, public vs internal interfaces, consistency guarantees) — `/init-claude` намеренно их не угадывает.

**Сразу после `/init-claude`, не закрывая сессию, продолжите общение** и попросите Claude пройтись по этим `TODO` вместе с вами. Что-то типа: «прочитай главные файлы из X/Y/Z, поковыряй структуру и заполни оставшиеся `TODO`-секции в `CLAUDE.md`». Он покопается в коде, предложит черновик заполнения — вы по ходу поправите неточности. Это самый дешёвый момент чтобы получить хороший `CLAUDE.md`: вы уже в контексте проекта, Claude уже читает файлы, а потраченные 15 минут диалога окупятся на каждой следующей сессии (Claude не будет читать пол-репо в начале каждой задачи).

В конце сессии:

```
/wrap
```

Через несколько сессий, когда накопились session notes:

```
/backlog
```

Старт работы над беклог-айтемом:

```
/pick <id>
```

## `code-transfer` (опционально)

Если у вас, как у меня, домашний ПК с Claude Code и корп-ноут без него — есть смысл поднять `code-transfer`. Зачем оно, концептуально и с примерами цикла push/pull — в [README.md разделах 5 и 6](README.md). Сама тулза и технические шаги (поднять сервер, скачать CLI, прописать `~/.syncrc`) — в отдельной репе [RunkerTNF/code-transfer](https://github.com/RunkerTNF/code-transfer).

## Note: путь `sync-projects` в `init-claude.md`

Слэш-команда `/init-claude` определяет «sync-project» по жёстко прописанному пути `C:\Users\Runker\sync-projects\` (внутри файла [home-claude/commands/init-claude.md](home-claude/commands/init-claude.md), Step 1). Если используете `code-transfer` и ваш local projects-dir отличается — отредактируйте этот check у себя в `~/.claude/commands/init-claude.md`. Если `code-transfer` не используете — на скрипт это не влияет, он просто всегда будет считать `is_sync_project = false`.

## Траблшутинг

- **Слэш-команды не находятся.** Проверь, что `.md`-файлы лежат в `~/.claude/commands/` (а не в подпапке) и у них есть frontmatter с `description:`.
- **Сабагенты не вызываются автоматически.** Убедись, что в глобальном `CLAUDE.md` есть секция `Default review workflow`, а файлы лежат в `~/.claude/agents/`.
- **`statusline.js` не работает.** Путь в `settings.json` должен быть абсолютным и указывать на твоего пользователя. На Windows — `/c/Users/<USER>/.claude/statusline.js`.
- **`/init-claude` ругается на отсутствие директории.** Запускай из корня проекта (там, где `pyproject.toml` / `package.json` / `.git`).
- **На каждое действие выскакивает prompt.** См. README раздел 12 («Тюнинг пермишенов на доверии») и шаг 3 здесь.

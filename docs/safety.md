# Safety и trust boundary

Agent Workflow проектируется как local, preview-first manager. Он не делает
network requests и не считает найденный агент согласием на запись.

## Preview и no-clobber

Detection и scan read-only. Setup/migration сначала создают materialized JSON
plan с exact roots, operations, expected hashes, warnings и conflicts.

No-clobber rules:

- unmanaged non-empty destination блокирует запись;
- managed file с drift блокирует перезапись или удаление;
- symlinked/escaping path отклоняется;
- apply повторно проверяет plan ID, roots и source hashes;
- изменившийся после preview source делает plan stale.

Не редактируйте plan или hashes вручную. Изменили требования — создайте новый
preview и получите новое подтверждение.

## Transactions, backups и rollback

Apply:

1. получает scope lock;
2. проверяет все sources и destinations;
3. создаёт verified backup;
4. готовит files в staging;
5. публикует journal;
6. выполняет atomic replace/delete;
7. фиксирует committed status.

При сбое manager пытается восстановить backup. Journal и backup нельзя
редактировать. Restore:

```text
MANAGER rollback JOURNAL_PATH
```

Rollback также проверяет hashes и не затирает последующие изменения.

## Credentials и privacy

Credentials не мигрируют. API keys, bearer tokens, cookies, passwords, private
keys и auth headers получают `sensitive_skip` или redaction. В plan не должно
быть credential value.

Для hosted-agent classification отправляйте только user-reviewed
`request.json`. Не отправляйте raw settings, inventory, backups, journals или
native cache. Private absolute paths и credential-like values редактируются,
text preview ограничен размером.

## External adapters

Declarative adapter может читать только свой validated package и создавать
операции в разрешённых roots. Package с `adapter.py` не исполняется без:

```text
--adapter-dir PATH --trust-adapter-code ID
```

Explicit trust означает разрешение выполнить локальный Python-код package.
Перед trust прочитайте код и зависимости. Manager ничего не скачивает сам.

## Native replacement

Migration сохраняет legacy source по умолчанию. `--replace-native` — отдельный
destructive opt-in, который допустим только после успешного neutral import.
Удаляются только fully migrated artifacts с exact hash. Unsupported,
sensitive и conflicting files сохраняются.

Не удаляйте `.claude`, `.codex`, home или project root целиком: manager может
владеть лишь несколькими файлами внутри.

## Sharing

`shared` и `split` profiles управляют ignore policy, а не secrecy. Перед commit
проверяйте manual memory, sessions, adapter settings и generated entrypoints.
`.syncprotect` не заменяет `.gitignore` и наоборот.

Optional personal examples не устанавливаются по умолчанию. Перед копированием
замените placeholders и убедитесь, что topology не раскрывает private paths.

Recovery по типовым ошибкам: [troubleshooting](troubleshooting.md).

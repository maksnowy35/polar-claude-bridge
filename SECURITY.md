# Bezpieczeństwo

Repo jest publiczne, a projekt dotyczy danych o zdrowiu. Zasada jest jedna: **w gicie jest tylko kod**.

## Co jest w repo, a czego nie ma

| w repo | poza repo |
|---|---|
| kod (`healthctx/`, `tools/`, `test_files/`) | surowe dane z Polara, dziennik, wyniki badań |
| dane syntetyczne (`tests/make_fixtures.py`, `database/public/`) | `.env` z kluczami |
| szablony (`templates/`) | lokalna baza `health.db`, wygenerowane pliki kontekstu |

## Gdzie są dane

- **Neon (Postgres, Frankfurt)**: `facts`, `daily_metrics`, `training_sessions`, `journal_entries`.
- **Google Drive**: folder aplikacji (`GDRIVE_FOLDER_ID`) z plikami kontekstu oraz `raw/` i `confidential/`. Scope `drive.file`, więc aplikacja nie widzi reszty Dysku.
- **Lokalnie**: `database/private/` i `database/confidential/`, oba w `.gitignore`.

## Klucze

Lokalnie trzymam je w `.env`, w CI w GitHub Secrets:

| sekret | do czego |
|---|---|
| `DATABASE_URL` | Neon, connection string bez `-pooler` |
| `POLAR_ACCESS_TOKEN` | AccessLink, z `test_files/auth_script.py` |
| `GDRIVE_FOLDER_ID`, `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN` | Google Drive |

`POLAR_CLIENT_ID`, `POLAR_CLIENT_SECRET` i `POLAR_USER_ID` są potrzebne tylko lokalnie, do autoryzacji i serwera MCP.

## Rotacja

- **Polar**: odłącz aplikację w Polar Flow (Ustawienia → Partnerzy), co unieważnia token. W admin.polaraccesslink.com wygeneruj nowy client secret i uruchom ponownie `test_files/auth_script.py`.
- **Google**: odbierz dostęp na myaccount.google.com/permissions, zresetuj client secret w Cloud Console i wygeneruj nowy refresh token (README, sekcja Google Drive).
- **Neon**: zresetuj hasło roli w konsoli i podmień `DATABASE_URL` w `.env` i w Secrets.

Po każdym wycieku najpierw rotacja, potem sprzątanie historii. Commit usunięty z historii nadal może być dostępny pod swoim SHA.

## Zabezpieczenia w repo

- Hook pre-commit: `git config core.hooksPath .githooks` (raz na klon). Blokuje pliki z `database/private` i `database/confidential`, `.env`, pliki bazy, JSON-y Polara poza `database/public` i `tests/` oraz klucze wpisane w kod.
- CI (`ci.yml`) uruchamia ten sam skan na całym repo przy każdym pushu.
- `daily.yml` loguje tylko liczniki, daty i nazwy plików. Nie dodawaj kroków, które wypisują pliki kontekstu albo wyniki zapytań, bo logi publicznego repo są publiczne.

## Zgłaszanie problemów

Jeśli coś wygląda na wyciek, nie opisuj tego w publicznym issue. Użyj Security → Report a vulnerability na GitHubie.

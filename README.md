# polar-claude-bridge

Pipeline, który zamienia dane z zegarka Polar (eksport z Polar Flow i AccessLink API v3), dziennik i wyniki badań w bazę danych oraz mały zestaw plików kontekstu dla asystenta AI. Asystent czyta `status.md` (~1,5k tokenów) albo widok SQL zamiast surowych JSON-ów, których jest kilkaset MB na rok.

## Architektura

```
 Polar Flow export ─┐
 AccessLink API ────┼─► raw JSON ──► parsers ──► facts ──► aggregate ──► daily_metrics ──► context files
 journal CSV / SQL ─┘   (Drive)      (export,     (DB)      (baselines,    training_sessions   (status.md,
                                      api)                   flags)        (DB)                 days/, CSV)
```

- **Import** jest idempotentny: plik z tym samym sha1 nie jest parsowany drugi raz, a fakt z niezmienionym payloadem nie oznacza dnia jako zmienionego.
- **Build** jest przyrostowy: przelicza dni od pierwszego zmienionego, a z wcześniejszych bierze tylko historię potrzebną do linii bazowych (28 i 60 dni).
- **Baza:** Postgres na Neon w produkcji, SQLite lokalnie i w testach. Ten sam kod, różnią się tylko migracje. Uzasadnienie jest w [docs/adr/001-database.md](docs/adr/001-database.md).

## Struktura repo

| ścieżka | co to |
|---|---|
| `healthctx/parsers/` | rozpoznawanie i parsowanie plików eksportu i odpowiedzi API (po zawartości, nie po nazwie) |
| `healthctx/aggregate.py` | rekordy dzienne, linie bazowe, flagi |
| `healthctx/db.py`, `repository.py`, `migrations/` | dostęp do bazy (SQLite/Postgres) i schemat |
| `healthctx/pipeline.py`, `cli.py` | import, build, CLI |
| `healthctx/render.py` | pliki kontekstu |
| `database/` | dane podzielone na `public/`, `private/` i `confidential/`, patrz [database/README.md](database/README.md) |
| `tests/` | testy jednostkowe, test całego pipeline'u (SQLite, opcjonalnie Postgres), generator danych syntetycznych |
| `templates/` | wzory dziennika i plików medycznych |
| `test_files/` | lokalny serwer MCP i autoryzacja OAuth Polara |

## Uruchomienie

```bash
pip install -r requirements.txt
cp .env.example .env                  # DATABASE_URL puste = lokalny SQLite w database/private/health.db
python -m healthctx run               # fetch (jeśli jest POLAR_ACCESS_TOKEN) + migrate + import + build
python -m healthctx fetch --days 7    # tylko pobranie z AccessLink do database/private/raw/api/
python -m healthctx push-context      # zmienione pliki kontekstu na Dysk Google
python -m healthctx pull-raw --with-confidential   # odtworzenie archiwum z Dysku (np. na runnerze CI)
python -m healthctx build --full      # przeliczenie wszystkiego od zera
python -m unittest discover -s tests -t .
```

Test na Postgresie uruchamia się tylko z `TEST_DATABASE_URL`, a nazwa bazy musi zawierać `test`, bo test czyści schemat.

Fetch zapisuje każdy element (noc, trening, dzień aktywności) jako osobny plik z datą w nazwie. Ponowne uruchomienie nadpisuje te same pliki, a import pomija niezmienione. Zakres dat dla aktywności i tętna 24/7 jest ograniczony do 28 dni, bo tyle przyjmuje AccessLink. Nieudany fetch (np. 401 po odebraniu zgody) nie zatrzymuje buildu z danych, które już są, tylko kończy `run` kodem 1.

## Neon: konfiguracja

1. Na neon.tech załóż projekt w regionie **AWS Europe Central (Frankfurt)**.
2. Skopiuj connection string **bez** `-pooler` w nazwie hosta. psycopg używa prepared statements, a pooler Neona działa w trybie transakcyjnym PgBouncera, który ich nie obsługuje.
3. Wpisz go do `.env`:
   ```
   DATABASE_URL=postgresql://<user>:<password>@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```
4. Uruchom:
   ```bash
   python -m healthctx migrate
   python -m healthctx db-check     # host, wersja schematu, liczba wierszy; bez wartości zdrowotnych
   ```
5. Na GitHubie: Settings → Secrets and variables → Actions → `DATABASE_URL`.
6. Opcjonalnie podłącz konektor Neon w claude.ai. Wtedy asystent czyta widoki `v_daily_last_30`, `v_flagged_days` i `v_monthly` oraz dopisuje do `journal_entries`.

## Google Drive: konfiguracja

1. W Google Cloud Console załóż projekt i włącz **Google Drive API**.
2. Na ekranie zgody OAuth wybierz typ External, dodaj scope `https://www.googleapis.com/auth/drive.file`, a potem **opublikuj aplikację** (status „In production”). W trybie Testing refresh token wygasa po 7 dniach. `drive.file` nie wymaga weryfikacji przez Google.
3. W Credentials utwórz OAuth client ID typu **Web application** z redirect URI `https://developers.google.com/oauthplayground`. Client ID i secret wpisz do `.env`.
4. Refresh token: w [OAuth 2.0 Playground](https://developers.google.com/oauthplayground) włącz „Use your own OAuth credentials”, autoryzuj scope `drive.file`, kliknij „Exchange authorization code for tokens” i skopiuj refresh token do `GDRIVE_REFRESH_TOKEN`.
5. `python -m healthctx push-context --dry-run`, a potem bez `--dry-run`. Przy pierwszym prawdziwym uruchomieniu na Moim dysku powstaje folder `polar-claude-bridge`, a jego id pojawia się w logu. Wpisz je do `GDRIVE_FOLDER_ID`.
6. Te same cztery zmienne dodaj w GitHub Secrets.

Ze scope `drive.file` aplikacja widzi tylko pliki, które sama utworzyła, więc nie ma dostępu do reszty Dysku. Konektor Drive w claude.ai działa na Twoim koncie, więc czyta te pliki normalnie.

## Pliki kontekstu (`database/private/context/`)

| plik | rozmiar | do czego |
|---|---|---|
| `status.md` | ~1–1,5k tokenów | zawsze pierwszy: profil, linie bazowe z 60 dni, trend 7 vs 28 dni, ostatnie 14 dni, obciążenie, flagi, dziennik, leki |
| `days/day_RRRR-MM-DD.md` | ~0,5k | noc (hipnogram, HR, HRV, oddech, temp. skóry), wieczór przed snem, treningi z HR co 5 min |
| `daily/`, `sessions/` | ~0,8k / ~0,3k na miesiąc | 1 wiersz na dzień / na trening |
| `monthly.csv`, `INDEX.md` | małe | trendy długoterminowe, legenda kolumn i flag |

`.changed.txt` zawiera listę plików zmienionych w ostatnim buildzie, czyli to, co trzeba wysłać na Dysk.

## Obsługiwane dane

| źródło | eksport Flow | API v3 |
|---|---|---|
| aktywność dzienna | `activity-*.json` | `/v3/users/activities` |
| tętno 24/7 | `247ohr_*.json` | `/v3/users/continuous-heart-rate` |
| temperatura skóry | `generic-period` (TM_SKIN_TEMPERATURE) | biosensing (parser tolerancyjny) |
| treningi | `training-session*.json` | `/v3/exercises` z `samples` i `zones` |
| sen | tylko czas snu z pliku aktywności (brak próbki pliku snu) | `/v3/users/sleep` |
| Nightly Recharge | brak próbki | `/v3/users/nightly-recharge` |
| cardio load | — | `/v3/users/cardio-load` |

Parsery API są napisane według dokumentacji AccessLink i sprawdzone na danych syntetycznych.

## Dziennik

Tabela `journal_entries` jest źródłem prawdy: wpisy można dodawać SQL-em albo importować z `database/confidential/journal/log.csv` (`date,time,type,item,value,unit,note`). Typy: `supp, med, symptom, mood, energy, stress, alcohol, caffeine, illness, rpe, weight, note`. Skala nastroju, energii i stresu to 1–10.

## Konfiguracja

Zmienne środowiskowe są w `.env.example`. `sports.json` mapuje numer sportu z eksportu na nazwę, a progi flag są w `healthctx/aggregate.py`.

## Zasady

- Noc (sen, Nightly Recharge, tętno spoczynkowe, temp. skóry) należy do daty przebudzenia.
- Repo jest publiczne: w gicie jest tylko kod i dane syntetyczne. Klucze trzymam w `.env` i GitHub Secrets.
- Po sklonowaniu włącz hook: `git config core.hooksPath .githooks`. Strażnik (`tools/check_sensitive.py`) blokuje commit z plikami z `database/private` i `database/confidential`, `.env`, plikami bazy, JSON-ami Polara poza `database/public` i `tests/` oraz kluczami wpisanymi w kod. `python tools/check_sensitive.py --all` sprawdza całe repo.

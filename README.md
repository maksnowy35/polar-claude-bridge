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
python -m healthctx run               # migrate + import + build
python -m healthctx build --full      # przeliczenie wszystkiego od zera
python -m unittest discover -s tests -t .
```

Test na Postgresie uruchamia się tylko z `TEST_DATABASE_URL`, a nazwa bazy musi zawierać `test`, bo test czyści schemat.

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

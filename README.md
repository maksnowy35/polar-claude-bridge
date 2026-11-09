# claude_health

Silnik danych zdrowotnych dla Claude. Zamienia surowe dane z Polara (eksport z Polar Flow **i** odpowiedzi AccessLink API v3) w mały zestaw plików, które Claude czyta zamiast surowych JSON-ów. Tylko biblioteka standardowa Pythona (3.10+), bez instalacji pakietów.

## Struktura repo

| ścieżka | co to |
|---|---|
| `healthctx/` | parsery (`parsers/export.py`, `parsers/api.py`), agregacja z flagami, dziennik, renderowanie plików |
| `run.py` | CLI: surowe dane → pliki kontekstu |
| `tests/` | testy parserów i generator syntetycznych danych API |
| `templates/` | wzory `journal/log.csv`, `medical/timeline.md`, `medical/labs.csv` |
| `test_files/` | lokalny serwer MCP (`polar_mcp_server.py`) i autoryzacja OAuth (`auth_script.py`) |
| `.env.example` | zmienne na klucze Polara i folder Dysku; prawdziwe wartości tylko w `.env` |

## Uruchomienie

```bash
python run.py --raw data/raw --out data/out \
              --journal data/journal/log.csv --medical data/medical
python tests/test_parsers.py          # szybki test parserów
python tests/make_fixtures.py /tmp/fx # syntetyczne dane API do testu całości
```

`--raw` może zawierać dowolne podfoldery i nazwy plików. Typ danych jest rozpoznawany po zawartości, a nie po nazwie. Wyniki parsowania są cache'owane per plik (`<out>/.cache`), więc codzienny przebieg parsuje tylko nowe pliki. `<out>/.changed.txt` zawiera listę plików, które się zmieniły (do wysyłki na Dysk).

## Co powstaje

| plik | rozmiar | do czego |
|---|---|---|
| `status.md` | ~1–1,5k tokenów | czytany zawsze pierwszy: profil, linie bazowe z 60 dni, trend 7 vs 28 dni, tabela 14 dni, obciążenie tygodniowe, flagi, dziennik, leki |
| `days/day_RRRR-MM-DD.md` | ~0,5k | szczegóły dnia: hipnogram, HR/HRV/oddech w nocy, temp. skóry, wieczór przed snem, treningi z profilem HR co 5 min |
| `daily/daily_RRRR-MM.csv` | ~0,8k/mies. | 1 wiersz na dzień |
| `sessions/sessions_RRRR-MM.csv` | ~0,3k/mies. | 1 wiersz na trening (minuty w strefach, cardio load) |
| `monthly.csv` | <0,1k/mies. | trendy długoterminowe |
| `INDEX.md` | ~1k | legenda kolumn, flag i kolejność czytania |

## Obsługiwane dane

| źródło | eksport Flow | API v3 |
|---|---|---|
| aktywność dzienna (kroki, MET, poziomy) | `activity-*.json` ✔ | `/v3/users/activities` ✔ |
| tętno 24/7 | `247ohr_*.json` ✔ | `/v3/users/continuous-heart-rate` ✔ |
| temperatura skóry | `generic-period` (TM_SKIN_TEMPERATURE) ✔ | biosensing: parser tolerancyjny |
| treningi | `training-session*.json` ✔ | `/v3/exercises` (z `samples`, `zones`) ✔ |
| sen (fazy, wynik, hipnogram) | **brak próbki** (na razie tylko czas snu z pliku aktywności) | `/v3/users/sleep` ✔ |
| Nightly Recharge (ANS, HRV, oddech) | **brak próbki** | `/v3/users/nightly-recharge` ✔ |
| cardio load (status, strain, tolerance) | — | `/v3/users/cardio-load` ✔ |
| profil, progi HR, test fitness | ✔ (bez imienia i e-maila) | — |

Parsery API są napisane według dokumentacji AccessLink i przetestowane na danych syntetycznych, nie na Twoich.

## Dziennik (`journal/log.csv`)

`date,time,type,item,value,unit,note`. Typy: `supp, med, symptom, mood, energy, stress, alcohol, caffeine, illness, rpe, weight, note`. Nastrój, energia i stres w skali 1–10. Wzór jest w `templates/journal/log.csv`.

## Konfiguracja

`sports.json` mapuje numer sportu z eksportu na nazwę, np. `"204": "tenis"`. Progi flag są w `healthctx/aggregate.py`.

## Zasady

- Noc (sen, Nightly Recharge, tętno spoczynkowe, temp. skóry) należy do daty przebudzenia.
- Do repozytorium trafia tylko kod. `data/`, `.cache/` i `.env` są w `.gitignore`.

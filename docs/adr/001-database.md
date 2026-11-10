# ADR 001: Baza danych dla historii zdrowotnej

Status: przyjęte, 2026-11-09

## Kontekst

- Dane: rok to ok. 1000 plików JSON z Polara (~200 MB surowo), dziennik (1–2 tys. wpisów), wyniki badań.
- Pipeline działa codziennie na GitHub Actions. Runner jest jednorazowy, więc historia musi żyć poza nim.
- Odczyt: asystent AI na telefonie i na laptopie. Nie może czytać surowych danych, bo rok to ~1,6 mln tokenów.
- Repo jest publiczne, a dane to dane o zdrowiu: nic nie może trafić do gita, klucze tylko w secrets.
- Budżet: 0 zł.

## Rozważane opcje

| opcja | plusy | minusy |
|---|---|---|
| pliki na Google Drive (CSV/JSON) | już podpięte do asystenta, darmowe | brak zapytań, każdy run ściąga i nadpisuje całość, konflikty przy dwóch pisarzach |
| SQLite / DuckDB jako plik na Drive | SQL, szybkie analizy | plik trzeba pobrać i odesłać w całości, jeden pisarz naraz |
| Supabase (Postgres) | Postgres + storage + konektor | free: 500 MB, projekt pauzuje po 7 dniach bez ruchu |
| **Neon (Postgres)** | free: 1 GB na projekt, region Frankfurt, scale-to-zero zamiast pauzowania, oficjalny konektor dla asystenta | jeden więcej serwis do utrzymania |

## Decyzja

- **Neon Postgres** (region AWS eu-central-1) na dane ustrukturyzowane: `facts`, `daily_metrics`, `training_sessions`, `journal_entries` oraz widoki `v_daily_last_30`, `v_flagged_days` i `v_monthly`.
- **Google Drive** na archiwum surowych JSON-ów i gotowe pliki kontekstu. Asystent czyta je przez konektor Drive, a w razie potrzeby pliki da się przetworzyć od nowa.
- **SQLite** lokalnie i w testach, z tym samym kodem dostępu do bazy (`healthctx/db.py`).

## Szacunek obciążenia

- `facts`: ~2 tys. wierszy na rok. Krzywe HR i temperatury są trzymane jako tablica 288 wartości (co 5 min) w jednym wierszu na dzień, a nie 288 wierszy. Razem ok. 6–8 MB na rok.
- `daily_metrics`: 365 wierszy na rok, `training_sessions`: ~250, `journal_entries`: ~1500.
- Razem poniżej 20 MB na rok, więc limit 1 GB starczy na dekady. Codzienny build to kilka sekund CPU, czyli ułamek darmowych CU-godzin.

## Jak ograniczam koszt analizy

1. Liczę przy imporcie, nie przy pytaniu: linie bazowe, odchylenia i flagi są zapisane w `daily_metrics`.
2. Build jest przyrostowy: przelicza dni od pierwszej zmiany i ładuje tylko 100 dni historii, a nie cały rok.
3. Asystent dostaje gotowe przekroje: `status.md` (14 dni + linie bazowe), plik dnia albo widok SQL (≤ 30 wierszy). Do surowych danych nie sięga.
4. Import pomija pliki o tym samym sha1, a fakt z niezmienionym payloadem nie oznacza dnia jako zmienionego.

## Konsekwencje

- Utrzymuję dwa zestawy migracji (`migrations/postgres`, `migrations/sqlite`). Widoki istnieją tylko w Postgresie.
- Asystent przez konektor Neon działa z uprawnieniami konta. Jeśli kiedyś będzie dostęp przez sam connection string, to tylko przez rolę z `SELECT` i `INSERT` na `journal_entries`:

  ```sql
  CREATE ROLE health_reader LOGIN PASSWORD '...';
  GRANT USAGE ON SCHEMA public TO health_reader;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO health_reader;
  GRANT INSERT ON journal_entries TO health_reader;
  ```

- `DATABASE_URL` trzymam tylko w `.env` i GitHub Secrets. Workflow nie wypisuje danych do logów, bo przy publicznym repo logi Actions są publiczne.

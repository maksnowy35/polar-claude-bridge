-- Local/test schema. Keep in sync with migrations/postgres/001_init.sql (views are Postgres only).

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE raw_files (
    path        TEXT PRIMARY KEY,
    sha1        TEXT NOT NULL,
    size_bytes  BIGINT NOT NULL,
    fact_count  INTEGER NOT NULL,
    import_run  INTEGER NOT NULL
);

CREATE TABLE facts (
    kind        TEXT NOT NULL,
    fact_key    TEXT NOT NULL,
    source      TEXT NOT NULL,
    fact_date   DATE,
    payload     TEXT NOT NULL,
    import_run  INTEGER NOT NULL,
    PRIMARY KEY (kind, fact_key, source)
);
CREATE INDEX facts_fact_date_idx ON facts (fact_date);
CREATE INDEX facts_import_run_idx ON facts (import_run);

-- Column names match daily_YYYY-MM.csv, the legend is in INDEX.md.
CREATE TABLE daily_metrics (
    day        DATE PRIMARY KEY,
    sleep_on   TEXT,
    sleep_off  TEXT,
    sleep_h    REAL,
    bed_h      REAL,
    score      SMALLINT,
    s_dur      SMALLINT,
    s_sol      SMALLINT,
    s_reg      SMALLINT,
    deep_pct   SMALLINT,
    rem_pct    SMALLINT,
    intr_min   SMALLINT,
    cont       REAL,
    cycles     SMALLINT,
    charge     SMALLINT,
    nr         SMALLINT,
    ans        REAL,
    hrv        SMALLINT,
    br         REAL,
    hr_nr      SMALLINT,
    rhr        SMALLINT,
    hr_night   SMALLINT,
    skin_t     REAL,
    skin_dev   REAL,
    steps      INTEGER,
    kcal       INTEGER,
    met_min    INTEGER,
    mod_min    INTEGER,
    vig_min    INTEGER,
    sed_h      REAL,
    nonwear_h  REAL,
    sess       SMALLINT,
    train_min  INTEGER,
    load       INTEGER,
    load7      INTEGER,
    acwr       REAL,
    sports     TEXT,
    last_end   TEXT,
    wt         REAL,
    mood       REAL,
    energy     REAL,
    stress     REAL,
    alc        REAL,
    caf_last   TEXT,
    sym        TEXT,
    supp       TEXT,
    flags      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE training_sessions (
    session_key  TEXT PRIMARY KEY,
    day          DATE NOT NULL,
    start_time   TEXT NOT NULL,
    end_time     TEXT,
    sport        TEXT,
    dur_min      INTEGER,
    kcal         INTEGER,
    hr_avg       SMALLINT,
    hr_max       SMALLINT,
    hr_min       SMALLINT,
    zones_min    TEXT,
    cardio_load  INTEGER,
    cardio_int   TEXT,
    muscle_load  INTEGER,
    trimp        INTEGER,
    rpe          TEXT,
    recovery_h   REAL,
    dist_km      REAL
);
CREATE INDEX training_sessions_day_idx ON training_sessions (day);

CREATE TABLE journal_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         DATE NOT NULL,
    entry_time  TEXT NOT NULL DEFAULT '',
    entry_type  TEXT NOT NULL,
    item        TEXT NOT NULL DEFAULT '',
    value       TEXT,
    unit        TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (day, entry_time, entry_type, item)
);

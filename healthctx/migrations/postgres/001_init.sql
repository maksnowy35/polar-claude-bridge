CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Registry of imported raw files. sha1 decides if a file has to be parsed again,
-- mtime is useless on CI runners because every checkout touches all files.
CREATE TABLE raw_files (
    path        TEXT PRIMARY KEY,
    sha1        TEXT NOT NULL,
    size_bytes  BIGINT NOT NULL,
    fact_count  INTEGER NOT NULL,
    import_run  INTEGER NOT NULL
);

-- Parser output, one row per (kind, key, source). Export and API data for the same day
-- are kept side by side and merged at build time (export wins, API fills gaps).
CREATE TABLE facts (
    kind        TEXT NOT NULL,
    fact_key    TEXT NOT NULL,
    source      TEXT NOT NULL,
    fact_date   DATE,
    payload     JSONB NOT NULL,
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
COMMENT ON TABLE daily_metrics IS 'One row per day. Night metrics belong to the wake-up date. Legend: INDEX.md';

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

-- Source of truth for the manual journal. Rows can be added straight from SQL
-- (e.g. by Claude through the Neon connector), the CSV import is only a bulk path.
CREATE TABLE journal_entries (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    day         DATE NOT NULL,
    entry_time  TEXT NOT NULL DEFAULT '',
    entry_type  TEXT NOT NULL,
    item        TEXT NOT NULL DEFAULT '',
    value       TEXT,
    unit        TEXT,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (day, entry_time, entry_type, item)
);

CREATE VIEW v_daily_last_30 AS
SELECT *
FROM daily_metrics
WHERE day > (SELECT max(day) FROM daily_metrics) - 30
ORDER BY day;

CREATE VIEW v_flagged_days AS
SELECT day, flags, sleep_h, score, hrv, rhr, br, skin_dev, ans, sym, supp
FROM daily_metrics
WHERE flags <> ''
ORDER BY day DESC;

CREATE VIEW v_monthly AS
SELECT date_trunc('month', day)::date              AS month,
       count(*)                                    AS days,
       round(avg(sleep_h)::numeric, 2)             AS sleep_h,
       round(avg(score))                           AS score,
       round(avg(hrv))                             AS hrv,
       round(avg(rhr))                             AS rhr,
       round(avg(steps))                           AS steps,
       sum(sess)                                   AS sessions,
       round(sum(train_min) / 60.0, 1)             AS train_h,
       sum(load)                                   AS cardio_load,
       round(avg(mood)::numeric, 1)                AS mood,
       count(*) FILTER (WHERE flags <> '')         AS flag_days
FROM daily_metrics
GROUP BY 1
ORDER BY 1;

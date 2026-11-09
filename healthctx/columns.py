DAILY_COLS = ["date", "on", "off", "sleep_h", "bed_h", "score", "s_dur", "s_sol", "s_reg", "deep_pct", "rem_pct",
              "intr_min", "cont", "cycles", "charge", "nr", "ans", "hrv", "br", "hr_nr", "rhr", "hr_night",
              "skin_t", "skin_dev", "steps", "kcal", "met_min", "mod_min", "vig_min", "sed_h", "nonwear_h",
              "sess", "train_min", "load", "load7", "acwr", "sports", "last_end", "wt",
              "mood", "energy", "stress", "alc", "caf_last", "sym", "supp", "flags"]

SESSION_COLS = ["date", "start", "end", "sport", "dur_min", "kcal", "hr_avg", "hr_max", "hr_min", "zones_min",
                "cardio_load", "cardio_int", "muscle_load", "trimp", "rpe", "recovery_h", "dist_km"]

# CSV keeps the short names, in SQL "on"/"date"/"start"/"end" are reserved or ambiguous.
DAILY_DB_NAMES = {"date": "day", "on": "sleep_on", "off": "sleep_off"}
SESSION_DB_NAMES = {"date": "day", "start": "start_time", "end": "end_time"}

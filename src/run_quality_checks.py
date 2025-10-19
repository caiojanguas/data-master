import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

# --- Config & paths ---
from src.config import DB_PATH, OUTPUTS

# Thresholds opcionais: se não existir em config, usamos defaults
try:
    from src.config import QUALITY_THRESHOLDS  # type: ignore
except Exception:
    QUALITY_THRESHOLDS = {
        # nulos críticos (absoluto)
        "null_track_id": 0,
        "null_track_name": 0,
        "null_artists": 0,
        "null_duration_ms": 0,
        # faixas inválidas (absoluto)
        "bad_danceability": 0,
        "bad_energy": 0,
        "bad_speechiness": 0,
        "bad_acousticness": 0,
        "bad_instrumentalness": 0,
        "bad_liveness": 0,
        "bad_valence": 0,
        # duplicidades (absoluto)
        "dup_track_id": 0,
        "dup_fuzzy_key": 0,
        # popularidade esperada
        "pop_min_expected": 0,    # min >= 0
        "pop_max_expected": 100,  # max <= 100
    }

OUTPUTS.mkdir(parents=True, exist_ok=True)

# ------------------------
# Consultas base (mantidas)
# ------------------------
SQLS = {
    "row_count": """
        SELECT COUNT(*) AS row_count FROM staging.kaggle_tracks;
    """,
    "nulls_core": """
        SELECT
            SUM(track_id IS NULL)        AS null_track_id,
            SUM(track_name IS NULL)      AS null_track_name,
            SUM(artists IS NULL)         AS null_artists,
            SUM(duration_ms IS NULL)     AS null_duration_ms,
            SUM(popularity IS NULL)      AS null_popularity
        FROM staging.kaggle_tracks;
    """,
    "ranges_features_invalid": """
        SELECT
            SUM(danceability < 0 OR danceability > 1 OR danceability IS NULL) AS bad_danceability,
            SUM(energy < 0 OR energy > 1 OR energy IS NULL)                   AS bad_energy,
            SUM(speechiness < 0 OR speechiness > 1 OR speechiness IS NULL)    AS bad_speechiness,
            SUM(acousticness < 0 OR acousticness > 1 OR acousticness IS NULL) AS bad_acousticness,
            SUM(instrumentalness < 0 OR instrumentalness > 1 OR instrumentalness IS NULL) AS bad_instrumentalness,
            SUM(liveness < 0 OR liveness > 1 OR liveness IS NULL)             AS bad_liveness,
            SUM(valence < 0 OR valence > 1 OR valence IS NULL)                AS bad_valence
        FROM staging.kaggle_tracks;
    """,
    # TOP 50 detalhado (mantido p/ export)
    "dup_by_track_id": """
        SELECT track_id, COUNT(*) AS cnt
        FROM staging.kaggle_tracks
        WHERE track_id IS NOT NULL
        GROUP BY 1
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 50;
    """,
    # TOP 50 detalhado (mantido p/ export)
    "dup_by_fuzzy_key": """
        -- duplicidade aproximada: (track_name, artists, duration_ms)
        SELECT lower(track_name) AS track_name_l,
               lower(artists)    AS artists_l,
               duration_ms,
               COUNT(*) AS cnt
        FROM staging.kaggle_tracks
        GROUP BY 1,2,3
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 50;
    """,
    "popularity_stats": """
        SELECT
          MIN(popularity) AS min_pop,
          MAX(popularity) AS max_pop,
          AVG(popularity) AS avg_pop
        FROM staging.kaggle_tracks;
    """
}

# Contagens agregadas para thresholds (somente números)
SQLS_COUNTS = {
    "dup_track_id": """
        SELECT COUNT(*) AS dup_track_id FROM (
          SELECT track_id
          FROM staging.kaggle_tracks
          WHERE track_id IS NOT NULL
          GROUP BY 1
          HAVING COUNT(*) > 1
        );
    """,
    "dup_fuzzy_key": """
        SELECT COUNT(*) AS dup_fuzzy_key FROM (
          SELECT lower(track_name) AS track_name_l,
                 lower(artists)    AS artists_l,
                 duration_ms
          FROM staging.kaggle_tracks
          GROUP BY 1,2,3
          HAVING COUNT(*) > 1
        );
    """
}

SQLS_OFFENDERS = {
    "null_track_name_rows": """
      SELECT rowid, * FROM staging.kaggle_tracks
      WHERE track_name IS NULL OR trim(track_name) = ''
      ORDER BY rowid
    """,
    "null_artists_rows": """
      SELECT rowid, * FROM staging.kaggle_tracks
      WHERE artists IS NULL OR trim(artists) = ''
      ORDER BY rowid
    """,
    "dup_track_id_rows": """
      WITH d AS (
        SELECT track_id
        FROM staging.kaggle_tracks
        WHERE track_id IS NOT NULL AND trim(track_id) <> ''
        GROUP BY 1
        HAVING COUNT(*) > 1
      )
      SELECT t.* FROM staging.kaggle_tracks t
      JOIN d ON d.track_id = t.track_id
      ORDER BY t.track_id
    """,
    "dup_fuzzy_key_rows": """
      WITH d AS (
        SELECT lower(track_name) AS tn, lower(artists) AS ar, duration_ms
        FROM staging.kaggle_tracks
        GROUP BY 1,2,3
        HAVING COUNT(*) > 1
      )
      SELECT t.* FROM staging.kaggle_tracks t
      JOIN d
        ON lower(t.track_name) = d.tn
       AND lower(t.artists)    = d.ar
       AND t.duration_ms       = d.duration_ms
      ORDER BY t.track_name, t.artists
    """
}

# ------------------------
# Esquema de observabilidade
# ------------------------
DDL_QUALITY = """
CREATE SCHEMA IF NOT EXISTS quality;

CREATE TABLE IF NOT EXISTS quality.run_history (
  run_id        TEXT PRIMARY KEY,
  started_at    TIMESTAMP,
  finished_at   TIMESTAMP,
  status        TEXT,            -- OK | FAIL
  row_count     BIGINT,
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS quality.metrics (
  run_id        TEXT,
  metric_name   TEXT,
  metric_value  DOUBLE,
  PRIMARY KEY (run_id, metric_name)
);

CREATE TABLE IF NOT EXISTS quality.violations (
  run_id        TEXT,
  rule_name     TEXT,
  expected      TEXT,
  actual        TEXT
);
"""


def _write_csv(con: duckdb.DuckDBPyConnection, name: str, sql: str) -> None:
    """Executa a consulta e salva no padrão quality_<name>.csv (compatível com sua versão)."""
    df = con.execute(sql).df()
    out = OUTPUTS / f"quality_{name}.csv"
    df.to_csv(out, index=False)
    print(f"[OK] {name} -> {out}")


def _upsert_metrics(con: duckdb.DuckDBPyConnection, run_id: str, metrics: dict) -> None:
    for k, v in metrics.items():
        con.execute("""
            INSERT OR REPLACE INTO quality.metrics (run_id, metric_name, metric_value)
            VALUES (?, ?, ?)
        """, [run_id, k, float(v)])


def _record_violation(con: duckdb.DuckDBPyConnection, run_id: str, rule: str, expected: str, actual: str) -> None:
    con.execute("""
        INSERT INTO quality.violations (run_id, rule_name, expected, actual)
        VALUES (?, ?, ?, ?)
    """, [run_id, rule, expected, actual])


def main():
    # Identificador da execução (idempotente o suficiente p/ auditoria)
    run_id = f"qrun_{int(time.time())}"
    started = datetime.now(timezone.utc)

    con = duckdb.connect(DB_PATH.as_posix())

    # Garante estruturas de observabilidade
    con.execute(DDL_QUALITY)

    # Registra início
    con.execute("""
        INSERT INTO quality.run_history (run_id, started_at, status, row_count, notes)
        VALUES (?, ?, 'RUNNING', NULL, NULL)
    """, [run_id, started])

    # 1) Exporta CSVs como na sua versão (compatibilidade)
    for name, sql in SQLS.items():
        _write_csv(con, name, sql)

    # 2) Calcula métricas numéricas para thresholds
    metrics = {}

    # row_count
    metrics["row_count"] = con.execute(SQLS["row_count"]).fetchone()[0]

    # nulls_core
    null_row = con.execute(SQLS["nulls_core"]).fetchone()
    # Ordem: null_track_id, null_track_name, null_artists, null_duration_ms, null_popularity
    metrics["null_track_id"] = null_row[0]
    metrics["null_track_name"] = null_row[1]
    metrics["null_artists"] = null_row[2]
    metrics["null_duration_ms"] = null_row[3]
    # null_popularity não entra em thresholds por default, mas guardamos como métrica
    metrics["null_popularity"] = null_row[4]

    # ranges
    ranges_row = con.execute(SQLS["ranges_features_invalid"]).fetchone()
    metrics["bad_danceability"] = ranges_row[0]
    metrics["bad_energy"] = ranges_row[1]
    metrics["bad_speechiness"] = ranges_row[2]
    metrics["bad_acousticness"] = ranges_row[3]
    metrics["bad_instrumentalness"] = ranges_row[4]
    metrics["bad_liveness"] = ranges_row[5]
    metrics["bad_valence"] = ranges_row[6]

    # duplicates (contagens agregadas para thresholds)
    dup_track_id = con.execute(SQLS_COUNTS["dup_track_id"]).fetchone()[0]
    dup_fuzzy_key = con.execute(SQLS_COUNTS["dup_fuzzy_key"]).fetchone()[0]
    metrics["dup_track_id"] = dup_track_id
    metrics["dup_fuzzy_key"] = dup_fuzzy_key

    # popularity stats
    pop_min, pop_max, pop_avg = con.execute(SQLS["popularity_stats"]).fetchone()
    # Proteção caso venha None
    pop_min = 0 if pop_min is None else pop_min
    pop_max = 0 if pop_max is None else pop_max
    pop_avg = 0.0 if pop_avg is None else pop_avg
    metrics["pop_min"] = pop_min
    metrics["pop_max"] = pop_max
    metrics["pop_avg"] = pop_avg

    # 3) Persiste métricas
    _upsert_metrics(con, run_id, metrics)

    # 4) Avalia thresholds
    failed = False

    # nulos/faixas/duplicidades
    for k in [
        "null_track_id", "null_track_name", "null_artists", "null_duration_ms",
        "bad_danceability", "bad_energy", "bad_speechiness", "bad_acousticness",
        "bad_instrumentalness", "bad_liveness", "bad_valence",
        "dup_track_id", "dup_fuzzy_key"
    ]:
        limit = QUALITY_THRESHOLDS.get(k, None)
        if limit is not None and metrics.get(k, 0) > limit:
            failed = True
            _record_violation(con, run_id, k, f"<= {limit}", str(metrics.get(k)))

    # popularidade 0..100
    pop_min_expected = QUALITY_THRESHOLDS.get("pop_min_expected", 0)
    pop_max_expected = QUALITY_THRESHOLDS.get("pop_max_expected", 100)
    if metrics["pop_min"] < pop_min_expected:
        failed = True
        _record_violation(con, run_id, "pop_min_expected", f">= {pop_min_expected}", str(metrics["pop_min"]))
    if metrics["pop_max"] > pop_max_expected:
        failed = True
        _record_violation(con, run_id, "pop_max_expected", f"<= {pop_max_expected}", str(metrics["pop_max"]))

    # 5) Conclui e registra status
    finished = datetime.now(timezone.utc)
    status = "FAIL" if failed else "OK"
    con.execute("""
        UPDATE quality.run_history
           SET finished_at = ?, status = ?, row_count = ?
         WHERE run_id = ?
    """, [finished, status, metrics["row_count"], run_id])

    # 6) Feedback no console (e exit code para CI/CD)
    print(f"[quality] run_id={run_id} status={status} rows={metrics['row_count']}")
    if failed:
        # imprime violações
        df = con.execute("SELECT * FROM quality.violations WHERE run_id = ?", [run_id]).df()
        if not df.empty:
            print(df.to_string(index=False))

        # === EXPORTA OS OFENSORES PARA CSV ===
        # pega regras que falharam
        viol = con.execute(
            "SELECT rule_name FROM quality.violations WHERE run_id = ?",
            [run_id]
        ).fetchall()
        viol_rules = {r[0] for r in viol}

        # cria pasta offenders_<timestamp>
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        off_dir = OUTPUTS / f"offenders_{stamp}"
        off_dir.mkdir(parents=True, exist_ok=True)

        # mapeia a regra -> SELECT dos ofensores (definidos em SQLS_OFFENDERS)
        mapping = {
            "null_track_name": "null_track_name_rows",
            "null_artists": "null_artists_rows",
            "dup_track_id": "dup_track_id_rows",
            "dup_fuzzy_key": "dup_fuzzy_key_rows",
        }

        for rule, sql_key in mapping.items():
            if rule in viol_rules and sql_key in SQLS_OFFENDERS:
                dfv = con.execute(SQLS_OFFENDERS[sql_key]).df()
                out = off_dir / f"{sql_key}.csv"
                dfv.to_csv(out, index=False)
                print(f"[export] {rule} -> {out}")

    con.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

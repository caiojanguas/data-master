import os
import duckdb
from datetime import datetime, timezone
from src.config import DB_PATH

# carregar .env (opcional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

MASK_SALT = os.getenv("MASK_SALT", "CHANGE_ME_SALT")

# -----------------------------------------------------------------------------
# DDL de schemas e tabela de auditoria (com run_id)
# -----------------------------------------------------------------------------
DDL_SCHEMAS = """
-- Schemas
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS quality;

-- Tabela de rejeições (auditoria) com run_id
CREATE TABLE IF NOT EXISTS quality.rejected_rows (
  run_id           TEXT,
  rejected_at      TIMESTAMP,
  reason           TEXT,            -- null_track_name | null_artists | feature_out_of_range | dup_track_id
  track_id         TEXT,
  track_name       TEXT,
  artists          TEXT,
  album_name       TEXT,
  duration_ms      BIGINT,
  popularity       INTEGER,
  danceability     DOUBLE,
  energy           DOUBLE,
  loudness         DOUBLE,
  mode             INTEGER,
  speechiness      DOUBLE,
  acousticness     DOUBLE,
  instrumentalness DOUBLE,
  liveness         DOUBLE,
  valence          DOUBLE,
  tempo            DOUBLE,
  time_signature   INTEGER,
  track_genre      TEXT
);

-- Compatibilidade: se a tabela já existia sem run_id, garante a coluna
ALTER TABLE quality.rejected_rows ADD COLUMN IF NOT EXISTS run_id TEXT;

-- Índice para consultas por run_id
CREATE INDEX IF NOT EXISTS idx_rejected_rows_run ON quality.rejected_rows(run_id);
"""

# -----------------------------------------------------------------------------
# CTAS: anota qualidade e dedupe, materializando em temp table tmp_annot
# -----------------------------------------------------------------------------
SQL_CTAS_TMP_ANNOT = """
CREATE OR REPLACE TEMP TABLE tmp_annot AS
WITH base AS (
  SELECT
    t.*,
    ROW_NUMBER() OVER () AS _rn,
    (track_name IS NULL OR trim(track_name) = '') AS bad_tn,
    (artists    IS NULL OR trim(artists)    = '') AS bad_ar,
    (danceability     IS NULL OR danceability     < 0 OR danceability     > 1) OR
    (energy           IS NULL OR energy           < 0 OR energy           > 1) OR
    (speechiness      IS NULL OR speechiness      < 0 OR speechiness      > 1) OR
    (acousticness     IS NULL OR acousticness     < 0 OR acousticness     > 1) OR
    (instrumentalness IS NULL OR instrumentalness < 0 OR instrumentalness > 1) OR
    (liveness         IS NULL OR liveness         < 0 OR liveness         > 1) OR
    (valence          IS NULL OR valence          < 0 OR valence          > 1)
      AS bad_feat
  FROM staging.kaggle_tracks t
),
dups AS (
  SELECT
    track_id,
    CASE
      WHEN track_id IS NULL OR trim(track_id) = '' THEN NULL
      ELSE ROW_NUMBER() OVER (PARTITION BY lower(track_id) ORDER BY _rn)
    END AS rn_by_id,
    _rn
  FROM base
),
annot AS (
  SELECT
    b.*,
    d.rn_by_id,
    CASE
      WHEN bad_tn THEN 'null_track_name'
      WHEN bad_ar THEN 'null_artists'
      WHEN bad_feat THEN 'feature_out_of_range'
      WHEN (rn_by_id IS NOT NULL AND rn_by_id > 1) THEN 'dup_track_id'
      ELSE NULL
    END AS reject_reason
  FROM base b
  LEFT JOIN dups d ON d._rn = b._rn
)
SELECT * FROM annot;
"""

# -----------------------------------------------------------------------------
# Conjunto válido para montar curated
# -----------------------------------------------------------------------------
SQL_CREATE_TMP_VALID = """
CREATE OR REPLACE TEMP TABLE tmp_valid_tracks AS
SELECT b.*
FROM (
  SELECT t.*, ROW_NUMBER() OVER () AS _rn
  FROM staging.kaggle_tracks t
) b
JOIN tmp_annot a
  ON a._rn = b._rn
WHERE a.reject_reason IS NULL;
"""

# -----------------------------------------------------------------------------
# Construção da camada curated (a partir de tmp_valid_tracks)
# -----------------------------------------------------------------------------
DDL_CURATED = f"""
-- dimensões
CREATE OR REPLACE TABLE curated.dim_artist AS
WITH src AS (
  SELECT DISTINCT
    trim(x) AS artist_name
  FROM tmp_valid_tracks,
       UNNEST(str_split(COALESCE(artists,''), ';')) AS t(x)
  WHERE trim(x) <> ''
)
SELECT
  lower(sha256(artist_name)) AS artist_id,
  artist_name,
  sha256(artist_name || '{MASK_SALT}') AS artist_name_masked,
  current_timestamp AS first_seen_ts,
  'kaggle' AS source
FROM src;

CREATE OR REPLACE TABLE curated.dim_genre AS
WITH src AS (
  SELECT DISTINCT lower(trim(track_genre)) AS genre_name
  FROM tmp_valid_tracks
  WHERE track_genre IS NOT NULL AND trim(track_genre) <> ''
)
SELECT
  lower(sha256(genre_name)) AS genre_id,
  genre_name
FROM src;

-- surrogate de álbum: (album_name + primeiro artista)
CREATE OR REPLACE TABLE curated.dim_album AS
WITH base AS (
  SELECT
    album_name,
    split_part(artists, ';', 1) AS first_artist
  FROM tmp_valid_tracks
  WHERE album_name IS NOT NULL AND trim(album_name) <> ''
),
uniq AS (
  SELECT DISTINCT
    album_name,
    first_artist,
    lower(sha256(coalesce(album_name,'') || '|' || coalesce(first_artist,''))) AS album_id
  FROM base
)
SELECT
  album_id,
  album_name,
  lower(sha256(trim(first_artist))) AS artist_id,
  'kaggle' AS source
FROM uniq;

-- fatos
CREATE OR REPLACE TABLE curated.fact_track AS
SELECT
  CASE WHEN track_id IS NOT NULL AND trim(track_id) <> ''
       THEN lower(track_id)
       ELSE lower(sha256(coalesce(track_name,'') || '|' || coalesce(artists,'') || '|' || coalesce(CAST(duration_ms AS VARCHAR),'')))
  END AS track_id,
  lower(sha256(coalesce(album_name,'') || '|' || coalesce(split_part(artists,';',1),''))) AS album_id,
  track_name,
  duration_ms,
  CASE WHEN explicit = TRUE THEN TRUE ELSE FALSE END AS explicit_flag,
  popularity,
  'kaggle' AS source,
  ingestion_ts
FROM tmp_valid_tracks;

CREATE OR REPLACE TABLE curated.fact_track_features AS
SELECT
  CASE WHEN track_id IS NOT NULL AND trim(track_id) <> ''
       THEN lower(track_id)
       ELSE lower(sha256(coalesce(track_name,'') || '|' || coalesce(artists,'') || '|' || coalesce(CAST(duration_ms AS VARCHAR),'')))
  END AS track_id,
  danceability, energy, loudness, mode, speechiness, acousticness,
  instrumentalness, liveness, valence, tempo, time_signature
FROM tmp_valid_tracks;

-- bridge track x genre
CREATE OR REPLACE TABLE curated.bridge_track_genre AS
WITH base AS (
  SELECT
    CASE WHEN track_id IS NOT NULL AND trim(track_id) <> ''
         THEN lower(track_id)
         ELSE lower(sha256(coalesce(track_name,'') || '|' || coalesce(artists,'') || '|' || coalesce(CAST(duration_ms AS VARCHAR),'')))
    END AS track_id,
    lower(trim(track_genre)) AS genre_name
  FROM tmp_valid_tracks
  WHERE track_genre IS NOT NULL AND trim(track_genre) <> ''
)
SELECT
  b.track_id,
  lower(sha256(b.genre_name)) AS genre_id
FROM base b;
"""

# -----------------------------------------------------------------------------
# Pós-checagens para log rápido
# -----------------------------------------------------------------------------
POST_CHECKS = """
SELECT 'curated.dim_artist' AS tbl, COUNT(*) AS n FROM curated.dim_artist
UNION ALL SELECT 'curated.dim_genre', COUNT(*) FROM curated.dim_genre
UNION ALL SELECT 'curated.dim_album', COUNT(*) FROM curated.dim_album
UNION ALL SELECT 'curated.fact_track', COUNT(*) FROM curated.fact_track
UNION ALL SELECT 'curated.fact_track_features', COUNT(*) FROM curated.fact_track_features
UNION ALL SELECT 'curated.bridge_track_genre', COUNT(*) FROM curated.bridge_track_genre
ORDER BY tbl;
"""

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    con = duckdb.connect(DB_PATH.as_posix())

    # garante estruturas
    con.execute(DDL_SCHEMAS)

    # run_id desta execução (UTC, timezone-aware)
    run_id = f"cur_{int(datetime.now(timezone.utc).timestamp())}"
    print(f"[curated] run_id={run_id} — iniciando montagem…")

    # 1) materializa tmp_annot com flags de qualidade e dedupe
    con.execute(SQL_CTAS_TMP_ANNOT)

    # 2) insere rejeições desta execução com run_id
    con.execute("""
        INSERT INTO quality.rejected_rows (
          run_id, rejected_at, reason,
          track_id, track_name, artists, album_name, duration_ms, popularity,
          danceability, energy, loudness, mode, speechiness, acousticness,
          instrumentalness, liveness, valence, tempo, time_signature, track_genre
        )
        SELECT
          ?,                           -- run_id
          CURRENT_TIMESTAMP,           -- rejected_at
          reject_reason,               -- reason
          track_id, track_name, artists, album_name, duration_ms, popularity,
          danceability, energy, loudness, mode, speechiness, acousticness,
          instrumentalness, liveness, valence, tempo, time_signature, track_genre
        FROM tmp_annot
        WHERE reject_reason IS NOT NULL;
    """, [run_id])

    # 3) cria conjunto válido para construir curated
    con.execute(SQL_CREATE_TMP_VALID)

    # 4) (re)cria toda a camada curated a partir dos válidos
    con.execute(DDL_CURATED)

    # 5) sanity check das tabelas da curated
    df = con.execute(POST_CHECKS).df()
    print(df.to_string(index=False))

    # 6) resumo de rejeições apenas desta execução
    rej = con.execute("""
      SELECT reason, COUNT(*) AS rows
      FROM quality.rejected_rows
      WHERE run_id = ?
      GROUP BY 1
      ORDER BY rows DESC;
    """, [run_id]).df()
    if not rej.empty:
        print(f"\nRejeições desta execução (run_id={run_id}):")
        print(rej.to_string(index=False))

    con.close()

if __name__ == "__main__":
    main()

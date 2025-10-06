import os
import duckdb
from src.config import DB_PATH

# carregar .env (precisa de python-dotenv no requirements)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass  # se não tiver dotenv, usa apenas os envs do SO

MASK_SALT = os.getenv("MASK_SALT", "CHANGE_ME_SALT")

DDL = f"""
CREATE SCHEMA IF NOT EXISTS curated;

-- dimensões
CREATE OR REPLACE TABLE curated.dim_artist AS
WITH src AS (
  SELECT DISTINCT
    trim(x) AS artist_name
  FROM staging.kaggle_tracks,
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
  FROM staging.kaggle_tracks
  WHERE track_genre IS NOT NULL AND trim(track_genre) <> ''
)
SELECT
  lower(sha256(genre_name)) AS genre_id,
  genre_name
FROM src;

-- como não temos album_id no CSV, criamos um surrogate com (album_name + primeiro artista)
CREATE OR REPLACE TABLE curated.dim_album AS
WITH base AS (
  SELECT
    album_name,
    split_part(artists, ';', 1) AS first_artist
  FROM staging.kaggle_tracks
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
  lower(sha256(trim(first_artist))) AS artist_id, -- referencia dim_artist
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
  CASE WHEN explicit = TRUE THEN TRUE ELSE FALSE END AS explicit_flag,  -- <-- aqui o ajuste
  popularity,
  'kaggle' AS source,
  ingestion_ts
FROM staging.kaggle_tracks;

CREATE OR REPLACE TABLE curated.fact_track_features AS
SELECT
  CASE WHEN track_id IS NOT NULL AND trim(track_id) <> ''
       THEN lower(track_id)
       ELSE lower(sha256(coalesce(track_name,'') || '|' || coalesce(artists,'') || '|' || coalesce(CAST(duration_ms AS VARCHAR),'')))
  END AS track_id,
  danceability, energy, loudness, mode, speechiness, acousticness,
  instrumentalness, liveness, valence, tempo, time_signature
FROM staging.kaggle_tracks;

-- bridge track x genre
CREATE OR REPLACE TABLE curated.bridge_track_genre AS
WITH base AS (
  SELECT
    CASE WHEN track_id IS NOT NULL AND trim(track_id) <> ''
         THEN lower(track_id)
         ELSE lower(sha256(coalesce(track_name,'') || '|' || coalesce(artists,'') || '|' || coalesce(CAST(duration_ms AS VARCHAR),'')))
    END AS track_id,
    lower(trim(track_genre)) AS genre_name
  FROM staging.kaggle_tracks
  WHERE track_genre IS NOT NULL AND trim(track_genre) <> ''
)
SELECT
  b.track_id,
  lower(sha256(b.genre_name)) AS genre_id
FROM base b;
"""

POST_CHECKS = """
SELECT 'curated.dim_artist' AS tbl, COUNT(*) AS n FROM curated.dim_artist
UNION ALL SELECT 'curated.dim_genre', COUNT(*) FROM curated.dim_genre
UNION ALL SELECT 'curated.dim_album', COUNT(*) FROM curated.dim_album
UNION ALL SELECT 'curated.fact_track', COUNT(*) FROM curated.fact_track
UNION ALL SELECT 'curated.fact_track_features', COUNT(*) FROM curated.fact_track_features
UNION ALL SELECT 'curated.bridge_track_genre', COUNT(*) FROM curated.bridge_track_genre
ORDER BY tbl;
"""

def main():
    con = duckdb.connect(DB_PATH.as_posix())
    con.execute(DDL)
    df = con.execute(POST_CHECKS).df()
    print(df.to_string(index=False))
    con.close()

if __name__ == "__main__":
    main()

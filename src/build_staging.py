import duckdb
from pathlib import Path
from src.config import DB_PATH, ROOT

CSV_PATH = ROOT / "data" / "raw" / "kaggle" / "dataset.csv"

SQL = f"""
CREATE SCHEMA IF NOT EXISTS staging;

CREATE OR REPLACE TABLE staging.kaggle_tracks AS
SELECT
    CAST(track_id AS VARCHAR)                AS track_id,
    CAST(artists AS VARCHAR)                 AS artists,         -- pode vir 'A;B'
    CAST(album_name AS VARCHAR)              AS album_name,
    CAST(track_name AS VARCHAR)              AS track_name,
    CAST(popularity AS INTEGER)              AS popularity,
    CAST(duration_ms AS INTEGER)             AS duration_ms,
    CASE
        WHEN lower(cast(explicit AS VARCHAR)) IN ('true','t','1','yes','y','verdadeiro','v') THEN TRUE
        WHEN lower(cast(explicit AS VARCHAR)) IN ('false','f','0','no','n','falso','f') THEN FALSE
        ELSE NULL
    END                                      AS explicit,
    CAST(danceability AS DOUBLE)             AS danceability,
    CAST(energy AS DOUBLE)                   AS energy,
    CAST("key" AS INTEGER)                   AS "key",
    CAST(loudness AS DOUBLE)                 AS loudness,
    CAST(mode AS INTEGER)                    AS mode,
    CAST(speechiness AS DOUBLE)              AS speechiness,
    CAST(acousticness AS DOUBLE)             AS acousticness,
    CAST(instrumentalness AS DOUBLE)         AS instrumentalness,
    CAST(liveness AS DOUBLE)                 AS liveness,
    CAST(valence AS DOUBLE)                  AS valence,
    CAST(tempo AS DOUBLE)                    AS tempo,
    CAST(time_signature AS INTEGER)          AS time_signature,
    CAST(track_genre AS VARCHAR)             AS track_genre,
    current_timestamp                        AS ingestion_ts,
    'kaggle'                                 AS source
FROM read_csv_auto('{CSV_PATH.as_posix()}', header=True, sample_size=-1, normalize_names=False);
"""
#read_csv_auto(..., sample_size=-1) força o DuckDB a ler o arquivo inteiro antes de inferir tipos (evita erro por amostra pequena).
#Coluna "key" foi colocada entre aspas porque é palavra reservada em alguns dialetos; no DuckDB é ok, mas manteremos seguro.

def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB_PATH.as_posix())
    con.execute(SQL)
    # um ping simples para ver quantas linhas carregou
    n = con.execute("SELECT COUNT(*) FROM staging.kaggle_tracks").fetchone()[0]
    print(f"staging.kaggle_tracks criado com {n} linhas.")
    con.close()

if __name__ == "__main__":
    main()

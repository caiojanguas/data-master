import duckdb
from pathlib import Path
from src.config import DB_PATH, OUTPUTS

OUTPUTS.mkdir(parents=True, exist_ok=True)

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
            SUM(speechiness < 0 OR speechiness > 1 OR speechiness IS NULL)   AS bad_speechiness,
            SUM(acousticness < 0 OR acousticness > 1 OR acousticness IS NULL)AS bad_acousticness,
            SUM(instrumentalness < 0 OR instrumentalness > 1 OR instrumentalness IS NULL) AS bad_instrumentalness,
            SUM(liveness < 0 OR liveness > 1 OR liveness IS NULL)            AS bad_liveness,
            SUM(valence < 0 OR valence > 1 OR valence IS NULL)               AS bad_valence
        FROM staging.kaggle_tracks;
    """,
    "dup_by_track_id": """
        SELECT track_id, COUNT(*) AS cnt
        FROM staging.kaggle_tracks
        WHERE track_id IS NOT NULL
        GROUP BY 1
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 50;
    """,
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

def main():
    con = duckdb.connect(DB_PATH.as_posix())
    for name, sql in SQLS.items():
        df = con.execute(sql).df()
        out = OUTPUTS / f"quality_{name}.csv"
        df.to_csv(out, index=False)
        print(f"[OK] {name} -> {out}")
    con.close()
    print("Quality checks concluídos.")

if __name__ == "__main__":
    main()

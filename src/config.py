from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_KAGGLE = RAW / "kaggle"
RAW_API = RAW / "spotify_api"
STAGING = DATA / "staging"
CURATED = DATA / "curated"
OUTPUTS = DATA / "outputs"

# Kaggle dataset slug
KAGGLE_DATASET = "maharshipandya/-spotify-tracks-dataset"

DB_PATH = STAGING / "case.duckdb"

# --- Quality thresholds (ajuste conforme seu apetite de risco) ---
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

    # duplicidades (absoluto) — pode tolerar algumas, se quiser
    "dup_track_id": 0,
    "dup_fuzzy_key": 0,

    # estatísticas (ex.: popularidade esperada 0..100)
    "pop_min_expected": 0,    # min >= 0
    "pop_max_expected": 100,  # max <= 100
}

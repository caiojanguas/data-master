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
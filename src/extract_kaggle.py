import zipfile
import logging
from pathlib import Path
from datetime import datetime

from kaggle.api.kaggle_api_extended import KaggleApi
from src.config import RAW_KAGGLE, KAGGLE_DATASET

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def _ensure_dirs():
    RAW_KAGGLE.mkdir(parents=True, exist_ok=True)

def _unzip_all(zips_dir: Path, extract_to: Path):
    for zf in zips_dir.glob("*.zip"):
        logging.info(f"Descompactando: {zf.name}")
        with zipfile.ZipFile(zf, "r") as z:
            z.extractall(extract_to)
        zf.unlink()

def run():
    _ensure_dirs()
    logging.info("Iniciando extração do Kaggle (Spotify Tracks Dataset)")
    api = KaggleApi(); api.authenticate()  # requer %USERPROFILE%\.kaggle\kaggle.json

    logging.info(f"Baixando dataset: {KAGGLE_DATASET}")
    api.dataset_download_files(KAGGLE_DATASET, path=str(RAW_KAGGLE), quiet=False)

    _unzip_all(RAW_KAGGLE, RAW_KAGGLE)

    meta = RAW_KAGGLE / "_INGESTION_METADATA.txt"
    meta.write_text(f"source={KAGGLE_DATASET}\ningestion_ts={datetime.utcnow().isoformat()}Z\n")

    files = [p.name for p in RAW_KAGGLE.glob("*") if p.is_file()]
    logging.info(f"Arquivos em RAW_KAGGLE: {files}")
    logging.info("Extração concluída com sucesso.")

if __name__ == "__main__":
    run()
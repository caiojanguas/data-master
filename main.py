# main.py
"""
Orquestrador do pipeline (CLI).
- Extensível por subcomandos (ex.: api, cloud) sem quebrar os atuais
- Usa sys.executable -m para rodar os módulos existentes de forma isolada
- Saídas e códigos de retorno propagados (bom p/ CI/CD)
"""

import os
import sys
import argparse
import subprocess
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def run(cmd: list[str], title: str) -> None:
    """Executa um passo e falha se o retorno != 0, imprimindo etapa e duração."""
    print(f"\n🔹 {title}")
    print("   $", " ".join(cmd))
    started = datetime.now()
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        elapsed = datetime.now() - started
        print(f"❌ Falhou: {title} (em {elapsed})")
        sys.exit(e.returncode)
    elapsed = datetime.now() - started
    print(f"✅ Concluído: {title} (em {elapsed})")


# -----------------------
# Subcomandos (pipeline)
# -----------------------

def cmd_extract_kaggle(_args):
    run([sys.executable, "-m", "src.extract_kaggle"], "Ingestão Kaggle (raw)")

def cmd_build_staging(_args):
    run([sys.executable, "-m", "src.build_staging"], "Construção da STAGING")

def cmd_quality(_args):
    run([sys.executable, "-m", "src.run_quality_checks"], "Quality Checks na STAGING")

def cmd_curated(_args):
    run([sys.executable, "-m", "src.build_curated"], "Montagem da camada CURATED")

def cmd_full(_args):
    """Pipeline completo atual (Kaggle → staging → quality → curated)."""
    cmd_extract_kaggle(_args)
    cmd_build_staging(_args)
    cmd_quality(_args)
    cmd_curated(_args)

# -----------------------
# Ganchos futuros
# -----------------------

def cmd_api_spotify(_args):
    """
    FUTURO: ingestão incremental/near-real-time via API do Spotify.
    Sugestão de passos:
      - src.extract_spotify (staging_api.*)
      - src.run_quality_checks --source=api
      - src.build_curated --merge api
    """
    print("⚠️ Stub: integração com API do Spotify ainda não implementada.")
    print("   Planejado: src.extract_spotify → staging_api → quality → curated (merge).")

def cmd_cloud(_args):
    """
    FUTURO: execução em Cloud (ex.: orchestration no GitHub Actions, DB no S3/GCS/Azure).
    Este subcomando pode:
      - Validar secrets/variáveis
      - Preparar buckets/tabelas/infra temporária
      - Disparar jobs (ex.: via workflow ou API do provedor)
    """
    print("⚠️ Stub: modo Cloud ainda não implementado.")
    print("   Planejado: armazenamento em objeto + runner CI/CD + flags específicas.")


# -----------------------
# CLI
# -----------------------

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Orquestrador do pipeline Data-Master (extensível por subcomandos)."
    )
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("extract-kaggle", help="Baixa/atualiza dados do Kaggle (raw)").set_defaults(func=cmd_extract_kaggle)
    sp.add_parser("build-staging", help="Constrói a camada staging").set_defaults(func=cmd_build_staging)
    sp.add_parser("quality", help="Roda quality checks na staging").set_defaults(func=cmd_quality)
    sp.add_parser("curated", help="Monta a camada curated").set_defaults(func=cmd_curated)
    sp.add_parser("full", help="Executa o pipeline completo atual").set_defaults(func=cmd_full)

    # ganchos futuros
    sp.add_parser("api-spotify", help="(Futuro) Ingestão via API do Spotify").set_defaults(func=cmd_api_spotify)
    sp.add_parser("cloud", help="(Futuro) Execução em ambiente Cloud").set_defaults(func=cmd_cloud)
    return p


def main():
    parser = make_parser()
    args = parser.parse_args()
    # Checagens leves antes de rodar (ex.: .env opcional)
    if not os.getenv("MASK_SALT"):
        print("ℹ️ Aviso: variável MASK_SALT não está definida (.env). Usará default do código (não recomendado).")
    args.func(args)


if __name__ == "__main__":
    main()

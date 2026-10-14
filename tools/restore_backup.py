"""Restore a private backup into an empty database; no HTTP endpoint."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prospector.store import Store
from prospector.domain import DomainError
from sqlalchemy.exc import SQLAlchemyError


def main():
    parser = argparse.ArgumentParser(description="Restaura um backup V2 em banco vazio.")
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    url = os.getenv("PROSPECTOR_DATABASE_URL", "")
    if not url:
        parser.error("Defina PROSPECTOR_DATABASE_URL no ambiente.")
    try:
        store = Store(url, os.getenv("PROSPECTOR_MODE", "cloud"))
        store.restore_empty(args.backup.read_bytes())
        store.engine.dispose()
    except DomainError as exc:
        parser.exit(1, str(exc)+"\n")
    except (SQLAlchemyError, OSError, ValueError, KeyError):
        parser.exit(1, "Não foi possível restaurar. Confira arquivo, versão e conexão com o banco.\n")
    print("Backup restaurado. Inicie o aplicativo e entre com a senha que estava ativa no backup.")


if __name__ == "__main__":
    main()

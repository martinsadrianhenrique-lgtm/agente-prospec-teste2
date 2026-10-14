"""Offline administrator recovery. Requires direct database credentials."""
import getpass
import os
import sys
from pathlib import Path
from sqlalchemy import select, update, delete
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prospector.store import Store
from prospector import schema as S
from prospector.security import hash_password, password_problem
from prospector.domain import DomainError


def main():
    url = os.getenv("PROSPECTOR_DATABASE_URL", "")
    if not url:
        sys.exit("Defina PROSPECTOR_DATABASE_URL no ambiente privado.")
    password = getpass.getpass("Nova senha do Adrian (mínimo 8 caracteres): ")
    if problem := password_problem(password):
        sys.exit(problem)
    if password != getpass.getpass("Repita a senha: "):
        sys.exit("As senhas não coincidem.")
    try:
        store = Store(url, os.getenv("PROSPECTOR_MODE", "cloud"))
        with store.engine.begin() as conn:
            user_id = conn.execute(select(S.users.c.id).where(S.users.c.username == "adrian", S.users.c.role == "admin")).scalar_one_or_none()
            if not user_id:
                sys.exit("Administrador Adrian não encontrado. Confira o banco selecionado.")
            conn.execute(update(S.users).where(S.users.c.id == user_id).values(password_hash=hash_password(password), active=True, must_change_password=False))
            conn.execute(delete(S.sessions).where(S.sessions.c.user_id == user_id))
            conn.execute(delete(S.login_limits).where(S.login_limits.c.username == "adrian"))
        store.engine.dispose()
    except (SQLAlchemyError, DomainError):
        sys.exit("Não foi possível atualizar. Confira a conexão com o banco.")
    print("Senha atualizada; sessões anteriores encerradas.")


if __name__ == "__main__":
    main()

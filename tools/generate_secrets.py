"""Interactive private configuration creation; never prints passwords/hashes."""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prospector.security import hash_password, password_problem


def main():
    target = Path(".streamlit/secrets.toml")
    if target.exists():
        sys.exit("Já existe .streamlit/secrets.toml. Preserve a configuração atual.")
    passwords = {}
    for user in ["adrian", "vitor"]:
        password = getpass.getpass(f"Senha inicial de {user}: ")
        if user == "adrian" and (problem := password_problem(password)):
            sys.exit(problem)
        if not password:
            sys.exit("Senha vazia não é permitida.")
        if password != getpass.getpass("Confirme: "):
            sys.exit("As senhas não coincidem.")
        passwords[user] = hash_password(password)
    content = '[app]\nmode = "cloud"\ndatabase_url = "postgresql://USUARIO:SENHA@HOST/BANCO?sslmode=require"\n'
    for user, name, role, change in [("adrian", "Adrian", "admin", "false"), ("vitor", "Vitor", "operator", "true")]:
        content += f'\n[bootstrap_users.{user}]\nname = "{name}"\nrole = "{role}"\npassword_hash = "{passwords[user]}"\nmust_change_password = {change}\n'
    target.parent.mkdir(exist_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)
    print("Configuração privada criada. Edite apenas a URL do banco e copie para Secrets no Streamlit. Não envie esse arquivo ao GitHub.")


if __name__ == "__main__":
    main()

from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def click(at, label):
    next(b for b in at.button if b.label == label).click().run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def make_app(tmp_path, definitions):
    at = AppTest.from_file(str(ROOT/"app.py"), default_timeout=30)
    at.secrets["app"] = {"mode": "local", "database_url": "sqlite:///"+str(tmp_path/"ui.db")}
    at.secrets["bootstrap_users"] = definitions
    return at.run()


def login(at, username, password, new_password):
    at.text_input(key="login_user").set_value(username)
    at.text_input(key="login_password").set_value(password)
    click(at, "Entrar")
    assert at.title[0].value == "Defina sua senha"
    at.text_input(key="new_password").set_value(new_password)
    at.text_input(key="repeat_password").set_value(new_password)
    click(at, "Salvar nova senha")
    assert not at.error


def test_admin_pages_import_and_history(tmp_path, definitions):
    if not (ROOT / "initial_data" / "clinicas.csv").exists():
        pytest.skip("Teste de integração com base privada fornecida pelo usuário.")
    at = make_app(tmp_path, definitions)
    assert not at.exception
    login(at, "adrian", "Admin-inicial-teste", "Senha pessoal segura do Adrian")
    assert at.title[0].value == "Bom trabalho, Adrian."
    at.radio(key="nav").set_value("Importar").run()
    click(at, "Carregar as bases recebidas: 213 registros")
    assert "213 novos" in at.success[0].value
    for page in ["Leads e CRM", "Pesquisa", "Resultados", "Configurações", "Minha conta"]:
        at.radio(key="nav").set_value(page).run(timeout=30)
        assert not at.exception, (page, [e.message for e in at.exception])
    at.radio(key="nav").set_value("Leads e CRM").run()
    next(x for x in at.selectbox if x.label == "Tipo de registro").set_value("Contato realizado")
    next(x for x in at.selectbox if x.label == "Canal").set_value("Ligação")
    next(x for x in at.text_area if x.label == "O que foi conversado / resposta recebida").set_value("Contato feito com a recepção.")
    click(at, "Registrar no histórico")
    assert not at.error, [e.value for e in at.error]
    assert any("Último contato realizado por Adrian" in x.value for x in at.info)
    at.radio(key="nav").set_value("Configurações").run()
    click(at, "Gerar backup completo")
    assert any(x.label == "Baixar backup JSON" for x in at.get("download_button"))


def test_vitor_sees_shared_base_claims_and_records(tmp_path, definitions):
    if not (ROOT / "initial_data" / "clinicas.csv").exists():
        pytest.skip("Teste de integração com base privada fornecida pelo usuário.")
    admin = make_app(tmp_path, definitions)
    login(admin, "adrian", "Admin-inicial-teste", "Senha pessoal segura do Adrian")
    admin.radio(key="nav").set_value("Importar").run()
    click(admin, "Carregar as bases recebidas: 213 registros")
    vitor = make_app(tmp_path, definitions)
    login(vitor, "vitor", "123456", "Senha pessoal segura do Vitor")
    assert any(x.value == "213" for x in vitor.metric)
    vitor.radio(key="nav").set_value("Leads e CRM").run()
    click(vitor, "Assumir este lead")
    assert any(x.value == "Vitor" for x in vitor.metric)
    next(x for x in vitor.selectbox if x.label == "Tipo de registro").set_value("Contato realizado")
    next(x for x in vitor.selectbox if x.label == "Canal").set_value("Ligação")
    next(x for x in vitor.text_area if x.label == "O que foi conversado / resposta recebida").set_value("Vitor conversou com a empresa.")
    click(vitor, "Registrar no histórico")
    assert any("Último contato realizado por Vitor" in x.value for x in vitor.info)
    admin.radio(key="nav").set_value("Leads e CRM").run()
    assert any("Último contato realizado por Vitor" in x.value for x in admin.info)
    vitor.radio(key="nav").set_value("Configurações").run()
    assert not any(x.label == "Gerar backup completo" for x in vitor.button)
    vitor.radio(key="nav").set_value("Importar").run()
    assert not any(x.label.startswith("Carregar as bases") for x in vitor.button)

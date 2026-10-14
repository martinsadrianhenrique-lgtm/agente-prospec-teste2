import json
import pytest
from sqlalchemy import select, update
from prospector import schema as S
from prospector.domain import DomainError, ConflictError, stamp
from prospector.importer import prepare_rows
from prospector.store import Store
from prospector.views import crm_rows
from test_crm import candidate, version, eligible, draft
from test_ui import make_app, login, click


def test_multiple_lists_share_one_history_and_removal_keeps_lead(db, team):
    admin, vitor = team
    a = db.create_list(vitor, "Oficinas Apucarana", city="Apucarana", niche="Oficina")
    b = db.create_list(vitor, "Retorno outubro")
    row = prepare_rows([{"Empresa":"Oficina Exemplo", "Cidade":"Apucarana", "Nicho":"Oficina"}])[0]
    lid, created = db.create_lead(vitor, row, list_id=a)
    assert created
    db.record_interaction(vitor, lid, "Contato realizado", "Ligação", "Conversei com o responsável", version(db, vitor, lid))
    assert db.create_lead(vitor, row, list_id=b) == (lid, False)
    db.list_membership(vitor, b, [lid, lid])
    snap = db.snapshot(admin)
    assert len(snap["leads"]) == 1 and len(snap["list_members"]) == 2
    record = crm_rows(snap)[0]
    assert "Oficinas Apucarana" in record["Listas"] and "Retorno outubro" in record["Listas"]
    assert record["Último contato por"] == "Vitor"
    db.list_membership(vitor, a, [lid], remove=True)
    assert len(db.snapshot(admin)["leads"]) == 1
    assert len(db.snapshot(admin)["interactions"]) == 1


def test_operator_imports_to_own_list_reimport_links_existing(db, team):
    admin, vitor = team
    a = db.create_list(vitor, "Lista A")
    b = db.create_list(vitor, "Lista B")
    admin_list = db.create_list(admin, "Lista do administrador")
    raw = [{"Empresa":"Contato Exemplo", "Cidade":"Califórnia", "Nicho":"Serviços", "Telefone":"(44) 99912-3456"}]
    rows = prepare_rows(raw)
    data = json.dumps(raw).encode()
    assert db.import_records(vitor, rows, "list.csv", data, list_id=a)["new"] == 1
    assert db.import_records(vitor, rows, "list.csv", data, list_id=b)["already_imported"]
    snap = db.snapshot(admin)
    assert len(snap["list_members"]) == 2
    assert snap["leads"][0]["owner_id"] == db.whoami(vitor)["id"]
    with pytest.raises(DomainError):
        db.import_records(vitor, rows, "list.csv", data, list_id=admin_list)


def test_same_file_with_different_city_defaults_is_not_wrongly_reused(db, team):
    admin, _ = team
    raw = [{"Empresa":"Loja Exemplo"}]
    for city in ["Apucarana", "Maringá"]:
        li = db.create_list(admin, "Lojas "+city, city=city, niche="Loja")
        prepared = prepare_rows(raw, default_city=city, default_niche="Loja")
        assert db.import_records(admin, prepared, "mesmo.csv", b"same file", list_id=li)["new"] == 1
    assert {x["city"] for x in db.snapshot(admin)["leads"]} == {"Apucarana", "Maringá"}


def test_list_archiving_permissions_and_stale_metadata(db, team):
    admin, vitor = team
    a = db.create_list(admin, "Lista exclusiva para organizar")
    lid = candidate(db, vitor)
    with pytest.raises(DomainError, match="criador"):
        db.list_membership(vitor, a, [lid])
    db.list_membership(admin, a, [lid])
    item = db.snapshot(admin)["lists"][0]
    db.update_list(admin, a, item["name"], "", "", "", True, item["version"])
    with pytest.raises(ConflictError):
        db.update_list(admin, a, item["name"], "Outra edição", "", "", False, item["version"])
    with pytest.raises(DomainError, match="arquivada"):
        db.list_membership(admin, a, [lid])
    assert len(db.snapshot(admin)["leads"]) == 1
    assert crm_rows(db.snapshot(admin))[0]["Listas"] == ""


def test_details_edit_invalidates_old_identity_and_preserves_author(db, team):
    admin, vitor = team
    lid = candidate(db, vitor); c, o = eligible(db, vitor, lid)
    message = draft(db, vitor, lid, c, o)
    db.edit_lead(vitor, lid, "Empresa outro endereço", "Apucarana", "Serviços", "Rua Teste 1", "https://example.com", "", "Pessoa Exemplo",
        "contato@example.com", "retorno, indicação", version(db, vitor, lid))
    with pytest.raises(DomainError, match="Identidade"):
        db.message_link(vitor, message)
    record = crm_rows(db.snapshot(admin))[0]
    assert record["Pessoa de contato"] == "Pessoa Exemplo" and record["E-mail"] == "contato@example.com"
    assert db.snapshot(admin)["interactions"][-1]["actor_name"] == "Vitor"


def test_lists_and_details_backup_roundtrip(db, team, tmp_path):
    admin, vitor = team
    lid = candidate(db, vitor)
    li = db.create_list(vitor, "Minha lista", "Descrição")
    db.list_membership(vitor, li, [lid])
    backup = db.backup(admin)
    restored = Store("sqlite:///"+str(tmp_path/"restored_lists.db"), "local")
    restored.restore_empty(backup)
    token = restored.login("vitor", "Vitor-Nova-Senha-2026")
    assert crm_rows(restored.snapshot(token))[0]["Listas"] == "Minha lista"
    restored.engine.dispose()


def test_migrate_v20_existing_campaigns_once(db, team):
    admin, _ = team
    candidate(db, admin)
    with db.engine.begin() as conn:
        conn.execute(update(S.settings).where(S.settings.c.key=="schema_version").values(value="2.0.0"))
    migrated = Store(str(db.engine.url), "local" if db.engine.dialect.name=="sqlite" else "cloud") if db.engine.dialect.name=="sqlite" else None
    if migrated:
        assert len(migrated.snapshot(admin)["lists"]) == 1
        assert len(migrated.snapshot(admin)["list_members"]) == 1
        migrated.engine.dispose()
    else:
        with db.engine.begin() as conn:
            db._migrate_lists(conn)
            db._migrate_lists(conn)
            assert len(conn.execute(select(S.list_members)).all()) == 1


def test_configured_personal_password_can_login_without_forced_change(tmp_path):
    from prospector.security import hash_password
    db = Store("sqlite:///"+str(tmp_path/"config.db"), "local")
    db.bootstrap({"adrian": {"name":"Adrian", "role":"admin", "password_hash":hash_password("Exemplo*08"), "must_change_password":False}})
    token = db.login("Adrian", "Exemplo*08")
    assert not db.whoami(token)["must_change_password"]
    assert db.snapshot(token)["leads"] == []
    db.engine.dispose()


def test_admin_creates_additional_operator(db, team):
    admin, vitor = team
    with pytest.raises(DomainError):
        db.create_user(vitor, "pessoa", "Pessoa", "Exemplo*2026")
    db.create_user(admin, "pessoa", "Pessoa", "Exemplo*2026")
    token = db.login("pessoa", "Exemplo*2026")
    assert db.whoami(token)["role"] == "operator" and db.whoami(token)["must_change_password"]


def test_ui_create_list_contact_open_crm_and_board(tmp_path, definitions):
    at = make_app(tmp_path, definitions)
    login(at, "adrian", "Admin-inicial-teste", "Senha pessoal segura do Adrian")
    at.radio(key="nav").set_value("Listas").run()
    next(x for x in at.text_input if x.label=="Nome da lista").set_value("Oficinas da cidade")
    next(x for x in at.text_input if x.label=="Cidade padrão").set_value("Apucarana")
    next(x for x in at.text_input if x.label=="Nicho padrão").set_value("Oficina")
    click(at, "Criar lista")
    assert not at.error
    next(x for x in at.text_input if x.label=="Empresa / negócio").set_value("Oficina de teste")
    click(at, "Adicionar à lista")
    assert not at.error, [e.value for e in at.error]
    click(at, "Abrir ficha completa")
    assert any(x.value=="Oficina de teste" for x in at.subheader)
    at.toggle(key="show_board").set_value(True).run()
    assert not at.exception
    next(x for x in at.text_input if x.label=="Pessoa de contato / decisor").set_value("Contato Teste")
    click(at, "Salvar dados da ficha")
    assert not at.error
    at.radio(key="nav").set_value("Listas").run()
    next(x for x in at.radio if x.label=="Como adicionar").set_value("Digitar ou colar uma tabela").run()
    assert not at.exception
    next(x for x in at.radio if x.label=="Como adicionar").set_value("Importar arquivo").run()
    click(at, "Abrir importação")
    assert at.title[0].value=="Importar bases"
    assert not at.exception

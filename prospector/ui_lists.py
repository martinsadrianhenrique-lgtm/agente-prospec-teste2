"""Contact-list workspace. A list organizes leads; it never copies their history."""
import html
import json
import pandas as pd
import streamlit as st
from .domain import DomainError, normalized, local_time
from .importer import prepare_rows
from .views import export_csv


def lists_page(db, token, user, snap, records, action, go_lead):
    st.markdown('<div class="ef-tag">Organização comercial</div>', unsafe_allow_html=True)
    st.title("Listas de contatos")
    st.write("Separe sua prospecção por região, nicho ou campanha. O histórico acompanha a empresa em todas as listas.")
    with st.expander("＋ Criar nova lista", expanded=not snap["lists"]):
        with st.form("new_list"):
            name = st.text_input("Nome da lista", placeholder="Ex.: Clínicas · Apucarana · Outubro")
            cols = st.columns(2)
            city = cols[0].text_input("Cidade padrão", placeholder="Apucarana")
            niche = cols[1].text_input("Nicho padrão", placeholder="Clínica odontológica")
            description = st.text_area("Objetivo da lista", placeholder="O que queremos oferecer e para quem?")
            create = st.form_submit_button("Criar lista", type="primary", use_container_width=True)
        if create:
            def save():
                st.session_state.selected_list_id = db.create_list(token, name, description, city, niche)
            action(save, "Lista criada. Agora adicione seus contatos.")
    cols = st.columns([3,1])
    query = cols[0].text_input("Buscar lista", placeholder="Nome, cidade ou nicho")
    archived = cols[1].checkbox("Ver arquivadas")
    all_lists = [li for li in snap["lists"] if li["archived"] == archived and (not query or normalized(query) in normalized(li["name"]+" "+li["city"]+" "+li["niche"]))]
    if not all_lists:
        st.info("Nenhuma lista nesse filtro. Crie uma lista acima para começar.")
        return
    users = {u["id"]: u["name"] for u in snap["users"]}
    member_ids = {li["id"]: {m["lead_id"] for m in snap["list_members"] if m["list_id"] == li["id"]} for li in all_lists}
    cols = st.columns(3)
    for i, li in enumerate(sorted(all_lists, key=lambda x:x["created_at"], reverse=True)[:9]):
        with cols[i%3].container(border=True):
            data = [r for r in records if r["ID"] in member_ids[li["id"]]]
            st.markdown(f"#### {html.escape(li['name'])}")
            st.caption(f"{li['city'] or 'Todas as cidades'} · {li['niche'] or 'Vários nichos'}")
            done = sum(bool(r["Último contato por"]) for r in data)
            st.metric("Contatos na lista", len(data))
            st.progress(done/len(data) if data else 0, text=f"{done} com contato realizado")
            if st.button("Abrir lista", key="list_card_"+li["id"], use_container_width=True):
                st.session_state.selected_list_id = li["id"]
                st.rerun()
    lookup = {li["id"]:li for li in all_lists}
    if st.session_state.get("selected_list_id") not in lookup:
        st.session_state.selected_list_id = next(iter(lookup))
    selected = st.selectbox("Lista aberta", list(lookup), format_func=lambda x:lookup[x]["name"], key="selected_list_id")
    item = lookup[selected]
    ids = member_ids[selected]
    subset = [r for r in records if r["ID"] in ids]
    editable = user["role"] == "admin" or item["created_by"] == user["id"]
    active_edit = editable and not item["archived"]
    st.subheader(item["name"])
    st.write(item["description"] or "Adicione contatos e acompanhe a evolução desta lista.")
    st.caption(f"Criada por {users.get(item['created_by'], '')} · {local_time(item['created_at'])}")
    cols = st.columns(4)
    cols[0].metric("Empresas", len(subset))
    cols[1].metric("Já contatadas", sum(bool(r["Último contato por"]) for r in subset))
    cols[2].metric("Atrasadas", sum(r["Atrasado"] for r in subset))
    cols[3].metric("Clientes ganhos", sum(r["Etapa"] == "Ganho" for r in subset))
    tab_contacts, tab_add, tab_manage = st.tabs(["Contatos e acompanhamento", "Adicionar contatos", "Configurar lista"])
    with tab_contacts:
        q = st.text_input("Buscar contato nesta lista", key="member_search_"+selected)
        shown = [r for r in subset if not q or normalized(q) in normalized(r["Empresa"]+" "+r["Telefone"]+" "+r["Pessoa de contato"])]
        if shown:
            columns = ["Empresa", "Pessoa de contato", "Cidade", "Responsável", "Etapa", "Último contato por", "Próxima ação", "Prazo"]
            st.dataframe(pd.DataFrame(shown)[columns], hide_index=True, use_container_width=True)
            target = st.selectbox("Contato para abrir no CRM", [r["ID"] for r in shown], format_func=lambda x:next(r["Empresa"] for r in shown if r["ID"]==x))
            if st.button("Abrir ficha completa", type="primary"):
                go_lead(target)
        else:
            st.info("Nenhum contato aqui ainda. Use a aba Adicionar contatos.")
        st.download_button("Exportar lista em CSV", export_csv(subset), file_name="lista_contatos.csv", mime="text/csv", disabled=not subset)
    with tab_add:
        if not active_edit:
            st.info("Para organizar esta lista, use o acesso do criador ou do administrador. Listas arquivadas precisam ser restauradas.")
        add_mode = st.radio("Como adicionar", ["Cadastrar um contato", "Digitar ou colar uma tabela", "Usar contatos do CRM", "Importar arquivo"], horizontal=True, key="list_add_mode_"+selected)
        if add_mode == "Cadastrar um contato":
            with st.form("list_new_lead_"+selected):
                company = st.text_input("Empresa / negócio")
                cols = st.columns(2)
                city = cols[0].text_input("Cidade do contato", value=item["city"])
                niche = cols[1].text_input("Nicho do contato", value=item["niche"])
                phone = st.text_input("Telefone com DDD (opcional)")
                source = st.text_input("Fonte do telefone (opcional)", help="URL pública ou registre a origem posteriormente na ficha.")
                address = st.text_input("Endereço (opcional)")
                submit = st.form_submit_button("Adicionar à lista", type="primary", disabled=not active_edit)
            if submit:
                def save_contact():
                    row = prepare_rows([{"Empresa": company, "Cidade": city, "Nicho": niche, "Telefone": phone, "Fonte pública": source, "Endereço": address}])[0]
                    if row["phone_errors"]:
                        raise DomainError("Confira o telefone. Use DDD e separe números com /.")
                    db.create_lead(token, row, item["name"], selected)
                action(save_contact, "Contato adicionado. Se já existia, a ficha e o histórico foram preservados.")
        elif add_mode == "Digitar ou colar uma tabela":
            st.caption("Cole linhas da sua planilha ou digite abaixo. Empresa é obrigatória; cidade e nicho usam os padrões da lista se ficarem vazios.")
            template = pd.DataFrame([{k:"" for k in ["Empresa", "Cidade", "Nicho", "Telefone", "Endereço", "Fonte pública"]} for _ in range(3)])
            table = st.data_editor(template, num_rows="dynamic", hide_index=True, use_container_width=True, key="paste_table_"+selected, disabled=not active_edit)
            if st.button("Salvar contatos da tabela", disabled=not active_edit, type="primary"):
                def save_table():
                    incoming = [r for r in table.fillna("").to_dict("records") if any(str(v).strip() for v in r.values())]
                    prepared = prepare_rows(incoming, default_niche=item["niche"], default_city=item["city"])
                    if any(not r["valid"] or r["phone_errors"] for r in prepared):
                        raise DomainError("Confira empresa, cidade, nicho e telefones em todas as linhas antes de salvar.")
                    data = json.dumps(incoming, ensure_ascii=False, sort_keys=True).encode()
                    db.import_records(token, prepared, "tabela_digitada.csv", data, item["name"], selected)
                action(save_table, "Tabela adicionada à lista sem duplicar fichas existentes.")
        elif add_mode == "Usar contatos do CRM":
            choices = {r["ID"]:f"{r['Empresa']} · {r['Cidade']}" for r in records if r["ID"] not in ids}
            chosen = st.multiselect("Contatos existentes", list(choices), format_func=choices.get)
            if st.button("Incluir selecionados", disabled=not active_edit or not chosen):
                action(lambda:db.list_membership(token, selected, chosen), "Contatos incluídos na lista.")
        else:
            st.write("Importe CSV ou Excel e selecione esta lista como destino.")
            if st.button("Abrir importação", disabled=not active_edit):
                st.session_state.import_list_target = selected
                st.session_state.nav_target = "Importar"
                st.rerun()
    with tab_manage:
        with st.form("list_settings_"+selected):
            name = st.text_input("Nome", item["name"])
            description = st.text_area("Descrição", item["description"])
            city = st.text_input("Cidade padrão da lista", item["city"])
            niche = st.text_input("Nicho padrão da lista", item["niche"])
            archive = st.checkbox("Lista arquivada", value=item["archived"], help="Os contatos, tarefas e históricos permanecem no CRM.")
            save = st.form_submit_button("Salvar lista", disabled=not editable)
        if save:
            action(lambda:db.update_list(token, selected, name, description, city, niche, archive, item["version"]), "Lista atualizada.")
        chosen = st.multiselect("Remover contatos somente desta lista", [r["ID"] for r in subset], format_func=lambda x:next(r["Empresa"] for r in subset if r["ID"]==x))
        if st.button("Remover da lista", disabled=not active_edit or not chosen):
            action(lambda:db.list_membership(token, selected, chosen, remove=True), "Removidos da lista; fichas e históricos preservados.")

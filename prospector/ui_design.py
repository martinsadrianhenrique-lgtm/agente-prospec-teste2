import html
import streamlit as st


def apply_design():
    st.markdown('''<style>
    [data-testid="stAppViewContainer"]{background:linear-gradient(145deg,#f6f4fb 0%,#f8fafc 55%,#f1f5fb 100%)}
    [data-testid="stSidebar"]{background:#221a35}
    [data-testid="stSidebar"] h3,[data-testid="stSidebar"] p,[data-testid="stSidebar"] label{color:#f5efff!important}
    [data-testid="stSidebar"] button p{color:#302044!important}
    [data-testid="stVerticalBlockBorderWrapper"]{border-radius:16px}
    [data-testid="stMetric"]{border:1px solid #e7e1f2;border-radius:16px;box-shadow:0 4px 18px #221a3505;background:#fff}
    .ef-hero{padding:26px 28px;border-radius:22px;background:linear-gradient(115deg,#241936,#492b75 70%,#7050c4);color:white;margin:8px 0 22px}
    .ef-hero h2{color:white!important;margin:0 0 8px;font-size:1.7rem!important;line-height:1.25}
    .ef-hero p{color:#e0d5f4;font-size:.97rem;margin:0;max-width:740px}
    .ef-hero small{display:block;text-transform:uppercase;letter-spacing:.15em;color:#c9b1ef;margin-bottom:12px;font-size:.7rem;font-weight:700}
    button[kind="primary"]{border-radius:10px;box-shadow:0 3px 9px #7050c422}
    [data-testid="stTabs"] [role="tab"]{font-weight:600}
    @media(max-width:640px){.ef-hero{padding:20px}.ef-hero h2{font-size:1.4rem!important}.ef-hero p{font-size:.9rem}}
    </style>''', unsafe_allow_html=True)


def hero(eyebrow, title, subtitle):
    st.markdown(f'<div class="ef-hero"><small>{html.escape(eyebrow)}</small><h2>{html.escape(title)}</h2><p>{html.escape(subtitle)}</p></div>', unsafe_allow_html=True)


def pipeline_board(records, go_lead):
    groups = [("Novos", {"Novo"}), ("Contato feito", {"Contatado"}), ("Em conversa", {"Em conversa", "Interessado"}),
        ("Negociação", {"Reunião marcada", "Proposta enviada"}), ("Encerrados", {"Ganho", "Perdido", "Encerrado sem resposta"})]
    for col, (name, stages) in zip(st.columns(5), groups):
        data = [r for r in records if r["Etapa"] in stages]
        with col:
            st.markdown(f"**{name} · {len(data)}**")
            for r in data[:8]:
                with st.container(border=True):
                    st.markdown(f"**{html.escape(r['Empresa'])}**")
                    st.caption(r["Cidade"]+" · "+r["Responsável"])
                    st.caption(r["Etapa"])
                    if r["Próxima ação"]:
                        st.write(r["Próxima ação"])
                        st.caption(("Atrasado · " if r["Atrasado"] else "")+r["Prazo"])
                    if st.button("Abrir", key="board_"+r["ID"], use_container_width=True):
                        go_lead(r["ID"])
            if len(data)>8:
                st.caption(f"Mais {len(data)-8} no filtro. Use a lista para consultar todos.")

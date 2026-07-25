import streamlit as st
import pandas as pd
from database import load_core_data, save_notas_to_db

def view_governanca():
    st.markdown("### 🔎 Busca e Governança")
    st.markdown("Explore, filtre e edite a base oficial de obras de forma centralizada.")

    # =====================================================================
    # 1. CARREGAMENTO DOS DADOS E SEGURANÇA (RLS)
    # =====================================================================
    df_notas, df_equipes_db, resumo_levantadores, levantadores_criticos, todos_levantadores, mapa_lat, mapa_lon, _ = load_core_data()
    
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")

    # Proteção em Nível de Linha (Se for Levantador, ele só vê e edita o dele)
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        df_notas = df_notas[df_notas['LEVANTADOR'].str.strip().str.upper() == usuario_limpo]
        df_equipes_db = df_equipes_db[df_equipes_db['Levantador'].str.strip().str.upper() == usuario_limpo]
        todos_levantadores = [usuario_limpo]
        st.info(f"👁️ **Modo Foco (RLS Ativo):** Exibindo apenas a base e as obras atribuídas a você ({usuario_atual}).")

    if df_notas.empty:
        st.warning("O banco de dados de notas está vazio. Faça a importação na aba correspondente.")
        return

    # =====================================================================
    # 2. MÓDULO DE EXPLORAÇÃO E GOVERNANÇA (EDITOR DE BASE)
    # =====================================================================
    st.markdown("#### 🔍 Explorador e Edição da Base de Dados")
    
    # ATUALIZADO PARA O NOVO TEMPLATE
    colunas_template = [
        'ID SISCO', 'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 
        'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'PROTOCOLO', 
        'CONTA CONTRATO', 'INSTALACAO', 'NOME', 'REGIONAL', 'MUNICIPIO', 
        'ENDEREÇO', 'LOCALIDADE', 'LATITUDE', 'LONGITUDE', 'PONTO DE REFERENCIA', 
        'TIPO LIGACAO'
    ]
    
    for col in colunas_template:
        if col not in df_notas.columns: df_notas[col] = ""
            
    cols_extras = [c for c in df_notas.columns if c not in colunas_template]
    df_notas = df_notas[colunas_template + cols_extras]

    colunas_data = ['DATA CRIAÇAO SISCO', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST']
    for col in colunas_data:
        if col in df_notas.columns:
            df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce').dt.date

    # Filtros da Tabela
    regioes = ["TODAS"] + sorted(list(set([str(x) for x in df_notas['REGIONAL'].unique() if pd.notna(x)])))
    municipios = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['MUNICIPIO'].unique() if pd.notna(x)])))
    levantadores = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['LEVANTADOR'].unique() if pd.notna(x)])))
    status_sap = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['STATUS SAP'].unique() if pd.notna(x)])))
    status_list_op = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['STATUS LIST'].unique() if pd.notna(x)])))

    if 'target_status_list' in st.session_state:
        alvo = st.session_state.pop('target_status_list')
        match = next((s for s in status_list_op if str(s).upper() == alvo), None)
        st.session_state['filtro_list_widget'] = match if match else 'TODOS'

    if st.session_state.get('filtro_lev_widget') and st.session_state['filtro_lev_widget'] not in levantadores:
        st.session_state['filtro_lev_widget'] = "TODOS"

    with st.container(border=True):
        st.markdown("#### 🎯 Painel de Filtros da Base")
        
        c_busca, c_cols = st.columns([3, 1.5])
        busca_livre = c_busca.text_input("Busca Rápida", placeholder="🔍 Pesquise por ID SISCO, Protocolo ou Nome...", label_visibility="collapsed", key="search_gov")
        
        todas_cols = df_notas.columns.tolist()
        cols_padrao = ['ID SISCO', 'PROTOCOLO', 'LEVANTADOR', 'STATUS LIST', 'STATUS SAP', 'REGIONAL', 'MUNICIPIO', 'DATA CRIAÇAO SISCO']
        cols_padrao = [c for c in cols_padrao if c in todas_cols]
        
        colunas_selecionadas = c_cols.multiselect("Colunas Visíveis", todas_cols, default=cols_padrao, placeholder="Escolha as colunas...", key="ms_cols_gov")
        
        c1, c2, c3, c4, c5 = st.columns(5)
        filtro_reg = c1.selectbox("Regional", regioes, key="filtro_reg_widget")
        filtro_mun = c2.selectbox("Município", municipios, key="filtro_mun_widget")
        filtro_lev = c3.selectbox("Levantador", levantadores, key="filtro_lev_widget")
        filtro_sap = c4.selectbox("Status SAP", status_sap, key="filtro_sap_widget")
        filtro_list = c5.selectbox("Status List", status_list_op, key="filtro_list_widget")
        
    df_filtrado = df_notas.copy()
    
    if filtro_reg != "TODAS": df_filtrado = df_filtrado[df_filtrado['REGIONAL'].astype(str) == filtro_reg]
    if filtro_mun != "TODOS": df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'].astype(str) == filtro_mun]
    if filtro_lev != "TODOS": df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'].astype(str) == filtro_lev]
    if filtro_sap != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS SAP'].astype(str) == filtro_sap]
    if filtro_list != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS LIST'].astype(str) == filtro_list]
    
    if busca_livre:
        termo = str(busca_livre).lower()
        df_filtrado = df_filtrado[
            df_filtrado['ID SISCO'].astype(str).str.lower().str.contains(termo) |
            df_filtrado['PROTOCOLO'].astype(str).str.lower().str.contains(termo) |
            df_filtrado['NOME'].astype(str).str.lower().str.contains(termo)
        ]

    st.caption(f"**Total Encontrado na Base:** {len(df_filtrado)} registros filtrados.")

    if not colunas_selecionadas: colunas_selecionadas = cols_padrao
    df_para_editar = df_filtrado[colunas_selecionadas].copy()
    
    config_colunas = {}
    for col in colunas_data:
        if col in colunas_selecionadas: config_colunas[col] = st.column_config.DateColumn(col, format="DD/MM/YYYY")
            
    if 'STATUS LIST' in colunas_selecionadas:
        opcoes_status = sorted(list(set([str(x) for x in df_notas['STATUS LIST'].unique() if pd.notna(x) and x.strip() != ""])))
        config_colunas['STATUS LIST'] = st.column_config.SelectboxColumn("STATUS LIST", help="Altere o status clicando na seta", options=opcoes_status)

    df_editado = st.data_editor(
        df_para_editar,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        height=450,
        column_config=config_colunas,
        key="editor_gov"
    )

    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("#### ⚡ Ações da Base de Dados")
        col_save, spacer, col_adv = st.columns([3, 4, 3])
        
        if col_save.button("💾 Salvar Alterações Tabela", type="primary", use_container_width=True, key="btn_save_tab_gov"):
            if st.session_state.perfil_usuario == "LEITURA":
                st.error("Acesso Negado: O seu perfil é apenas leitura.")
            else:
                df_notas.update(df_editado)
                novos_indices = [idx for idx in df_editado.index if idx not in df_notas.index]
                if novos_indices:
                    novas_linhas = df_editado.loc[novos_indices]
                    novas_linhas = novas_linhas.reindex(columns=df_notas.columns)
                    df_notas = pd.concat([df_notas, novas_linhas])
                
                for col in colunas_data:
                    if col in df_notas.columns:
                        df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce').dt.strftime('%d/%m/%Y').fillna("")
                
                save_notas_to_db(df_notas)
                st.success("✅ Edições salvas com sucesso no banco de dados!")
                st.rerun()

        with col_adv.popover("⚙️ Configurações Avançadas", use_container_width=True):
            st.markdown("**Área de Risco**")
            st.info("Ações aqui afetam toda a base de dados oficial.")
            if st.button("🗑️ Apagar Base Inteira", type="secondary", use_container_width=True, key="btn_del_gov"):
                if st.session_state.perfil_usuario != "ADMIN":
                    st.error("Acesso Negado: Apenas ADMINS podem limpar a base.")
                else:
                    save_notas_to_db(pd.DataFrame(columns=colunas_template), backup=True)
                    st.success("✅ Banco de dados limpo! A estrutura original foi preservada.")
                    st.rerun()

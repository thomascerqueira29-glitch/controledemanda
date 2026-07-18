import streamlit as st
import pandas as pd
from database import load_core_data, save_notas_to_db

def view_governanca():
    st.markdown("### 🔎 Governança Direta")
    st.markdown("Visualize, filtre e edite a base de obras de acordo com o template oficial.")

    # 1. Carregamento dos Dados
    df_notas, _, _, _, _, _, _, _ = load_core_data()
    
    # 2. Mapeamento das 22 colunas exatas
    colunas_template = [
        'ID SISCO', 'STATUS SISCO', 'TIPO LIGACAO SISCO', 'DESCRIÇÃO SERVIÇO SISCO', 
        'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 
        'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'PROTOCOLO', 
        'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 
        'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 
        'PONTO DE REFERENCIA', 'TIPO LIGACAO'
    ]
    
    # Garante estrutura
    if df_notas.empty:
        df_notas = pd.DataFrame(columns=colunas_template)
    else:
        for col in colunas_template:
            if col not in df_notas.columns:
                df_notas[col] = ""
                
        cols_extras = [c for c in df_notas.columns if c not in colunas_template]
        df_notas = df_notas[colunas_template + cols_extras]

    # Tratamento de Datas
    colunas_data = ['DATA CRIAÇAO SISCO', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST']
    for col in colunas_data:
        if col in df_notas.columns:
            df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce', dayfirst=True)

    # =====================================================================
    # CAPTURA INTELIGENTE DOS FILTROS (Vindos do Painel Executivo)
    # =====================================================================
    def_reg = st.session_state.get('ui_reg', 'TODAS')
    def_mun = st.session_state.get('ui_mun', 'TODOS')
    def_lev = st.session_state.get('ui_lev', 'TODOS')
    def_sap = st.session_state.get('ui_sap', 'TODOS')
    
    # Se vier uma lista residual do cache antigo, ignora. Pega a String pura.
    def_list = st.session_state.get('ui_list', 'TODOS')
    if isinstance(def_list, list): 
        def_list = 'TODOS'

    # 3. Área de Filtros Interativos (Agora com 5 Colunas)
    with st.expander("📊 Painel de Filtros", expanded=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        
        regioes = ["TODAS"] + sorted([str(x) for x in df_notas['REGIONAL'].unique() if pd.notna(x)])
        idx_reg = regioes.index(def_reg) if def_reg in regioes else 0
        filtro_reg = c1.selectbox("Regional", regioes, index=idx_reg)
        
        municipios = ["TODOS"] + sorted([str(x) for x in df_notas['MUNICIPIO'].unique() if pd.notna(x)])
        idx_mun = municipios.index(def_mun) if def_mun in municipios else 0
        filtro_mun = c2.selectbox("Município", municipios, index=idx_mun)
        
        levantadores = ["TODOS"] + sorted([str(x) for x in df_notas['LEVANTADOR'].unique() if pd.notna(x)])
        idx_lev = levantadores.index(def_lev) if def_lev in levantadores else 0
        filtro_lev = c3.selectbox("Levantador", levantadores, index=idx_lev)
        
        status_sap = ["TODOS"] + sorted([str(x) for x in df_notas['STATUS SAP'].unique() if pd.notna(x)])
        idx_sap = status_sap.index(def_sap) if def_sap in status_sap else 0
        filtro_sap = c4.selectbox("Status SAP", status_sap, index=idx_sap)
        
        # O NOVO FILTRO: Status List (Sincronizado automaticamente)
        status_list = ["TODOS"] + sorted([str(x) for x in df_notas['STATUS LIST'].unique() if pd.notna(x)])
        idx_list = 0
        if def_list != 'TODOS':
            for i, item in enumerate(status_list):
                if item.upper() == def_list.upper():
                    idx_list = i
                    break
        filtro_list = c5.selectbox("Status List", status_list, index=idx_list)
        
        busca_livre = st.text_input("🔍 Busca Rápida (ID SISCO, PROTOCOLO ou NOME DO SOLICITANTE)")

    # Limpa as variáveis da memória para que o usuário possa trocar os filtros manualmente depois
    for key in ['ui_lev', 'ui_reg', 'ui_mun', 'ui_sap', 'ui_list']:
        if key in st.session_state:
            del st.session_state[key]

    # 4. Aplicação dos Filtros 
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
            df_filtrado['NOME DO SOLICITANTE'].astype(str).str.lower().str.contains(termo)
        ]

    st.caption(f"**Total de Obras Filtradas:** {len(df_filtrado)} registros.")

    config_colunas = {}
    for col in colunas_data:
        config_colunas[col] = st.column_config.DateColumn(
            col,
            format="DD/MM/YYYY" 
        )

    # 5. Tabela de Edição
    df_editado = st.data_editor(
        df_filtrado,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        height=500,
        column_config=config_colunas
    )

    # 6. Botões de Ação
    st.markdown("---")
    col_save, col_clear, _ = st.columns([2, 2, 6])
    
    if col_save.button("💾 Salvar Alterações", type="primary", use_container_width=True):
        if st.session_state.perfil_usuario == "LEITURA":
            st.error("Acesso Negado: O seu perfil é apenas leitura.")
        else:
            df_notas.update(df_editado)
            
            novos_indices = [idx for idx in df_editado.index if idx not in df_notas.index]
            if novos_indices:
                df_notas = pd.concat([df_notas, df_editado.loc[novos_indices]])
            
            for col in colunas_data:
                if col in df_notas.columns:
                    df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce').dt.strftime('%d/%m/%Y').fillna("")
            
            save_notas_to_db(df_notas)
            st.success("✅ Edições salvas com sucesso no banco de dados!")
            st.rerun()

    if col_clear.button("🗑️ Apagar Base Inteira", type="secondary", use_container_width=True):
        if st.session_state.perfil_usuario != "ADMIN":
            st.error("Acesso Negado: Apenas ADMINS podem limpar a base.")
        else:
            save_notas_to_db(pd.DataFrame(columns=colunas_template), backup=True)
            st.success("✅ Banco de dados limpo! A estrutura original foi preservada.")
            st.rerun()

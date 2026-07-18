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
    
    if df_notas.empty:
        df_notas = pd.DataFrame(columns=colunas_template)
    else:
        for col in colunas_template:
            if col not in df_notas.columns:
                df_notas[col] = ""
                
        cols_extras = [c for c in df_notas.columns if c not in colunas_template]
        df_notas = df_notas[colunas_template + cols_extras]

    # Prepara as datas em formato puro (sem horas) para o st.column_config.DateColumn não bugar
    colunas_data = ['DATA CRIAÇAO SISCO', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST']
    for col in colunas_data:
        if col in df_notas.columns:
            df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce').dt.date

    # =====================================================================
    # 3. LISTAS DE FILTROS E CONEXÃO COM O PAINEL EXECUTIVO
    # =====================================================================
    regioes = ["TODAS"] + sorted(list(set([str(x) for x in df_notas['REGIONAL'].unique() if pd.notna(x)])))
    municipios = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['MUNICIPIO'].unique() if pd.notna(x)])))
    levantadores = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['LEVANTADOR'].unique() if pd.notna(x)])))
    status_sap = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['STATUS SAP'].unique() if pd.notna(x)])))
    status_list_op = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['STATUS LIST'].unique() if pd.notna(x)])))

    # Captura a exigência do "Em levantamento" enviada pelo botão Ver Base
    if 'target_status_list' in st.session_state:
        alvo = st.session_state.pop('target_status_list')
        match = next((s for s in status_list_op if str(s).upper() == alvo), None)
        if match:
            st.session_state['filtro_list_widget'] = match
        else:
            st.session_state['filtro_list_widget'] = 'TODOS'

    # Escudo Anti-Bug: Impede o sistema de travar caso o levantador procurado tenha sumido da base
    if st.session_state.get('filtro_lev_widget') and st.session_state['filtro_lev_widget'] not in levantadores:
        st.session_state['filtro_lev_widget'] = "TODOS"

    # ÁREA DE FILTROS INTERATIVOS - As 'keys' gravam e preservam a sua escolha
    with st.expander("📊 Painel de Filtros", expanded=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        filtro_reg = c1.selectbox("Regional", regioes, key="filtro_reg_widget")
        filtro_mun = c2.selectbox("Município", municipios, key="filtro_mun_widget")
        filtro_lev = c3.selectbox("Levantador", levantadores, key="filtro_lev_widget")
        filtro_sap = c4.selectbox("Status SAP", status_sap, key="filtro_sap_widget")
        filtro_list = c5.selectbox("Status List", status_list_op, key="filtro_list_widget")
        
        busca_livre = st.text_input("🔍 Busca Rápida (ID SISCO, PROTOCOLO ou NOME DO SOLICITANTE)")
        
    # =====================================================================
    # 4. APLICAÇÃO DOS FILTROS NA BASE
    # =====================================================================
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
            
            # Ao salvar no Banco de Dados, transforma tudo de volta para a String Brasileira padrão (DD/MM/YYYY)
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

import streamlit as st
import pandas as pd
from database import load_core_data, save_notas_to_db

def view_governanca():
    st.markdown("### 🔎 Governança Direta")
    st.markdown("Visualize, filtre e edite a base de obras de acordo com o template oficial.")

    # 1. Carregamento dos Dados
    df_notas, _, _, _, _, _, _, _ = load_core_data()
    
    # 2. Mapeamento das 22 colunas exatas do 'template.xlsx'
    colunas_template = [
        'ID SISCO', 'STATUS SISCO', 'TIPO LIGACAO SISCO', 'DESCRIÇÃO SERVIÇO SISCO', 
        'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 
        'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'PROTOCOLO', 
        'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 
        'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 
        'PONTO DE REFERENCIA', 'TIPO LIGACAO'
    ]
    
    # Garante que o banco obedeça à estrutura do template
    if df_notas.empty:
        df_notas = pd.DataFrame(columns=colunas_template)
    else:
        for col in colunas_template:
            if col not in df_notas.columns:
                df_notas[col] = ""
                
        cols_extras = [c for c in df_notas.columns if c not in colunas_template]
        df_notas = df_notas[colunas_template + cols_extras]

    # --- NOVO: Tratamento de Datas ---
    colunas_data = ['DATA CRIAÇAO SISCO', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST']
    for col in colunas_data:
        if col in df_notas.columns:
            # Converte as strings do banco para objetos de Data (para o calendário funcionar na tela)
            df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce', dayfirst=True)

    # 3. Área de Filtros Interativos
    with st.expander("📊 Painel de Filtros", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        
        regioes = ["TODAS"] + sorted(df_notas['REGIONAL'].astype(str).unique().tolist())
        filtro_reg = c1.selectbox("Regional", regioes)
        
        municipios = ["TODOS"] + sorted(df_notas['MUNICIPIO'].astype(str).unique().tolist())
        filtro_mun = c2.selectbox("Município", municipios)
        
        levantadores = ["TODOS"] + sorted(df_notas['LEVANTADOR'].astype(str).unique().tolist())
        filtro_lev = c3.selectbox("Levantador", levantadores)
        
        status_sap = ["TODOS"] + sorted(df_notas['STATUS SAP'].astype(str).unique().tolist())
        filtro_sap = c4.selectbox("Status SAP", status_sap)
        
        busca_livre = st.text_input("🔍 Busca Rápida (ID SISCO, PROTOCOLO ou NOME DO SOLICITANTE)")

    # 4. Aplicação dos Filtros
    df_filtrado = df_notas.copy()
    
    if filtro_reg != "TODAS": df_filtrado = df_filtrado[df_filtrado['REGIONAL'] == filtro_reg]
    if filtro_mun != "TODOS": df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'] == filtro_mun]
    if filtro_lev != "TODOS": df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'] == filtro_lev]
    if filtro_sap != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS SAP'] == filtro_sap]
    
    if busca_livre:
        termo = str(busca_livre).lower()
        df_filtrado = df_filtrado[
            df_filtrado['ID SISCO'].astype(str).str.lower().str.contains(termo) |
            df_filtrado['PROTOCOLO'].astype(str).str.lower().str.contains(termo) |
            df_filtrado['NOME DO SOLICITANTE'].astype(str).str.lower().str.contains(termo)
        ]

    st.caption(f"**Total de Obras Filtradas:** {len(df_filtrado)} registros.")

    # --- NOVO: Configura visualização do calendário no Data Editor ---
    config_colunas = {}
    for col in colunas_data:
        config_colunas[col] = st.column_config.DateColumn(
            col,
            format="DD/MM/YYYY" # Força o formato brasileiro na exibição
        )

    # 5. Tabela de Edição (Estilo Planilha)
    df_editado = st.data_editor(
        df_filtrado,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        height=500,
        column_config=config_colunas # Aplica as regras de coluna criadas
    )

    # 6. Botões de Ação
    st.markdown("---")
    col_save, col_clear, _ = st.columns([2, 2, 6])
    
    if col_save.button("💾 Salvar Alterações", type="primary", use_container_width=True):
        if st.session_state.perfil_usuario == "LEITURA":
            st.error("Acesso Negado: O seu perfil é apenas leitura.")
        else:
            # Mescla as edições filtradas de volta para o DataFrame completo
            df_notas.update(df_editado)
            
            # Adiciona novas linhas criadas pelo usuário
            novos_indices = [idx for idx in df_editado.index if idx not in df_notas.index]
            if novos_indices:
                df_notas = pd.concat([df_notas, df_editado.loc[novos_indices]])
            
            # --- NOVO: Limpeza das datas antes de salvar no SQLite ---
            for col in colunas_data:
                if col in df_notas.columns:
                    # Formata a data para texto BR (DD/MM/AAAA) e troca valores vazios por "" (evitando o infame "NaT")
                    df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce').dt.strftime('%d/%m/%Y').fillna("")
            
            # Salva no Banco de Dados
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

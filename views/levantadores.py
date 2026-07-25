import streamlit as st
import pandas as pd
import sqlite3
import io
from database import DB_PATH, load_core_data

def view_levantadores():
    if st.session_state.perfil_usuario != "ADMIN": 
        st.error("Restrito. Apenas administradores podem acessar esta página.")
        return
        
    st.markdown("### 👷 Gestão Residencial e Equipes")
    
    # 1. Carrega os dados direto do banco
    with sqlite3.connect(DB_PATH, timeout=10) as conn: 
        df_eq = pd.read_sql("SELECT * FROM equipes", conn)
    
    # =================================================================
    # 2. PADRONIZAÇÃO ABSOLUTA DE COLUNAS
    # =================================================================
    # Transforma tudo em maiúsculo e tira espaços para evitar conflitos
    df_eq.columns = [str(c).upper().strip() for c in df_eq.columns]
    
    df_eq = df_eq.rename(columns={
        'LEVANTADOR': 'COLABORADOR',
        'RESIDENCIA': 'MUNICIPIO',
        'MUNICÍPIO': 'MUNICIPIO'
    })
    
    df_eq = df_eq.loc[:, ~df_eq.columns.duplicated()]
    
    # Colunas exigidas baseadas na nova planilha oficial
    colunas_oficiais = ['EQUIPE', 'COLABORADOR', 'LONGITUDE', 'LATITUDE', 'MUNICIPIO', 'REGIONAL']
    for col in colunas_oficiais:
        if col not in df_eq.columns: 
            if col in ['LATITUDE', 'LONGITUDE']:
                df_eq[col] = 0.0
            else:
                df_eq[col] = ""
                
    # Filtra mantendo apenas as colunas oficiais na ordem correta
    df_eq = df_eq[colunas_oficiais]

    # Limpa dados vazios para a visualização na tabela interativa
    df_levs = df_eq[['COLABORADOR', 'EQUIPE', 'MUNICIPIO']].copy()
    df_levs = df_levs[df_levs['COLABORADOR'].str.strip() != ""]
    df_levs = df_levs.drop_duplicates(subset=['COLABORADOR'])
    
    # Lista de municípios únicos já existentes no banco para o dropdown
    op_mun = [""] + sorted([str(x).upper() for x in df_eq['MUNICIPIO'].dropna().unique() if str(x).strip() != ''])
    
    st.markdown("Altere a base (Município) do técnico diretamente na tabela e clique em **Atualizar Bases**.")
    
    # 3. Editor Visual da Tabela
    df_ed = st.data_editor(
        df_levs, 
        column_config={
            "COLABORADOR": st.column_config.TextColumn("Colaborador (Técnico)", disabled=True), 
            "EQUIPE": st.column_config.TextColumn("Equipe", disabled=True), 
            "MUNICIPIO": st.column_config.SelectboxColumn("Município Base", options=op_mun)
        }, 
        hide_index=True, 
        use_container_width=True,
        height=300
    )
    
    if st.button("💾 Atualizar Bases", type="primary"):
        # Mapeia as alterações feitas na tabela interativa para o DataFrame principal
        mapeamento_mun = df_ed.set_index('COLABORADOR')['MUNICIPIO'].to_dict()
        df_eq['MUNICIPIO'] = df_eq['COLABORADOR'].map(mapeamento_mun).fillna(df_eq['MUNICIPIO'])
        
        with sqlite3.connect(DB_PATH, timeout=20) as conn: 
            df_eq.to_sql('equipes', conn, if_exists='replace', index=False)
            
        load_core_data.clear() # Limpa o cache para o Painel Executivo refletir na mesma hora
        st.success("✅ Bases atualizadas com sucesso!")
        st.rerun()

    st.markdown("---")
    
    # =================================================================
    # 4. CADASTRO INDIVIDUAL E CARGA EM LOTE (NOVO)
    # =================================================================
    col_cad, col_lote = st.columns([1, 1.2])
    
    with col_cad:
        st.markdown("#### ➕ Cadastro Rápido")
        with st.form("new_lev"):
            nome = st.text_input("Nome (Colaborador)", placeholder="Ex: JOÃO DA SILVA")
            eq = st.text_input("Equipe", placeholder="Ex: EQUIPE 01")
            res = st.text_input("Município Base", placeholder="Ex: SÃO LUÍS")
            
            if st.form_submit_button("Salvar Cadastro", type="primary", use_container_width=True):
                if nome and eq and res:
                    nova_linha = pd.DataFrame([{
                        'EQUIPE': eq.upper().strip(),
                        'COLABORADOR': nome.upper().strip(),
                        'LONGITUDE': 0.0,
                        'LATITUDE': 0.0,
                        'MUNICIPIO': res.upper().strip(),
                        'REGIONAL': ''
                    }])
                    
                    df_novo = pd.concat([df_eq, nova_linha], ignore_index=True)
                    
                    with sqlite3.connect(DB_PATH, timeout=20) as conn: 
                        df_novo.to_sql('equipes', conn, if_exists='replace', index=False)
                        
                    load_core_data.clear()
                    st.success(f"✅ Colaborador cadastrado!")
                    st.rerun()
                else:
                    st.warning("⚠️ Preencha todos os campos para cadastrar individualmente.")

    with col_lote:
        st.markdown("#### 📂 Substituir Base Completa")
        st.info("Envie uma planilha preenchida para **apagar a base atual inteira** e inserir uma nova lista limpa de colaboradores.")
        
        # Gera o arquivo de modelo em memória na hora para o botão de download
        df_template_eq = pd.DataFrame(columns=colunas_oficiais)
        buf_template = io.BytesIO()
        with pd.ExcelWriter(buf_template, engine='openpyxl') as writer:
            df_template_eq.to_excel(writer, index=False, sheet_name='LEVANTADORES')
        
        c_down, c_up = st.columns([1, 1])
        c_down.download_button(
            label="📥 Baixar Modelo (Excel)",
            data=buf_template.getvalue(),
            file_name="levantadores_base.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        arquivo_up = st.file_uploader("Suba a planilha (.xlsx)", type=['xlsx'], label_visibility="collapsed")
        
        if arquivo_up:
            if st.button("🚨 Deletar Antiga e Salvar Nova", type="primary", use_container_width=True):
                try:
                    df_novo_eq = pd.read_excel(arquivo_up)
                    df_novo_eq.columns = [str(c).upper().strip() for c in df_novo_eq.columns]
                    
                    # Verifica se as colunas obrigatórias existem
                    faltantes = [c for c in colunas_oficiais if c not in df_novo_eq.columns]
                    if faltantes:
                        st.error(f"❌ O arquivo não possui as colunas obrigatórias: {', '.join(faltantes)}")
                    else:
                        df_novo_eq = df_novo_eq[colunas_oficiais]
                        # Garante que números fiquem numéricos e o resto preenchido corretamente
                        df_novo_eq['LATITUDE'] = pd.to_numeric(df_novo_eq['LATITUDE'], errors='coerce').fillna(0.0)
                        df_novo_eq['LONGITUDE'] = pd.to_numeric(df_novo_eq['LONGITUDE'], errors='coerce').fillna(0.0)
                        df_novo_eq = df_novo_eq.fillna("")
                        
                        # Substitui a tabela do banco de dados (if_exists='replace')
                        with sqlite3.connect(DB_PATH, timeout=20) as conn: 
                            df_novo_eq.to_sql('equipes', conn, if_exists='replace', index=False)
                        
                        load_core_data.clear()
                        st.success("✅ Nova base oficial de equipes inserida com sucesso!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar a carga em lote: {e}")

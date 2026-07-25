import streamlit as st
import pandas as pd
import sqlite3
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
    # 2. PADRONIZAÇÃO ABSOLUTA DE COLUNAS (Evita o OperationalError)
    # =================================================================
    
    # Transforma tudo em maiúsculo e tira espaços para evitar conflito (ex: 'Equipe' vs 'EQUIPE')
    df_eq.columns = [str(c).upper().strip() for c in df_eq.columns]
    
    # Renomeia colunas do padrão antigo para o novo, reaproveitando os dados já cadastrados
    df_eq = df_eq.rename(columns={
        'LEVANTADOR': 'COLABORADOR',
        'RESIDENCIA': 'MUNICIPIO',
        'MUNICÍPIO': 'MUNICIPIO'
    })
    
    # Remove possíveis colunas duplicadas que tenham sido geradas na renomeação
    df_eq = df_eq.loc[:, ~df_eq.columns.duplicated()]
    
    # Garante que todas as colunas oficiais existam
    colunas_oficiais = ['COLABORADOR', 'EQUIPE', 'MUNICIPIO', 'REGIONAL', 'LATITUDE', 'LONGITUDE']
    for col in colunas_oficiais:
        if col not in df_eq.columns: 
            if col in ['LATITUDE', 'LONGITUDE']:
                df_eq[col] = 0.0
            else:
                df_eq[col] = ""
                
    # Filtra para manter APENAS as colunas oficiais (Isso limpa qualquer "lixo" antigo do banco)
    df_eq = df_eq[colunas_oficiais]

    # Limpa dados vazios e remove duplicidades para a visualização na tela
    df_levs = df_eq[['COLABORADOR', 'EQUIPE', 'MUNICIPIO']].copy()
    df_levs = df_levs[df_levs['COLABORADOR'].str.strip() != ""]
    df_levs = df_levs.drop_duplicates(subset=['COLABORADOR'])
    
    # Lista de municípios únicos já existentes no banco
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
        use_container_width=True
    )
    
    if st.button("💾 Atualizar Bases", type="primary"):
        # Mapeia as alterações feitas na tabela para o DataFrame principal
        mapeamento_mun = df_ed.set_index('COLABORADOR')['MUNICIPIO'].to_dict()
        df_eq['MUNICIPIO'] = df_eq['COLABORADOR'].map(mapeamento_mun).fillna(df_eq['MUNICIPIO'])
        
        # Salva usando Pandas de forma segura (a tabela recriada agora tem a estrutura perfeita)
        with sqlite3.connect(DB_PATH, timeout=20) as conn: 
            df_eq.to_sql('equipes', conn, if_exists='replace', index=False)
            
        load_core_data.clear() # Limpa o cache para o Painel refletir na mesma hora
        st.success("✅ Bases atualizadas com sucesso!")
        st.rerun()

    st.markdown("---")
    st.markdown("#### ➕ Cadastrar Novo Membro")
    
    # 4. Formulário de Cadastro
    with st.form("new_lev"):
        c1, c2, c3 = st.columns(3)
        nome = c1.text_input("Nome (Colaborador)", placeholder="Ex: JOÃO DA SILVA")
        eq = c2.text_input("Equipe", placeholder="Ex: EQUIPE 01")
        res = c3.text_input("Município Base", placeholder="Ex: SÃO LUÍS")
        
        if st.form_submit_button("Cadastrar", type="primary"):
            if nome and eq and res:
                # Cria a nova linha respeitando todas as colunas oficiais do template
                nova_linha = pd.DataFrame([{
                    'COLABORADOR': nome.upper().strip(),
                    'EQUIPE': eq.upper().strip(),
                    'MUNICIPIO': res.upper().strip(),
                    'REGIONAL': '',
                    'LATITUDE': 0.0,
                    'LONGITUDE': 0.0
                }])
                
                # Concatena e salva com o Pandas
                df_novo = pd.concat([df_eq, nova_linha], ignore_index=True)
                
                with sqlite3.connect(DB_PATH, timeout=20) as conn: 
                    df_novo.to_sql('equipes', conn, if_exists='replace', index=False)
                    
                load_core_data.clear()
                st.success(f"✅ O colaborador {nome.upper()} foi cadastrado e já está disponível no sistema!")
                st.rerun()
            else:
                st.warning("⚠️ Por favor, preencha todos os campos antes de cadastrar.")

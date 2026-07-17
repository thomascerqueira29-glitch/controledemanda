import streamlit as st
import pandas as pd
import sqlite3
from database import DB_PATH, load_core_data

def view_levantadores():
    if st.session_state.perfil_usuario != "ADMIN": st.error("Restrito."); return
    st.markdown("### 👷 Gestão Residencial")
    
    with sqlite3.connect(DB_PATH, timeout=10) as conn: df_eq = pd.read_sql("SELECT * FROM equipes", conn)
    
    for col in ['Levantador', 'Equipe', 'Residencia', 'Município']:
        if col not in df_eq.columns: df_eq[col] = ""
        
    df_levs = df_eq[['Levantador', 'Equipe', 'Residencia']].drop_duplicates(subset=['Levantador']).copy()
    op_mun = [""] + sorted([str(x).upper() for x in df_eq['Município'].dropna().unique() if str(x).strip() != ''])
    
    df_ed = st.data_editor(df_levs, column_config={"Levantador": st.column_config.TextColumn(disabled=True), "Equipe": st.column_config.TextColumn(disabled=True), "Residencia": st.column_config.SelectboxColumn(options=op_mun)}, hide_index=True, use_container_width=True)
    if st.button("💾 Atualizar", type="primary"):
        df_eq['Residencia'] = df_eq['Levantador'].map(df_ed.set_index('Levantador')['Residencia'].to_dict())
        with sqlite3.connect(DB_PATH, timeout=10) as conn: df_eq.to_sql('equipes', conn, if_exists='replace', index=False)
        load_core_data.clear(); st.rerun()

    st.markdown("#### ➕ Novo Membro")
    with st.form("new_lev"):
        c1, c2, c3 = st.columns(3)
        nome, eq, res = c1.text_input("Nome"), c2.text_input("Equipe"), c3.selectbox("Residência", op_mun)
        if st.form_submit_button("Cadastrar", type="primary"):
            if nome and eq and res:
                with sqlite3.connect(DB_PATH) as conn: conn.execute("INSERT INTO equipes (Levantador, Equipe, Residencia) VALUES (?, ?, ?)", (nome.upper(), eq.upper(), res))
                load_core_data.clear(); st.rerun()

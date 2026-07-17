import streamlit as st
import pandas as pd
import sqlite3
from database import DB_PATH, hash_senha

def view_acessos():
    if st.session_state.perfil_usuario != "ADMIN": st.error("Restrito."); return
    st.markdown("### 🔐 Controle de Acesso (SHA-256)")
    
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn: 
            df_usr = pd.read_sql("SELECT username, role FROM usuarios", conn)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de segurança. Tente atualizar a página. ({e})")
        return
        
    df_usr['Apagar'] = False
    
    ed_usr = st.data_editor(df_usr, hide_index=True, use_container_width=True, column_config={"username": st.column_config.TextColumn(disabled=True), "role": st.column_config.SelectboxColumn(options=["ADMIN", "LEITURA"])})
    if st.button("Salvar Permissões", type="primary"):
        with sqlite3.connect(DB_PATH) as conn:
            for _, r in ed_usr.iterrows():
                if r['Apagar'] and r['username'] != st.session_state.usuario_logado: conn.execute("DELETE FROM usuarios WHERE username=?", (r['username'],))
                elif not r['Apagar']: conn.execute("UPDATE usuarios SET role=? WHERE username=?", (r['role'], r['username']))
        st.rerun()
        
    st.markdown("#### ➕ Nova Conta")
    with st.form("n_usr"):
        c1, c2, c3 = st.columns(3)
        u, p, rol = c1.text_input("Usuário").upper(), c2.text_input("Senha", type="password"), c3.selectbox("Perfil", ["LEITURA", "ADMIN"])
        if st.form_submit_button("Criar"):
            try:
                with sqlite3.connect(DB_PATH) as conn: conn.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", (u, hash_senha(p), rol))
                st.rerun()
            except: st.error("Usuário já existe.")

import streamlit as st
import pandas as pd
import sqlite3
from database import DB_PATH, hash_senha

def view_acessos():
    if st.session_state.perfil_usuario != "ADMIN": 
        st.error("Restrito.")
        return
    
    st.markdown("### 🔐 Controle de Acesso")
    
    # Busca usuários direto com sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df_usr = pd.read_sql("SELECT username, role FROM usuarios", conn)
    except Exception as e:
        st.error(f"Erro ao ler usuários: {e}")
        return
        
    df_usr['Apagar'] = False
    
    # Editor de dados
    ed_usr = st.data_editor(
        df_usr, 
        hide_index=True, 
        use_container_width=True, 
        column_config={
            "username": st.column_config.TextColumn(disabled=True), 
            "role": st.column_config.SelectboxColumn(options=["ADMIN", "LEITURA"])
        }
    )
    
    if st.button("Salvar Permissões", type="primary"):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            for _, r in ed_usr.iterrows():
                if r['Apagar'] and r['username'] != st.session_state.usuario_logado:
                    cursor.execute("DELETE FROM usuarios WHERE username=?", (r['username'],))
                else:
                    cursor.execute("UPDATE usuarios SET role=? WHERE username=?", (r['role'], r['username']))
            conn.commit()
        st.rerun()
        
    st.markdown("#### ➕ Nova Conta")
    with st.form("n_usr"):
        c1, c2, c3 = st.columns(3)
        u = c1.text_input("Usuário").upper()
        p = c2.text_input("Senha", type="password")
        rol = c3.selectbox("Perfil", ["LEITURA", "ADMIN"])
        
        if st.form_submit_button("Criar"):
            if u and p:
                try:
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", 
                                     (u, hash_senha(p), rol))
                        conn.commit()
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Usuário já existe.")

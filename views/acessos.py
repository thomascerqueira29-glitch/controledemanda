import streamlit as st
import pandas as pd
import sqlite3

# Importamos apenas as funções que TEMOS CERTEZA que existem no seu db_config.py
from utils.db_config import get_connection, hash_password

def view_acessos():
    st.title("🛡️ Gerenciamento De Acessos")
    
    # Bloqueio de segurança
    if st.session_state.get("perfil_usuario") != "ADMIN":
        st.error("Acesso Restrito. Apenas administradores podem acessar esta página.")
        return

    st.markdown("### Usuários Cadastrados")
    
    # Leitura direta do banco para evitar erros de importação de queries.py
    try:
        conn = get_connection()
        # Seleciona as colunas, omitindo a senha por segurança
        df_users = pd.read_sql("SELECT id, username, role FROM usuarios", conn)
        conn.close()
        
        if not df_users.empty:
            st.dataframe(df_users, use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum usuário encontrado.")
    except Exception as e:
        st.error(f"Erro ao carregar usuários: {e}")
        
    st.markdown("---")
    
    st.subheader("➕ Adicionar Novo Usuário")
    with st.form("form_novo_usuario", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            novo_nome = st.text_input("Nome de Usuário (Username)")
            nova_senha = st.text_input("Senha Temporária", type="password") 
        with col2:
            novo_perfil = st.selectbox("Perfil (Role)", ["ADMIN", "USUARIO", "LEVANTADOR"])
        
        submit = st.form_submit_button("Salvar Usuário", type="primary")
        
        if submit:
            if novo_nome and nova_senha:
                try:
                    # Criptografa a senha usando a função oficial
                    senha_protegida = hash_password(nova_senha)
                    
                    # Inserção direta no banco usando a conexão limpa
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)",
                        (novo_nome.strip().upper(), senha_protegida, novo_perfil)
                    )
                    conn.commit()
                    conn.close()
                    
                    st.success(f"✅ Usuário {novo_nome.upper()} salvo com sucesso!") 
                    st.rerun() 
                except sqlite3.IntegrityError:
                    st.error("❌ Erro: Este usuário já existe no sistema.")
                except Exception as e:
                    st.error(f"❌ Erro inesperado: {e}")
            else:
                st.warning("⚠️ Por favor, preencha o nome de usuário e a senha.")

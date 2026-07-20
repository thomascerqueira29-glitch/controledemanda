import streamlit as st
import pandas as pd
import sqlite3
from utils.db_config import get_connection, get_db_path, hash_password

def get_users():
    """Lê os usuários do banco de dados centralizado."""
    conn = get_connection()
    try:
        # Não trazemos a coluna password por segurança!
        df = pd.read_sql("SELECT username, role FROM usuarios", conn)
    except Exception as e:
        st.error(f"Erro ao ler banco de dados: {e}")
        df = pd.DataFrame(columns=["username", "role"])
        
    conn.close()
    return df

def view_acessos():
    st.title("🛡️ Gerenciamento De Acessos")
    
    # Trava de segurança baseada na sessão
    if st.session_state.get("perfil_usuario") != "ADMIN":
        st.error("Acesso Restrito. Apenas administradores podem acessar esta página.")
        return

    st.markdown("### Usuários Cadastrados")
    st.info(f"Conectado ao banco de dados: `{get_db_path()}`")
    
    df_users = get_users()
    
    if not df_users.empty:
        st.dataframe(df_users, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum usuário encontrado no sistema.")
        
    st.markdown("---")
    
    # ==========================================
    # FORMULÁRIO PARA ADICIONAR NOVO USUÁRIO
    # ==========================================
    st.subheader("➕ Adicionar Novo Usuário")
    with st.form("form_novo_usuario", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            novo_nome = st.text_input("Nome de Usuário (Username)")
            # Campo de senha incluído para o novo usuário
            nova_senha = st.text_input("Senha Temporária", type="password") 
        with col2:
            novo_perfil = st.selectbox("Perfil (Role)", ["ADMIN", "USUARIO", "LEVANTADOR"])
        
        submit = st.form_submit_button("Salvar Usuário")
        
        if submit:
            if novo_nome and nova_senha:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    # Criptografa a senha antes de salvar no banco!
                    senha_protegida = hash_password(nova_senha)
                    
                    cursor.execute(
                        "INSERT INTO usuarios (username, role, password) VALUES (?, ?, ?)", 
                        (novo_nome.upper(), novo_perfil, senha_protegida)
                    )
                    conn.commit()
                    st.success(f"Usuário {novo_nome.upper()} adicionado com sucesso e senha criptografada!")
                    st.rerun() 
                except sqlite3.IntegrityError:
                    st.error("Erro: Este usuário já existe no sistema.")
                except Exception as e:
                    st.error(f"Erro inesperado: {e}")
                finally:
                    conn.close()
            else:
                st.error("Por favor, preencha o nome de usuário e a senha.")

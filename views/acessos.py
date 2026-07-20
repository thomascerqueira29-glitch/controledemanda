import streamlit as st
import sqlite3
from utils.db_config import hash_password, get_db_path
from utils.queries import get_all_users, insert_user

def view_acessos():
    st.title("🛡️ Gerenciamento De Acessos")
    
    if st.session_state.get("perfil_usuario") != "ADMIN":
        st.error("Acesso Restrito. Apenas administradores podem acessar esta página.")
        return

    st.markdown("### Usuários Cadastrados")
    st.info(f"Conectado ao banco de dados: `{get_db_path()}`")
    
    # 4. ISOLAMENTO DO SQL (Usando a função limpa do queries.py)
    try:
        df_users = get_all_users()
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
        
        submit = st.form_submit_button("Salvar Usuário")
        
        if submit:
            if novo_nome and nova_senha:
                try:
                    senha_protegida = hash_password(nova_senha)
                    # 4. ISOLAMENTO DO SQL (Inserindo via camada de serviço)
                    insert_user(novo_nome.upper(), novo_perfil, senha_protegida)
                    
                    st.toast("✅ Usuário salvo com sucesso!") # Upgrade Visual: st.toast
                    st.rerun() 
                except sqlite3.IntegrityError:
                    st.error("Erro: Este usuário já existe no sistema.")
                except Exception as e:
                    st.error(f"Erro inesperado: {e}")
            else:
                st.error("Por favor, preencha o nome de usuário e a senha.")

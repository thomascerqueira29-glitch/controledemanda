import streamlit as st
import pandas as pd
import sqlite3
import os

# Tenta localizar o banco de dados correto
if os.path.exists("controle_torre_nip.db"):
    DB_NAME = "controle_torre_nip.db"
elif os.path.exists("nip_database.db"):
    DB_NAME = "nip_database.db"
else:
    DB_NAME = "database.db"

def get_connection():
    """Cria a conexão com o banco de dados SQLite"""
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db(conn):
    """Garante que a tabela 'usuarios' exista antes de qualquer consulta."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            password TEXT
        )
    ''')
    
    # Se a tabela acabou de ser criada e está vazia, insere o usuário padrão
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (username, role, password) VALUES ('THOMAS', 'ADMIN', '123456')")
        
    conn.commit()

def get_users():
    """Lê os usuários do banco de dados, inicializando a tabela se necessário."""
    conn = get_connection()
    
    # Cria a tabela antes do Pandas tentar ler
    init_db(conn) 
    
    try:
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
    st.info(f"Conectado ao banco de dados: `{DB_NAME}`")
    
    # Leitura protegida (se não existir, é criada na hora)
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
        with col2:
            novo_perfil = st.selectbox("Perfil (Role)", ["ADMIN", "USUARIO", "LEVANTADOR"])
        
        submit = st.form_submit_button("Salvar Usuário")
        
        if submit:
            if novo_nome:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "INSERT INTO usuarios (username, role, password) VALUES (?, ?, ?)", 
                        (novo_nome.upper(), novo_perfil, "123456")
                    )
                    conn.commit()
                    st.success(f"Usuário {novo_nome.upper()} adicionado com sucesso!")
                    st.rerun() 
                except sqlite3.IntegrityError:
                    st.error("Erro: Este usuário já existe no sistema.")
                except Exception as e:
                    st.error(f"Erro inesperado: {e}")
                finally:
                    conn.close()
            else:
                st.error("Por favor, preencha o nome de usuário.")

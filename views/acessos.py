import streamlit as st
import pandas as pd
import sqlite3
from database import hash_senha

DB_PATH = 'controle_torre_nip.db'

def get_users():
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("SELECT username, role FROM usuarios", conn)

def delete_user(username):
    if username == 'THOMAS':
        st.error("Proteção de Sistema: Não é possível apagar o administrador principal.")
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM usuarios WHERE username=?", (username,))
    st.toast(f"Usuário {username} apagado com sucesso!", icon="🗑️")

def update_role(username, new_role):
    if username == 'THOMAS' and new_role != 'ADMIN':
        st.error("Proteção de Sistema: O administrador principal deve permanecer como ADMIN.")
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE usuarios SET role=? WHERE username=?", (new_role, username))
    st.toast(f"Acesso de {username} alterado para {new_role}.", icon="✅")

def create_user(username, password, role):
    username = username.strip().upper()
    with sqlite3.connect(DB_PATH) as conn:
        if conn.execute("SELECT 1 FROM usuarios WHERE username=?", (username,)).fetchone():
            st.error(f"O usuário '{username}' já existe!")
            return False
        conn.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)",
                     (username, hash_senha(password), role))
    st.success(f"Conta para {username} criada com sucesso!")
    return True

def view_acessos():
    # Proteção de Rota
    if st.session_state.get('perfil_usuario') != 'ADMIN':
        st.error("Acesso Negado: Apenas administradores podem gerenciar acessos.")
        st.stop()

    st.markdown("### 🛡️ Gerenciamento de Acessos")
    st.markdown("Controle quem tem permissão para entrar no sistema e o que podem acessar.")
    st.markdown("<br>", unsafe_allow_html=True)
    
    # =====================================================================
    # 1. TABELA DE CONTROLE DE ACESSOS (Edição Rápida Inteligente)
    # =====================================================================
    df_users = get_users()
    perfis_padrao = ["ADMIN", "COORDENAÇÃO", "LEITURA"]
    
    with st.container(border=True):
        # Cabeçalhos Padronizados
        col_usr, col_prf, col_act = st.columns([3, 3, 1.5])
        col_usr.markdown("<p style='color: #666; font-size: 14px; font-weight: bold;'>Usuário</p>", unsafe_allow_html=True)
        col_prf.markdown("<p style='color: #666; font-size: 14px; font-weight: bold;'>Perfil</p>", unsafe_allow_html=True)
        col_act.markdown("<p style='color: #666; font-size: 14px; font-weight: bold; text-align: center;'>Ações</p>", unsafe_allow_html=True)
        st.markdown("<hr style='margin-top: -10px; margin-bottom: 10px;'>", unsafe_allow_html=True)
        
        # Iteração para criar a tabela visual interativa linha a linha
        for _, row in df_users.iterrows():
            usr = row['username']
            rol = row['role']
            
            # Trava de segurança para normalizar perfis antigos que possam estar salvos no banco
            if rol not in perfis_padrao:
                if "COORD" in str(rol).upper(): rol = "COORDENAÇÃO"
                else: rol = "LEITURA"
                
            c1, c2, c3 = st.columns([3, 3, 1.5])
            
            # Usuário (Alinhado verticalmente com o centro da caixa)
            c1.markdown(f"<div style='padding-top: 8px; font-weight: 500;'>{usr}</div>", unsafe_allow_html=True)
            
            # Perfil (Dropdown de Edição Automática)
            idx_rol = perfis_padrao.index(rol)
            novo_perfil = c2.selectbox(
                f"Perfil {usr}", # Nome oculto por acessibilidade
                perfis_padrao, 
                index=idx_rol, 
                key=f"rol_{usr}", 
                label_visibility="collapsed"
            )
            
            # Gatilho automático: se mudar no selectbox, muda no banco
            if novo_perfil != rol:
                update_role(usr, novo_perfil)
                st.rerun()
                
            # Ações (Lixeira com Confirmação Flutuante)
            with c3:
                # Popover age como um botão que abre um mini-menu para evitar deleção acidental
                with st.popover("🗑️ Apagar", use_container_width=True):
                    st.markdown(f"Remover **{usr}**?")
                    if st.button("Sim, apagar conta", key=f"del_{usr}", type="primary"):
                        delete_user(usr)
                        st.rerun()
                
    st.markdown("<br><br>", unsafe_allow_html=True)

    # =====================================================================
    # 2. FORMULÁRIO DE NOVA CONTA (Layout Compacto e CTA Aprimorado)
    # =====================================================================
    st.markdown("### ➕ Nova Conta")
    
    # Restringe a largura (ocupa 60% da tela em monitores largos, 100% em celulares)
    col_form, _ = st.columns([1.5, 1]) 
    
    with col_form.container(border=True):
        new_usr = st.text_input("Usuário (Login)", placeholder="Ex: JOAO.SILVA")
        new_pwd = st.text_input("Senha", type="password", placeholder="••••••••")
        new_rol = st.selectbox("Nível de Permissão", perfis_padrao, index=2) # Padrão mais seguro: LEITURA
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Cria uma sub-coluna apenas para alinhar o CTA azulzinho no canto inferior direito
        _, col_btn = st.columns([2, 1.5])
        if col_btn.button("Criar Nova Conta", type="primary", use_container_width=True):
            if not new_usr or not new_pwd:
                st.warning("⚠️ Preencha o nome de usuário e a senha para continuar.")
            else:
                if create_user(new_usr, new_pwd, new_rol):
                    st.rerun()

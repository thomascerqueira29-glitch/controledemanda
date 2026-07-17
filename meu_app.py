import streamlit as st
import pandas as pd
import sqlite3
import streamlit_antd_components as sac
from datetime import datetime, timedelta

# 1. Importações do Motor Central (Bastidores)
from database import (DB_PATH, init_databases, init_business_db, 
                      sync_residencias_banco, hash_senha)

# 2. Importações das Telas Isoladas (Módulos)
from views.painel import view_painel_executivo
from views.governanca import view_governanca
from views.carga import view_carga
from views.levantadores import view_levantadores
from views.acessos import view_acessos
from views.simulador import view_simulador

st.set_page_config(page_title="Portal Corporativo NIP", layout="wide", page_icon="🏗️", initial_sidebar_state="expanded")

# =============================================================================
# INICIALIZAÇÃO DE BANCO DE DADOS
# =============================================================================
if 'db_initialized' not in st.session_state:
    init_databases()
    init_business_db()
    sync_residencias_banco()
    st.session_state.db_initialized = True

# =============================================================================
# SISTEMA DE LOGIN
# =============================================================================
if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None
    st.session_state.perfil_usuario = None

if st.session_state.usuario_logado is None:
    st.markdown("<h2 style='text-align: center; margin-top: 80px; color: #1A4F7C;'>🔐 Portal Corporativo NIP</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #666;'>Sistema de Governança de Redes de Distribuição</p>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Usuário").strip().upper()
            password = st.text_input("Senha", type="password")
            if st.form_submit_button("Autenticar", type="primary", use_container_width=True):
                try:
                    with sqlite3.connect(DB_PATH, timeout=10) as conn:
                        result = conn.execute("SELECT password, role FROM usuarios WHERE username=?", (username,)).fetchone()
                        if result:
                            db_pwd, role = result
                            input_hash = hash_senha(password)
                            
                            # Atualiza silenciosamente senhas antigas em texto plano para SHA-256
                            if db_pwd == input_hash or db_pwd == password:
                                if db_pwd == password: 
                                    conn.execute("UPDATE usuarios SET password=? WHERE username=?", (input_hash, username))
                                st.session_state.usuario_logado = username
                                st.session_state.perfil_usuario = role
                                conn.execute("UPDATE usuarios SET last_active = ? WHERE username = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username))
                                conn.commit()
                                st.rerun()
                            else: st.error("Credenciais inválidas.")
                        else: st.error("Acesso revogado ou inexistente.")
                except Exception as e:
                    st.error(f"Erro ao acessar banco de dados de login: {e}")
        st.info("💡 **Aviso:** Insira suas credenciais corporativas.")
    st.stop()
    
if st.session_state.get('perfil_usuario') != 'ADMIN':
    st.markdown("""<style>#MainMenu {visibility: hidden;} header {visibility: hidden;}</style>""", unsafe_allow_html=True)

# Atualiza a sessão para o usuário não cair por inatividade
try:
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("UPDATE usuarios SET last_active = ? WHERE username = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.usuario_logado))
        conn.commit()
except: pass

# =============================================================================
# MENU LATERAL E ROTEAMENTO
# =============================================================================
if 'menu_idx' not in st.session_state:
    st.session_state.menu_idx = 0

with st.sidebar:
    st.markdown("### 👤 Portal NIP")
    st.caption(f"Usuário: **{st.session_state.usuario_logado}**")
    st.caption(f"Perfil: **{st.session_state.perfil_usuario}**")
    
    if st.button("🚪 Sair / Deslogar", use_container_width=True):
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.execute("UPDATE usuarios SET last_active = NULL WHERE username = ?", (st.session_state.usuario_logado,))
            conn.commit()
        st.session_state.usuario_logado = None
        st.session_state.perfil_usuario = None
        st.rerun()

    st.markdown("---")
    
    opcoes_menu = ['Painel Executivo', 'Busca e Governança', 'Simulador de Alocação']
    icones_menu = ['pie-chart-fill', 'sliders', 'calculator-fill']
    
    if st.session_state.perfil_usuario == "ADMIN":
        opcoes_menu.insert(1, 'Carga de Lotes')
        icones_menu.insert(1, 'cloud-upload-fill')
        opcoes_menu.insert(2, 'Levantadores')
        icones_menu.insert(2, 'person-vcard-fill')
        opcoes_menu.insert(3, 'Gerenciamento de Acessos')
        icones_menu.insert(3, 'shield-lock-fill')
        
    menu_items = [sac.MenuItem(opcoes_menu[i], icon=icones_menu[i]) for i in range(len(opcoes_menu))]
    menu_selecionado = sac.menu(menu_items, index=st.session_state.menu_idx, format_func='title', size='md')
    
    if menu_selecionado in opcoes_menu:
        st.session_state.menu_idx = opcoes_menu.index(menu_selecionado)

# =============================================================================
# ROTEADOR DE TELAS (O CÉREBRO DA NOVA ARQUITETURA)
# =============================================================================
if menu_selecionado == 'Painel Executivo': view_painel_executivo()
elif menu_selecionado == 'Busca e Governança': view_governanca()
elif menu_selecionado == 'Carga de Lotes': view_carga()
elif menu_selecionado == 'Levantadores': view_levantadores()
elif menu_selecionado == 'Gerenciamento de Acessos': view_acessos()
elif menu_selecionado == 'Simulador de Alocação': view_simulador()

# =============================================================================
# HEARTBEAT OTIMIZADO
# =============================================================================
if st.session_state.usuario_logado:
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            ativos = pd.read_sql(f"SELECT username, role FROM usuarios WHERE last_active >= '{ (datetime.now() - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S') }'", conn)
        if not ativos.empty:
            st.markdown("---")
            st.markdown("#### 🟢 Usuários Online")
            st.markdown("".join([f"<span style='background-color: #d4edda; color: #155724; padding: 4px 10px; border-radius: 12px; margin-right: 8px; font-size: 13px; font-weight: bold; border: 1px solid #c3e6cb;'>👤 {r['username']} ({r['role']})</span>" for _, r in ativos.iterrows()]), unsafe_allow_html=True)
    except: pass

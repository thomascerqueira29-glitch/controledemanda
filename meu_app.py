import streamlit as st

# ==========================================
# 1. CONFIGURAÇÃO GLOBAL DA PÁGINA (Deve ser a 1ª linha do app)
# ==========================================
st.set_page_config(
    page_title="Portal NIP", 
    page_icon="🗺️", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. INICIALIZAÇÃO E IMPORTAÇÃO DO BANCO
# ==========================================
from utils.db_config import init_db, get_connection, hash_password

# Garante que as tabelas existem antes de qualquer coisa acontecer
init_db()

# ==========================================
# 3. IMPORTAÇÕES DAS TELAS (VIEWS)
# ==========================================
from views.painel import view_painel_executivo
from views.modulo_croqui import view_gerador_croqui

try: from views.carga import view_carga 
except ImportError: view_carga = None

try: from views.levantadores import view_levantadores
except ImportError: view_levantadores = None

try: from views.acessos import view_acessos
except ImportError: view_acessos = None

try: from views.governanca import view_governanca
except ImportError: view_governanca = None

try: from views.simulador import view_simulador
except ImportError: view_simulador = None

# ==========================================
# 4. CONTROLE DE SESSÃO E LOGIN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario" not in st.session_state:
    st.session_state.usuario = None
if "perfil_usuario" not in st.session_state:
    st.session_state.perfil_usuario = None

def fazer_login(username, password):
    """Verifica as credenciais no banco usando criptografia"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Criptografa a senha que o usuário digitou para comparar com o banco
    senha_criptografada = hash_password(password)
    
    cursor.execute(
        "SELECT role FROM usuarios WHERE username = ? AND password = ?", 
        (username.upper(), senha_criptografada)
    )
    resultado = cursor.fetchone()
    conn.close()
    
    if resultado:
        st.session_state.autenticado = True
        st.session_state.usuario = username.upper()
        st.session_state.perfil_usuario = resultado[0]
        return True
    return False

def tela_login():
    """Interface da Tela de Autenticação"""
    st.markdown("<h1 style='text-align: center;'>🔐 Acesso ao Portal NIP</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Faça login para continuar</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("form_login"):
            usuario_input = st.text_input("Usuário (Ex: THOMAS)")
            senha_input = st.text_input("Senha (Ex: 123456)", type="password")
            
            submit_login = st.form_submit_button("Entrar", use_container_width=True)
            
            if submit_login:
                if fazer_login(usuario_input, senha_input):
                    st.success("Acesso concedido! Carregando...")
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")

# ==========================================
# 5. APLICATIVO PRINCIPAL (MAESTRO)
# ==========================================
def main():
    # Bloqueia a execução se não estiver logado
    if not st.session_state.autenticado:
        tela_login()
        return

    # A PARTIR DAQUI, O USUÁRIO ESTÁ LOGADO
    
    # ==========================================
    # BARRA LATERAL (MENU)
    # ==========================================
    st.sidebar.markdown("### 👤 Portal NIP")
    st.sidebar.markdown(f"**Usuário:** {st.session_state.usuario}")
    st.sidebar.markdown(f"**Perfil:** {st.session_state.perfil_usuario}")
    
    if st.sidebar.button("🚪 SAIR / DESLOGAR", use_container_width=True):
        st.session_state.clear()
        st.rerun()
        
    st.sidebar.markdown("---")

    menu_opcoes = [
        "📊 Painel Executivo",
        "🗺️ Gerador de Croquis Automático", 
        "☁️ Carga De Lotes",
        "📇 Levantadores",
        "🛡️ Gerenciamento De Acessos",
        "🔍 Busca E Governança",
        "⚙️ Simulador De Alocação"
    ]
    
    pagina_selecionada = st.sidebar.radio(
        "Navegação do Sistema", 
        menu_opcoes, 
        label_visibility="collapsed"
    )

    st.sidebar.markdown("---") 

    # ==========================================
    # ROTEADOR DE TELAS
    # ==========================================
    if pagina_selecionada == "📊 Painel Executivo":
        view_painel_executivo()

    elif pagina_selecionada == "🗺️ Gerador de Croquis Automático":
        view_gerador_croqui()

    elif pagina_selecionada == "☁️ Carga De Lotes":
        if view_carga: view_carga()
        else: st.error("⚠️ view_carga não encontrada.")

    elif pagina_selecionada == "📇 Levantadores":
        if view_levantadores: view_levantadores()
        else: st.error("⚠️ view_levantadores não encontrada.")

    elif pagina_selecionada == "🛡️ Gerenciamento De Acessos":
        if view_acessos: view_acessos()
        else: st.error("⚠️ view_acessos não encontrada.")

    elif pagina_selecionada == "🔍 Busca E Governança":
        if view_governanca: view_governanca()
        else: st.error("⚠️ view_governanca não encontrada.")

    elif pagina_selecionada == "⚙️ Simulador De Alocação":
        if view_simulador: view_simulador()
        else: st.error("⚠️ view_simulador não encontrada.")

if __name__ == "__main__":
    main()

import streamlit as st

# ==========================================
# 1. CONFIGURAÇÃO GLOBAL DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Portal NIP", 
    page_icon="🗺️", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. IMPORTAÇÕES PRINCIPAIS
# ==========================================
from views.painel import view_painel_executivo
from views.modulo_croqui import view_gerador_croqui

# ==========================================
# 3. IMPORTAÇÕES DAS OUTRAS TELAS (Com base nos nomes reais dos seus arquivos)
# ==========================================
# Importando de carga.py
try:
    # Se a função dentro do carga.py tiver outro nome, mude o 'view_carga' abaixo
    from views.carga import view_carga 
except ImportError:
    view_carga = None

# Importando de levantadores.py
try:
    from views.levantadores import view_levantadores
except ImportError:
    view_levantadores = None

# Importando de acessos.py
try:
    from views.acessos import view_acessos
except ImportError:
    view_acessos = None

# Importando de governanca.py
try:
    from views.governanca import view_governanca
except ImportError:
    view_governanca = None

# Importando de simulador.py
try:
    from views.simulador import view_simulador
except ImportError:
    view_simulador = None


def main():
    # ==========================================
    # 4. CABEÇALHO DA BARRA LATERAL (PERFIL)
    # ==========================================
    st.sidebar.markdown("### 👤 Portal NIP")
    st.sidebar.markdown("**Usuário:** THOMAS")
    st.sidebar.markdown("**Perfil:** ADMIN")
    
    # Lógica do botão de Sair
    if st.sidebar.button("🚪 SAIR / DESLOGAR", use_container_width=True):
        st.session_state.clear()
        st.rerun()
        
    st.sidebar.markdown("---")

    # ==========================================
    # 5. MENU DE NAVEGAÇÃO DO SISTEMA
    # ==========================================
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
    # 6. ROTEADOR OFICIAL (O MAESTRO DAS TELAS)
    # ==========================================
    
    if pagina_selecionada == "📊 Painel Executivo":
        view_painel_executivo()

    elif pagina_selecionada == "🗺️ Gerador de Croquis Automático":
        view_gerador_croqui()

    elif pagina_selecionada == "☁️ Carga De Lotes":
        if view_carga: 
            view_carga()
        else: 
            st.error("⚠️ Verifique o nome da FUNÇÃO dentro do arquivo `views/carga.py`. Atualize a linha 25 deste arquivo (meu_app.py) para o nome correto.")

    elif pagina_selecionada == "📇 Levantadores":
        if view_levantadores: 
            view_levantadores()
        else: 
            st.error("⚠️ Verifique o nome da FUNÇÃO dentro do arquivo `views/levantadores.py`. Atualize a linha 31 deste arquivo para o nome correto.")

    elif pagina_selecionada == "🛡️ Gerenciamento De Acessos":
        if view_acessos: 
            view_acessos()
        else: 
            st.error("⚠️ Verifique o nome da FUNÇÃO dentro do arquivo `views/acessos.py`. Atualize a linha 37 deste arquivo para o nome correto.")

    elif pagina_selecionada == "🔍 Busca E Governança":
        if view_governanca: 
            view_governanca()
        else: 
            st.error("⚠️ Verifique o nome da FUNÇÃO dentro do arquivo `views/governanca.py`. Atualize a linha 43 deste arquivo para o nome correto.")

    elif pagina_selecionada == "⚙️ Simulador De Alocação":
        if view_simulador: 
            view_simulador()
        else: 
            st.error("⚠️ Verifique o nome da FUNÇÃO dentro do arquivo `views/simulador.py`. Atualize a linha 49 deste arquivo para o nome correto.")

# Verifica se é o script principal rodando
if __name__ == "__main__":
    main()

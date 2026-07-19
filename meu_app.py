import streamlit as st

# ==========================================
# 1. CONFIGURAÇÃO GLOBAL DA PÁGINA
# (Deve ser o primeiro comando do app)
# ==========================================
st.set_page_config(
    page_title="Portal NIP", 
    page_icon="🗺️", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. IMPORTAÇÃO DOS SEUS MÓDULOS (VIEWS)
# ==========================================
from views.painel import view_painel_executivo
from views.modulo_croqui import view_gerador_croqui

# Descomente e ajuste conforme os seus outros arquivos existirem:
# from views.carga_lotes import view_carga_lotes
# from views.levantadores import view_levantadores
# from views.acessos import view_acessos
# from views.governanca import view_governanca
# from views.simulador import view_simulador

def main():
    # ==========================================
    # 3. CABEÇALHO DA BARRA LATERAL (PERFIL)
    # ==========================================
    st.sidebar.markdown("### 👤 Portal NIP")
    st.sidebar.markdown("**Usuário:** THOMAS")
    st.sidebar.markdown("**Perfil:** ADMIN")
    
    # Exemplo de lógica para o botão de Sair
    if st.sidebar.button("🚪 SAIR / DESLOGAR", use_container_width=True):
        st.session_state.clear()
        st.rerun()
        
    st.sidebar.markdown("---")

    # ==========================================
    # 4. MENU DE NAVEGAÇÃO OFICIAL
    # ==========================================
    menu_opcoes = [
        "📊 Painel Executivo",
        "🗺️ Gerador de Croquis Automático",  # <-- NOVO MÓDULO AQUI!
        "☁️ Carga De Lotes",
        "📇 Levantadores",
        "🛡️ Gerenciamento De Acessos",
        "🔍 Busca E Governança",
        "⚙️ Simulador De Alocação"
    ]
    
    # O Radio Button cria o visual de abas empilhadas na lateral
    pagina_selecionada = st.sidebar.radio(
        "Navegação do Sistema", 
        menu_opcoes, 
        label_visibility="collapsed"
    )

    st.sidebar.markdown("---") # Linha divisória antes dos "Filtros Territoriais" que aparecerão no Painel

    # ==========================================
    # 5. ROTEADOR (O MÁGICO QUE TROCA AS TELAS)
    # ==========================================
    if pagina_selecionada == "📊 Painel Executivo":
        # Chama a função que constrói o painel principal
        view_painel_executivo()

    elif pagina_selecionada == "🗺️ Gerador de Croquis Automático":
        # Chama a função que constrói os croquis (100% independente do painel agora)
        view_gerador_croqui()

    elif pagina_selecionada == "☁️ Carga De Lotes":
        st.title("☁️ Carga De Lotes")
        st.info("Conecte a view de carga de lotes aqui.")
        # view_carga_lotes()

    elif pagina_selecionada == "📇 Levantadores":
        st.title("📇 Gestão de Levantadores")
        st.info("Conecte a view de levantadores aqui.")
        # view_levantadores()

    elif pagina_selecionada == "🛡️ Gerenciamento De Acessos":
        st.title("🛡️ Gerenciamento De Acessos")
        st.info("Conecte a view de acessos aqui.")
        # view_acessos()

    elif pagina_selecionada == "🔍 Busca E Governança":
        st.title("🔍 Busca E Governança")
        st.info("Conecte a view de governança aqui.")
        # view_governanca()

    elif pagina_selecionada == "⚙️ Simulador De Alocação":
        st.title("⚙️ Simulador De Alocação")
        st.info("Conecte a view do simulador aqui.")
        # view_simulador()

# Verifica se é o script principal rodando
if __name__ == "__main__":
    main()

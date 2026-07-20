import streamlit as st
from utils.queries import get_dados_painel

# ==========================================
# 1. OTIMIZAÇÃO COM CACHE 
# (Guarda na memória para carregar os mapas e dados na hora)
# ==========================================
@st.cache_data(ttl=600) # O cache expira a cada 10 minutos (600 segundos)
def carregar_dados():
    return get_dados_painel()

@st.cache_data
def gerar_csv(df):
    """Gera o arquivo CSV em cache para não reprocessar no botão de download"""
    return df.to_csv(index=False).encode('utf-8')

def view_painel_executivo():
    st.title("📊 Painel Executivo de Produtividade")
    
    # Carrega dados instantaneamente
    df = carregar_dados()
    
    # ==========================================
    # 2. LAYOUT LIMPO PARA FILTROS (Filtro flutuante)
    # ==========================================
    col_filtro, col_vazia = st.columns([1, 4])
    with col_filtro:
        with st.popover("🎛️ Filtros Territoriais e Status"):
            st.markdown("**Ajuste a visualização:**")
            
            # Select boxes dentro do popover (economiza espaço na tela)
            filtro_territorio = st.multiselect(
                "Território",
                options=df['Territorio'].unique(),
                default=df['Territorio'].unique()
            )
            filtro_status = st.multiselect(
                "Status do Croqui",
                options=df['Status'].unique(),
                default=df['Status'].unique()
            )

    # Aplicação matemática dos filtros
    df_filtrado = df[
        (df['Territorio'].isin(filtro_territorio)) &
        (df['Status'].isin(filtro_status))
    ]

    st.markdown("---")

    # ==========================================
    # UPGRADE VISUAL: Métricas de Alto Nível
    # ==========================================
    st.markdown("### 📈 Visão Geral")
    metrica1, metrica2, metrica3 = st.columns(3)
    
    total_ordens = len(df_filtrado)
    total_gerados = len(df_filtrado[df_filtrado['Status'] == 'Gerado'])
    sla_medio = round(df_filtrado['SLA_Dias'].mean(), 1) if not df_filtrado.empty else 0
    
    metrica1.metric("Total de Demandas", total_ordens)
    metrica2.metric("Croquis Gerados", total_gerados)
    metrica3.metric("SLA Médio (Dias)", f"{sla_medio} dias")

    # Tabela principal
    st.markdown("### 📋 Dados Detalhados")
    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    # ==========================================
    # 3. MÓDULO DE EXPORTAÇÃO
    # ==========================================
    st.markdown("<br>", unsafe_allow_html=True) # Espaçamento
    
    # Chama a função cacheadada para transformar o DataFrame filtrado em CSV
    csv_export = gerar_csv(df_filtrado)
    
    st.download_button(
        label="📥 Exportar Relatório Filtrado (CSV)",
        data=csv_export,
        file_name='relatorio_painel_nip.csv',
        mime='text/csv',
        type="primary", # Deixa o botão destacado na cor principal do app
        use_container_width=True
    )

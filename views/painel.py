import streamlit as st
from utils.queries import get_dados_painel

# ==========================================
# 1. OTIMIZAÇÃO COM CACHE 
# ==========================================
@st.cache_data(ttl=600)
def carregar_dados():
    return get_dados_painel()

@st.cache_data
def gerar_csv(df):
    return df.to_csv(index=False).encode('utf-8')

def view_painel_executivo():
    st.title("📊 Painel Executivo de Produtividade")
    
    df = carregar_dados()
    
    # ==========================================
    # 2. LAYOUT LIMPO PARA FILTROS
    # ==========================================
    col_filtro, col_vazia = st.columns([1, 4])
    with col_filtro:
        with st.popover("🎛️ Filtros Territoriais e Status"):
            st.markdown("**Ajuste a visualização:**")
            
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

    # Aplicação dos filtros
    df_filtrado = df[
        (df['Territorio'].isin(filtro_territorio)) &
        (df['Status'].isin(filtro_status))
    ]

    st.markdown("---")

    # ==========================================
    # 3. MÉTRICAS DE ALTO NÍVEL
    # ==========================================
    st.markdown("### 📈 Visão Geral")
    metrica1, metrica2, metrica3 = st.columns(3)
    
    total_ordens = len(df_filtrado)
    total_gerados = len(df_filtrado[df_filtrado['Status'] == 'Gerado'])
    sla_medio = round(df_filtrado['SLA_Dias'].mean(), 1) if not df_filtrado.empty else 0
    
    metrica1.metric("Total de Demandas", total_ordens)
    metrica2.metric("Croquis Gerados", total_gerados)
    metrica3.metric("SLA Médio (Dias)", f"{sla_medio} dias")

    st.markdown("### 📋 Dados Detalhados")
    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    # ==========================================
    # 4. MÓDULO DE EXPORTAÇÃO
    # ==========================================
    st.markdown("<br>", unsafe_allow_html=True)
    
    csv_export = gerar_csv(df_filtrado)
    
    st.download_button(
        label="📥 Exportar Relatório Filtrado (CSV)",
        data=csv_export,
        file_name='relatorio_painel_nip.csv',
        mime='text/csv',
        type="primary",
        use_container_width=True
    )

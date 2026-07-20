import streamlit as st
import pandas as pd
from utils.queries import get_dados_painel

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
    # 1. FILTROS FLUTUANTES (Despolui a tela)
    # ==========================================
    col_filtro, col_vazia = st.columns([1, 4])
    with col_filtro:
        with st.popover("🎛️ Filtros Territoriais e Status"):
            st.markdown("**Ajuste a visualização:**")
            filtro_territorio = st.multiselect(
                "Território", options=df['Territorio'].unique(), default=df['Territorio'].unique()
            )
            filtro_status = st.multiselect(
                "Status do Croqui", options=df['Status'].unique(), default=df['Status'].unique()
            )
            filtro_equipe = st.multiselect(
                "Equipe Alocada", options=df['Equipe_Alocada'].unique(), default=df['Equipe_Alocada'].unique()
            )

    # Aplicação matemática dos filtros
    df_filtrado = df[
        (df['Territorio'].isin(filtro_territorio)) &
        (df['Status'].isin(filtro_status)) &
        (df['Equipe_Alocada'].isin(filtro_equipe))
    ]

    st.markdown("---")

    # ==========================================
    # 2. MÉTRICAS DE ALTO NÍVEL
    # ==========================================
    metrica1, metrica2, metrica3, metrica4 = st.columns(4)
    total_ordens = len(df_filtrado)
    total_gerados = len(df_filtrado[df_filtrado['Status'] == 'Gerado'])
    sla_medio = round(df_filtrado['SLA_Dias'].mean(), 1) if not df_filtrado.empty else 0
    obras_alocadas = len(df_filtrado[df_filtrado['Equipe_Alocada'] != 'Aguardando'])
    
    metrica1.metric("Total de Demandas", total_ordens)
    metrica2.metric("Croquis Gerados", total_gerados)
    metrica3.metric("SLA Médio", f"{sla_medio} dias")
    metrica4.metric("Obras Alocadas", obras_alocadas)

    st.markdown("---")

    # ==========================================
    # 3. MAPA GEOGRÁFICO E GRÁFICOS
    # ==========================================
    col_mapa, col_grafico = st.columns([2, 1])
    
    with col_mapa:
        st.subheader("🗺️ Mapa de Distribuição das Obras")
        if not df_filtrado.empty and 'LAT' in df_filtrado.columns and 'LON' in df_filtrado.columns:
            # Exibe os pontos no mapa com as coordenadas filtradas
            st.map(df_filtrado, latitude='LAT', longitude='LON', color='#0044ff', size=150)
        else:
            st.warning("Sem dados de coordenadas para exibir no mapa.")

    with col_grafico:
        st.subheader("📈 Status vs Território")
        if not df_filtrado.empty:
            # Conta a quantidade de ordens por território
            df_grafico = df_filtrado['Territorio'].value_counts()
            st.bar_chart(df_grafico)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Conta a quantidade por Status
            df_status = df_filtrado['Status'].value_counts()
            st.bar_chart(df_status, color="#ff4b4b")

    st.markdown("---")

    # ==========================================
    # 4. ALOCAÇÃO DE OBRAS (Visão Detalhada)
    # ==========================================
    st.subheader("👷 Alocação de Obras e Equipes")
    
    # Aba interativa para organizar a visualização
    aba_dados, aba_alocacao = st.tabs(["📋 Tabela Geral", "🏗️ Visão de Alocação"])
    
    with aba_dados:
        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)
        
    with aba_alocacao:
        col_alpha, col_beta, col_aguardando = st.columns(3)
        
        with col_alpha:
            st.info("Equipe Alpha")
            st.dataframe(df_filtrado[df_filtrado['Equipe_Alocada'] == 'Equipe Alpha'][['ID_Ordem', 'Territorio']], hide_index=True)
            
        with col_beta:
            st.success("Equipe Beta")
            st.dataframe(df_filtrado[df_filtrado['Equipe_Alocada'] == 'Equipe Beta'][['ID_Ordem', 'Territorio']], hide_index=True)
            
        with col_aguardando:
            st.warning("Aguardando Alocação")
            st.dataframe(df_filtrado[df_filtrado['Equipe_Alocada'] == 'Aguardando'][['ID_Ordem', 'SLA_Dias']], hide_index=True)

    # ==========================================
    # 5. MÓDULO DE EXPORTAÇÃO
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

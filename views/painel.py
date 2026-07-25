import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# Importa as ferramentas essenciais
from database import load_core_data, SEM_LEVANTADOR

def kpi_card(title, value, subtitle="", icon="📌", border_color="#1A4F7C"):
    return f"""
    <div style="background-color: white; border-radius: 10px; padding: 15px; border-left: 6px solid {border_color}; box-shadow: 0 4px 6px rgba(0,0,0,0.05); height: 100%; border: 1px solid #f0f2f6;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
            <span style="font-size: 14px; font-weight: 800; color: #444; text-transform: uppercase; letter-spacing: 0.5px;">{title}</span>
            <span style="font-size: 20px;">{icon}</span>
        </div>
        <h2 style="margin: 0; color: #111; font-size: 38px; font-weight: 800; line-height: 1.1;">{value}</h2>
        {f'<p style="margin: 8px 0 0 0; font-size: 13px; font-weight: 600; color: #6c757d;">{subtitle}</p>' if subtitle else ''}
    </div>
    """

def calcular_saude_dados(df):
    if df.empty or 'LATITUDE' not in df.columns or 'LONGITUDE' not in df.columns: return 0.0
    has_lat = df['LATITUDE'].astype(str).str.strip().replace(['nan', 'None', '', '<NA>', '0', '0.0'], np.nan).notna()
    has_lon = df['LONGITUDE'].astype(str).str.strip().replace(['nan', 'None', '', '<NA>', '0', '0.0'], np.nan).notna()
    return (has_lat & has_lon).mean() * 100

def view_painel_executivo():
    """Painel Executivo Focado em KPIs e Gráficos"""
    st.markdown("### 📈 Visão Global de Produtividade")
    
    # Sincronização Automática: Puxa sempre a versão mais atual do DB (Governança)
    df_notas_db, df_equipes_db, resumo_levantadores, levantadores_criticos, _, _, _, _ = load_core_data()
    
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")
    
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        df_notas_db = df_notas_db[df_notas_db['LEVANTADOR'].str.strip().str.upper() == usuario_limpo]
        df_equipes_db = df_equipes_db[df_equipes_db['Levantador'].str.strip().str.upper() == usuario_limpo]
        st.info(f"👁️ **Modo Foco (RLS Ativo):** Exibindo apenas a base e as obras atribuídas a você ({usuario_atual}).")
    
    if len(df_notas_db) == 0:
        st.warning("Nenhum dado encontrado para exibição nos filtros atuais ou banco vazio.")
        return

    # --- CÁLCULO DOS KPIS ---
    total_obras = len(df_notas_db)
    
    # Conta apenas os levantadores reais da aba equipes
    if not df_equipes_db.empty and 'Levantador' in df_equipes_db.columns:
        qtd_equipes = df_equipes_db['Levantador'].replace([SEM_LEVANTADOR, '', 'nan', 'None'], pd.NA).dropna().nunique()
    else:
        qtd_equipes = 0

    fila_count = len(df_notas_db[df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR]) if 'LEVANTADOR' in df_notas_db.columns else 0
    qtd_risco = len(levantadores_criticos) if levantadores_criticos else 0
    taxa_dados = calcular_saude_dados(df_notas_db)

    # --- RENDERIZAÇÃO DOS KPIS ---
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(kpi_card("Obras", total_obras, "Em execução / Cadastradas", "🏗️", "#1A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Equipes", qtd_equipes, "Ativas em campo", "👥", "#8B5CF6"), unsafe_allow_html=True)
    k3.markdown(kpi_card("Fila", fila_count, "Aguardando alocação", "⏳", "#F59E0B"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Risco", qtd_risco, "Abaixo da meta", "🚨", "#EF4444" if qtd_risco > 0 else "#10B981"), unsafe_allow_html=True)
    k5.markdown(kpi_card("Data Quality", f"{taxa_dados:.1f}%", "Precisão Geoespacial", "🎯", "#EC4899"), unsafe_allow_html=True)
    
    st.markdown("<br><hr>", unsafe_allow_html=True)
    
    # Lixos genéricos para limpar os gráficos
    lixos = ['0', '0.0', 'nan', 'SEM LEVANTADOR', '', 'None', '<NA>']
    
    # --- LINHA 1 DE GRÁFICOS (Município e Tipo de Nota) ---
    c_g1, c_g2 = st.columns([1.2, 1])
    
    with c_g1:
        # Gráfico 1: Obras por Município (Template Bot)
        df_mun = df_notas_db.copy()
        if 'MUNICIPIO' in df_mun.columns:
            df_mun = df_mun[~df_mun['MUNICIPIO'].astype(str).str.strip().isin(lixos)]
            municipios_count = df_mun.groupby('MUNICIPIO').size().reset_index(name='Qtd_Obras')
            
            if not municipios_count.empty:
                fig1 = px.bar(
                    municipios_count.sort_values('Qtd_Obras', ascending=False).head(15).sort_values('Qtd_Obras'), 
                    x='Qtd_Obras', y='MUNICIPIO', orientation='h', title="Top 15 Concentração por Município", 
                    text='Qtd_Obras', color_discrete_sequence=['#1A4F7C']
                )
                fig1.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
                fig1.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, xaxis=dict(showticklabels=False), yaxis=dict(showticklabels=True))
                st.plotly_chart(fig1, use_container_width=True)
            
    with c_g2:
        # Gráfico 2: Obras por Tipo de Nota (Template Bot - Coluna I)
        if 'TIPO NOTA' in df_notas_db.columns:
            df_tipo = df_notas_db.copy()
            df_tipo = df_tipo[~df_tipo['TIPO NOTA'].astype(str).str.strip().isin(lixos)]
            tipo_count = df_tipo.groupby('TIPO NOTA').size().reset_index(name='Qtd_Obras')
            
            if not tipo_count.empty:
                fig2 = px.bar(
                    tipo_count.sort_values('Qtd_Obras', ascending=False).head(10), 
                    x='TIPO NOTA', y='Qtd_Obras', title="Distribuição por Tipo de Nota", 
                    text='Qtd_Obras', color_discrete_sequence=['#10B981']
                )
                fig2.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
                fig2.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, yaxis=dict(showticklabels=False))
                st.plotly_chart(fig2, use_container_width=True)
                
    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- LINHA 2 DE GRÁFICOS (Status List) ---
    c_g3, _ = st.columns([1, 0.01]) # Utiliza praticamente a tela toda para o gráfico de Status
    
    with c_g3:
        # Gráfico 3: Obras por Status List (Template Bot - Coluna D)
        if 'STATUS LIST' in df_notas_db.columns:
            df_status = df_notas_db.copy()
            df_status = df_status[~df_status['STATUS LIST'].astype(str).str.strip().isin(lixos)]
            status_count = df_status.groupby('STATUS LIST').size().reset_index(name='Qtd_Obras')
            
            if not status_count.empty:
                fig3 = px.bar(
                    status_count.sort_values('Qtd_Obras', ascending=False), 
                    x='STATUS LIST', y='Qtd_Obras', title="Volume de Obras por Status List", 
                    text='Qtd_Obras', color_discrete_sequence=['#F59E0B']
                )
                fig3.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
                fig3.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, yaxis=dict(showticklabels=False))
                st.plotly_chart(fig3, use_container_width=True)

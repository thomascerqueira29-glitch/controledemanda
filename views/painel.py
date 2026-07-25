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
    
    # Sincronização Automática: Comunicação Direta com Governança (Lê em tempo real)
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
    
    # Busca dinâmica da coluna EQUIPE (Planilha Levantadores_bot)
    qtd_equipes = 0
    if not df_equipes_db.empty:
        col_equipe = next((c for c in df_equipes_db.columns if str(c).strip().upper() == 'EQUIPE'), None)
        col_levantador = next((c for c in df_equipes_db.columns if str(c).strip().upper() in ['LEVANTADOR', 'NOME', 'TECNICO']), None)
        
        if col_equipe:
            qtd_equipes = df_equipes_db[col_equipe].replace([SEM_LEVANTADOR, '', 'nan', 'None'], pd.NA).dropna().nunique()
        elif col_levantador:
            qtd_equipes = df_equipes_db[col_levantador].replace([SEM_LEVANTADOR, '', 'nan', 'None'], pd.NA).dropna().nunique()

    # Identificação da coluna Levantador no DB de notas (Pode estar vazia dependendo do template)
    coluna_levantador_db = next((col for col in df_notas_db.columns if str(col).strip().upper() in ['LEVANTADOR', 'EQUIPE']), None)
    if coluna_levantador_db:
        fila_count = len(df_notas_db[df_notas_db[coluna_levantador_db] == SEM_LEVANTADOR])
    else:
        fila_count = total_obras

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
    c_g1, c_g2 = st.columns([1.5, 1])
    
    with c_g1:
        # Primeiro Gráfico: Obras por Município
        coluna_municipio = next((col for col in df_notas_db.columns if str(col).strip().upper() in ['MUNICIPIO', 'MUNICÍPIO']), None)
        if coluna_municipio:
            df_mun = df_notas_db.copy()
            df_mun = df_mun[~df_mun[coluna_municipio].astype(str).str.strip().isin(lixos)]
            municipios_count = df_mun.groupby(coluna_municipio).size().reset_index(name='Qtd_Obras')
            
            if not municipios_count.empty:
                fig1 = px.bar(
                    municipios_count.sort_values('Qtd_Obras', ascending=False).head(15).sort_values('Qtd_Obras'), 
                    x='Qtd_Obras', y=coluna_municipio, orientation='h', title="Top 15 Concentração por Município", 
                    text='Qtd_Obras', color_discrete_sequence=['#1A4F7C']
                )
                fig1.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
                fig1.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, xaxis=dict(showticklabels=False), yaxis=dict(showticklabels=True))
                st.plotly_chart(fig1, use_container_width=True)
            
    with c_g2:
        # Segundo Gráfico: Obras por Tipo de Nota (Busca Inteligente da Coluna I)
        coluna_tipo_nota = next((col for col in df_notas_db.columns if str(col).strip().upper() in ['TIPO NOTA', 'TIPO DE NOTA', 'TIPO LIGACAO', 'TIPO LIGAÇÃO']), None)
        if coluna_tipo_nota:
            df_tipo = df_notas_db.copy()
            df_tipo = df_tipo[~df_tipo[coluna_tipo_nota].astype(str).str.strip().isin(lixos)]
            tipo_count = df_tipo.groupby(coluna_tipo_nota).size().reset_index(name='Qtd_Obras')
            
            if not tipo_count.empty:
                fig2 = px.bar(
                    tipo_count.sort_values('Qtd_Obras', ascending=False).head(15), 
                    x=coluna_tipo_nota, y='Qtd_Obras', title="Distribuição por Tipo de Nota", 
                    text='Qtd_Obras', color_discrete_sequence=['#10B981']
                )
                fig2.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
                fig2.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, yaxis=dict(showticklabels=False))
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("ℹ️ A coluna de 'TIPO NOTA' não foi encontrada na sua base de dados oficial.")
                
    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- LINHA 2 DE GRÁFICOS (Status List - Largura Total) ---
    coluna_status_list = next((col for col in df_notas_db.columns if str(col).strip().upper() in ['STATUS LIST']), None)
    if coluna_status_list:
        df_status = df_notas_db.copy()
        df_status = df_status[~df_status[coluna_status_list].astype(str).str.strip().isin(lixos)]
        status_count = df_status.groupby(coluna_status_list).size().reset_index(name='Qtd_Obras')
        
        if not status_count.empty:
            fig3 = px.bar(
                status_count.sort_values('Qtd_Obras', ascending=False), 
                x=coluna_status_list, y='Qtd_Obras', title="Volume de Obras por Status List", 
                text='Qtd_Obras', color_discrete_sequence=['#F59E0B']
            )
            fig3.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
            fig3.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, yaxis=dict(showticklabels=False))
            st.plotly_chart(fig3, use_container_width=True)

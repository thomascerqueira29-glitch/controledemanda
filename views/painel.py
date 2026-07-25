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

def view_painel_executivo():
    """Painel Executivo Focado em KPIs e Gráficos"""
    st.markdown("### 📈 Visão Global de Produtividade")
    
    # =================================================================
    # 1. SINCRONIZAÇÃO EM TEMPO REAL COM A GOVERNANÇA (Limpa Cache)
    # =================================================================
    load_core_data.clear() # <- O segredo da sincronização instantânea!
    df_notas_db, df_equipes_db, _, _, _, _, _, _ = load_core_data()
    
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")
    
    # Filtro RLS: Se for um técnico logado, ele só verá os números das obras atribuídas a ele
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        
        # Filtra a base de notas
        col_lev_db = next((c for c in df_notas_db.columns if str(c).strip().upper() in ['LEVANTADOR', 'EQUIPE']), None)
        if col_lev_db:
            df_notas_db = df_notas_db[df_notas_db[col_lev_db].str.strip().str.upper() == usuario_limpo]
            
        # Filtra a base de equipes
        col_colab_eq = next((c for c in df_equipes_db.columns if str(c).strip().upper() in ['COLABORADOR', 'LEVANTADOR']), None)
        if col_colab_eq:
            df_equipes_db = df_equipes_db[df_equipes_db[col_colab_eq].str.strip().str.upper() == usuario_limpo]
            
        st.info(f"👁️ **Modo Foco (RLS Ativo):** Exibindo apenas a base e as obras atribuídas a você ({usuario_atual}).")
    
    if len(df_notas_db) == 0:
        st.warning("Nenhum dado encontrado para exibição. Importe um lote ou atualize a Governança.")
        return

    # =================================================================
    # 2. CÁLCULO DOS 4 KPIS EXATOS (Baseados no Template Bot)
    # =================================================================
    
    # KPI 1: Quantidade total e EXATA de obras que constam na aba governança
    total_obras = len(df_notas_db)
    
    # KPI 2: Quantidade total de levantadores ativos (Base Levantadores_base)
    qtd_equipes = 0
    if not df_equipes_db.empty:
        col_colaborador = next((c for c in df_equipes_db.columns if str(c).strip().upper() in ['COLABORADOR', 'LEVANTADOR', 'NOME', 'TECNICO']), None)
        if col_colaborador:
            qtd_equipes = df_equipes_db[col_colaborador].replace([SEM_LEVANTADOR, '', 'nan', 'None'], pd.NA).dropna().nunique()

    # KPI 3: Quantidade de obras dos tipos CCF, DIF, MGD, MTP, ASC, SID
    tipos_alvo = ['CCF', 'DIF', 'MGD', 'MTP', 'ASC', 'SID']
    coluna_tipo_nota = next((col for col in df_notas_db.columns if str(col).strip().upper() in ['TIPO NOTA', 'TIPO DE NOTA', 'TIPO LIGACAO', 'TIPO LIGAÇÃO']), None)
    
    qtd_tipos_especificos = 0
    if coluna_tipo_nota:
        mask_tipos = df_notas_db[coluna_tipo_nota].astype(str).str.strip().str.upper().isin(tipos_alvo)
        qtd_tipos_especificos = int(mask_tipos.sum())

    # KPI 4: Quantidade de obras em 'Pre Analise' ou 'Liberado para Levantamentos'
    status_alvo = ['PRE ANALISE', 'PRÉ ANÁLISE', 'PRÉ ANALISE', 'PRE ANÁLISE', 'LIBERADO PARA LEVANTAMENTOS', 'LIBERADO PARA LEVANTAMENTO']
    # Busca dinamicamente por Status Atual ou Status List
    coluna_status = next((col for col in df_notas_db.columns if str(col).strip().upper() in ['STATUS ATUAL (LEVANTAMENTO)', 'STATUS LIST']), None)
    
    qtd_status_especifico = 0
    if coluna_status:
        mask_status = df_notas_db[coluna_status].astype(str).str.strip().str.upper().isin(status_alvo)
        qtd_status_especifico = int(mask_status.sum())

    # =================================================================
    # 3. RENDERIZAÇÃO DOS 4 CARDS
    # =================================================================
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi_card("Obras Totais", total_obras, "Base da Governança", "🏗️", "#1A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Levantadores", qtd_equipes, "Ativos na Planilha Base", "👥", "#8B5CF6"), unsafe_allow_html=True)
    k3.markdown(kpi_card("Obras Prioritárias", qtd_tipos_especificos, "CCF, DIF, MGD, MTP, ASC, SID", "🎯", "#F59E0B"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Pré-Análise / Liberado", qtd_status_especifico, "Status da Demanda", "⚡", "#10B981"), unsafe_allow_html=True)
    
    st.markdown("<br><hr>", unsafe_allow_html=True)
    
    # Lixos genéricos para não poluir os gráficos
    lixos = ['0', '0.0', 'nan', 'SEM LEVANTADOR', '', 'None', '<NA>']
    
    # =================================================================
    # 4. RENDERIZAÇÃO DOS GRÁFICOS (Município e Tipo de Nota)
    # =================================================================
    c_g1, c_g2 = st.columns([1.5, 1])
    
    with c_g1:
        # Gráfico 1: Obras por Município
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
        # Gráfico 2: Obras por Tipo de Nota
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
    
    # =================================================================
    # 5. RENDERIZAÇÃO DO GRÁFICO (Status List - Largura Total)
    # =================================================================
    if coluna_status:
        df_status = df_notas_db.copy()
        df_status = df_status[~df_status[coluna_status].astype(str).str.strip().isin(lixos)]
        status_count = df_status.groupby(coluna_status).size().reset_index(name='Qtd_Obras')
        
        if not status_count.empty:
            fig3 = px.bar(
                status_count.sort_values('Qtd_Obras', ascending=False), 
                x=coluna_status, y='Qtd_Obras', title=f"Volume de Obras por Status: {coluna_status.title()}", 
                text='Qtd_Obras', color_discrete_sequence=['#F59E0B']
            )
            fig3.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
            fig3.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, yaxis=dict(showticklabels=False))
            st.plotly_chart(fig3, use_container_width=True)

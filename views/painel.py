import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import sqlite3

# Importa o caminho do banco de dados oficial
from database import DB_PATH, SEM_LEVANTADOR

def kpi_card(title, value, subtitle="", icon="📌", border_color="#1A4F7C"):
    return f"""
    <div style="background-color: white; border-radius: 10px; padding: 15px; border-left: 6px solid {border_color}; box-shadow: 0 4px 6px rgba(0,0,0,0.05); height: 100%; border: 1px solid #f0f2f6;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
            <span style="font-size: 14px; font-weight: 800; color: #444; text-transform: uppercase; letter-spacing: 0.5px;">{title}</span>
            <span style="font-size: 20px;">{icon}</span>
        </div>
        <h2 style="margin: 0; color: #111; font-size: 34px; font-weight: 800; line-height: 1.2; white-space: nowrap;">{value}</h2>
        {f'<p style="margin: 8px 0 0 0; font-size: 13px; font-weight: 600; color: #6c757d;">{subtitle}</p>' if subtitle else ''}
    </div>
    """

def view_painel_executivo():
    """Painel Executivo Focado em KPIs e Gráficos com Sync em Tempo Real"""
    st.markdown("### 📈 Visão Global de Produtividade")
    
    # =====================================================================
    # 1. LEITURA DIRETA DO BANCO (SEM CACHE) - 100% SINCRONIZADO
    # =====================================================================
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df_notas_db = pd.read_sql("SELECT * FROM notas", conn)
            df_equipes_db = pd.read_sql("SELECT * FROM equipes", conn)
    except Exception as e:
        st.error(f"Erro ao conectar com o banco de dados oficial: {e}")
        return

    if df_notas_db.empty:
        st.warning("A base de obras está vazia. Importe um lote ou atualize a Governança.")
        return

    # Segurança RLS (Proteção por nível de usuário se um técnico logar)
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")
    
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        
        col_lev_db = next((c for c in df_notas_db.columns if str(c).strip().upper() in ['LEVANTADOR', 'EQUIPE']), None)
        if col_lev_db:
            df_notas_db = df_notas_db[df_notas_db[col_lev_db].str.strip().str.upper() == usuario_limpo]
            
        col_colab_eq = next((c for c in df_equipes_db.columns if str(c).strip().upper() in ['COLABORADOR', 'LEVANTADOR']), None)
        if col_colab_eq:
            df_equipes_db = df_equipes_db[df_equipes_db[col_colab_eq].str.strip().str.upper() == usuario_limpo]
            
        st.info(f"👁️ **Modo Foco (RLS Ativo):** Exibindo apenas a base e as obras atribuídas a você ({usuario_atual}).")

    # =====================================================================
    # 2. CÁLCULO DOS 4 KPIS EXATOS (Varredura Inteligente)
    # =====================================================================
    
    # KPI 1: Obras Totais (Exatamente as linhas da aba Governança)
    total_obras = len(df_notas_db)
    
    # KPI 2: Quantidade de Levantadores (Aba Levantadores - planilha base)
    qtd_equipes = 0
    if not df_equipes_db.empty:
        col_colaborador = next((c for c in df_equipes_db.columns if str(c).strip().upper() in ['COLABORADOR', 'LEVANTADOR', 'NOME', 'TECNICO']), None)
        if col_colaborador:
            qtd_equipes = df_equipes_db[col_colaborador].replace([SEM_LEVANTADOR, '', 'nan', 'None'], pd.NA).dropna().nunique()

    # KPI 3: Varredura de Obras Prioritárias (CCF, DIF, MGD, MTP, ASC, SID)
    tipos_alvo = ['CCF', 'DIF', 'MGD', 'MTP', 'ASC', 'SID']
    colunas_de_tipo = [c for c in df_notas_db.columns if 'TIPO' in str(c).upper()]
    mask_tipos = pd.Series(False, index=df_notas_db.index)
    
    for col in colunas_de_tipo:
        s_norm = df_notas_db[col].astype(str).str.strip().str.upper()
        mask_tipos = mask_tipos | s_norm.isin(tipos_alvo)
        
    qtd_tipos_especificos = int(mask_tipos.sum())

    # KPI 4: Varredura Divivida (Pré-Análise x Liberado)
    # Busca em qualquer coluna que tenha a palavra "STATUS"
    colunas_de_status = [c for c in df_notas_db.columns if 'STATUS' in str(c).upper()]
    
    mask_pre = pd.Series(False, index=df_notas_db.index)
    mask_lib = pd.Series(False, index=df_notas_db.index)
    
    for col in colunas_de_status:
        # Normaliza a string (Maiúscula e sem acento para garantir o Match)
        s_norm = df_notas_db[col].astype(str).str.strip().str.upper()
        s_norm = s_norm.str.replace('Á', 'A').str.replace('É', 'E').str.replace('Í', 'I').str.replace('Ó', 'O').str.replace('Ú', 'U').str.replace('Â', 'A').str.replace('Ê', 'E').str.replace('Ç', 'C')
        
        # Faz as duas contagens separadamente
        mask_pre = mask_pre | s_norm.str.contains('PRE ANALISE', na=False)
        mask_lib = mask_lib | s_norm.str.contains('LIBERADO', na=False)
        
    qtd_pre_analise = int(mask_pre.sum())
    qtd_liberado = int(mask_lib.sum())
    
    # Monta a string visual que será inserida no card
    valor_dividido = f"<span style='color: #F59E0B;'>{qtd_pre_analise}</span><span style='font-size: 14px; color: #666;'> PA</span> <span style='color: #ddd; font-weight: 300;'>|</span> <span style='color: #10B981;'>{qtd_liberado}</span><span style='font-size: 14px; color: #666;'> LIB</span>"

    # =====================================================================
    # 3. RENDERIZAÇÃO DOS 4 CARDS (Garantindo 4 colunas)
    # =====================================================================
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi_card("Obras Totais", total_obras, "Base da Governança", "🏗️", "#1A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Levantadores", qtd_equipes, "Ativos na Planilha Base", "👥", "#8B5CF6"), unsafe_allow_html=True)
    k3.markdown(kpi_card("Obras Prioritárias", qtd_tipos_especificos, "CCF, DIF, MGD, MTP, ASC, SID", "🎯", "#F59E0B"), unsafe_allow_html=True)
    
    # Aplica o valor dividido e o título STATUS SISCO
    k4.markdown(kpi_card("Status Sisco", valor_dividido, "Pré-Análise / Liberado", "⚡", "#10B981"), unsafe_allow_html=True)
    
    st.markdown("<br><hr>", unsafe_allow_html=True)

    # =====================================================================
    # 4. GRÁFICOS DIRECIONADOS
    # =====================================================================
    lixos = ['0', '0.0', 'nan', 'SEM LEVANTADOR', '', 'None', '<NA>']
    
    # --- LINHA 1 DE GRÁFICOS (1: Município | 2: Tipo de Nota) ---
    c_g1, c_g2 = st.columns([1.5, 1])
    
    with c_g1:
        # Gráfico 1: Quantidade de obras totais por município
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
        # Gráfico 2: Quantidade de obras de acordo com TIPO NOTA
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
            st.info("ℹ️ A coluna de 'TIPO NOTA' não foi encontrada na sua base.")
                
    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- LINHA 2 DE GRÁFICOS (3: Status List - Largura Total) ---
    # Prioridade para STATUS LIST no gráfico, como solicitado anteriormente
    coluna_status_grafico = next((col for col in df_notas_db.columns if str(col).strip().upper() in ['STATUS LIST', 'STATUS ATUAL (LEVANTAMENTO)', 'STATUS SAP']), None)
    
    if coluna_status_grafico:
        df_status = df_notas_db.copy()
        df_status = df_status[~df_status[coluna_status_grafico].astype(str).str.strip().isin(lixos)]
        status_count = df_status.groupby(coluna_status_grafico).size().reset_index(name='Qtd_Obras')
        
        if not status_count.empty:
            fig3 = px.bar(
                status_count.sort_values('Qtd_Obras', ascending=False), 
                x=coluna_status_grafico, y='Qtd_Obras', title=f"Volume de Obras por: {coluna_status_grafico.title()}", 
                text='Qtd_Obras', color_discrete_sequence=['#F59E0B']
            )
            fig3.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
            fig3.update_layout(margin=dict(l=10, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, yaxis=dict(showticklabels=False))
            st.plotly_chart(fig3, use_container_width=True)

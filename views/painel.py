import streamlit as st
import pandas as pd
import plotly.express as px

# Importa as ferramentas essenciais
from database import load_core_data, calcular_sla_vetorizado, SEM_LEVANTADOR, STATUS_PRODUTIVIDADE

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
    
    df_notas_db, df_equipes_db, resumo_levantadores, levantadores_criticos, _, _, _, _ = load_core_data()
    
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")
    
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        df_notas_db = df_notas_db[df_notas_db['LEVANTADOR'].str.strip().str.upper() == usuario_limpo]
        df_equipes_db = df_equipes_db[df_equipes_db['Levantador'].str.strip().str.upper() == usuario_limpo]
        resumo_levantadores = resumo_levantadores[resumo_levantadores['Levantador'].str.strip().str.upper() == usuario_limpo]
        st.info(f"👁️ **Modo Foco (RLS Ativo):** Exibindo apenas a base e as obras atribuídas a você ({usuario_atual}).")
    
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("Nenhum dado encontrado para exibição nos filtros atuais ou banco vazio.")
        return

    try: df_notas_db = calcular_sla_vetorizado(df_notas_db)
    except: pass
        
    # --- KPIs ---
    k1, k2, k3, k4, k5 = st.columns(5)
    
    k1.markdown(kpi_card("Obras", int(resumo_levantadores['Total_Obras_Real'].sum()), "Em execução", "🏗️", "#1A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Equipes", len(resumo_levantadores), "Ativas em campo", "👥", "#10B981"), unsafe_allow_html=True)
    fila_count = 0 if perfil_atual == "LEVANTADOR" else len(df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))])
    k3.markdown(kpi_card("Fila", fila_count, "Aguardando", "⏳", "#F59E0B"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Risco", len(levantadores_criticos), "Abaixo da meta", "🚨", "#EF4444" if len(levantadores_criticos) > 0 else "#10B981"), unsafe_allow_html=True)
    taxa_dados = calcular_saude_dados(df_notas_db)
    k5.markdown(kpi_card("Data Quality", f"{taxa_dados:.1f}%", "Precisão Geoespacial", "🎯", "#8B5CF6"), unsafe_allow_html=True)
    
    st.markdown("<br><hr>", unsafe_allow_html=True)
    
    # --- GRÁFICOS ---
    c_g1, c_g2 = st.columns(2)
    with c_g1:
        df_mun = df_notas_db.copy()
        lixos = ['0', '0.0', 'nan', 'SEM LEVANTADOR', '', 'None']
        df_mun = df_mun[~df_mun['MUNICIPIO'].astype(str).str.strip().isin(lixos)]
        
        if not df_mun.empty and 'MUNICIPIO' in df_mun.columns:
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
        try:
            df_sla = df_notas_db[df_notas_db['Status_SLA'].isin(['No Prazo', 'Vencimento Próximo', 'Vencida'])]
            if not df_sla.empty:
                df_g = df_sla.groupby(['REGIONAL', 'Status_SLA']).size().reset_index(name='Qtd')
                df_g['Status_SLA'] = pd.Categorical(df_g['Status_SLA'], categories=['No Prazo', 'Vencimento Próximo', 'Vencida'], ordered=True)
                
                fig2 = px.bar(
                    df_g.sort_values(['REGIONAL', 'Status_SLA']), 
                    x='REGIONAL', y='Qtd', color='Status_SLA', 
                    title="Monitoramento de SLA Regional", 
                    barmode='stack', text='Qtd', 
                    color_discrete_map={'No Prazo': '#10B981', 'Vencimento Próximo': '#F59E0B', 'Vencida': '#EF4444'}
                )
                fig2.update_traces(textposition='inside', textfont=dict(size=12, color='white'))
                fig2.update_layout(margin=dict(l=20, r=20, t=40, b=40), xaxis_title=None, yaxis=dict(showticklabels=False), xaxis=dict(showticklabels=True), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, title=None))
                st.plotly_chart(fig2, use_container_width=True)
        except Exception: pass

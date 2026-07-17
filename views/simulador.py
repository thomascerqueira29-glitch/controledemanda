import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from database import load_core_data, SEM_LEVANTADOR

def view_simulador():
    st.markdown("<h2 style='text-align: center; color: #1A4F7C;'>Simulador de Alocação de Levantadores</h2>", unsafe_allow_html=True)
    _, df_e, _, _, _, _, _, _ = load_core_data()
    
    if 'Regional' not in df_e.columns: df_e['Regional'] = ""
    df_e['Regional'] = df_e['Regional'].replace(['', 'nan', 'None', '<NA>'], 'NÃO INFORMADA').astype(str).str.upper()
    df_e['Levantador'] = df_e['Levantador'].astype(str).str.upper()

    mun_total = df_e.groupby('Regional')['Município'].nunique().reset_index(name='Total Municípios')
    valid_lev_mask = ((df_e['Levantador'] != SEM_LEVANTADOR) & (df_e['Levantador'].notna()) & (~df_e['Levantador'].isin(['', '0', 'NAN', 'NONE'])))
    mun_com = df_e[valid_lev_mask].groupby('Regional')['Município'].nunique().reset_index(name='Com Levantador')
    lev_atuais = df_e[valid_lev_mask].groupby('Regional')['Levantador'].nunique().reset_index(name='Levantadores Atuais')

    df_sim = mun_total.merge(mun_com, on='Regional', how='left').fillna(0)
    df_sim = df_sim.merge(lev_atuais, on='Regional', how='left').fillna(0)
    df_sim['Sem Levantador'] = df_sim['Total Municípios'] - df_sim['Com Levantador']
    df_sim['Levantadores Atuais'] = df_sim['Levantadores Atuais'].astype(int)
    df_sim['Capacidade Media'] = np.where(df_sim['Levantadores Atuais'] > 0, df_sim['Com Levantador'] / df_sim['Levantadores Atuais'], 0)

    c1, c2, c3, c4 = st.columns(4)
    ph_mun = c1.empty()
    ph_com = c2.empty()
    ph_sem = c3.empty()
    ph_cob = c4.empty()
    
    st.write("")
    st.markdown("<h4 style='background-color: #333; color: white; padding: 5px 10px; border-radius: 5px;'>Dados por Regional (Edite os Novos Levantadores)</h4>", unsafe_allow_html=True)

    df_sim['Novos Levantadores'] = 0
    col_config = {
        "Regional": st.column_config.TextColumn("Regional", disabled=True),
        "Total Municípios": st.column_config.NumberColumn("Total Municípios", disabled=True),
        "Com Levantador": st.column_config.NumberColumn("Com Levantador", disabled=True),
        "Sem Levantador": st.column_config.NumberColumn("Sem Levantador", disabled=True),
        "Levantadores Atuais": st.column_config.NumberColumn("Levantadores Atuais", disabled=True),
        "Novos Levantadores": st.column_config.NumberColumn("Novos Levantadores", min_value=0, step=1),
        "Capacidade Media": None 
    }

    df_edited = st.data_editor(df_sim, column_config=col_config, use_container_width=True, hide_index=True, key='editor_simulador')

    df_edited['Municipios Ganhos'] = np.floor(df_edited['Novos Levantadores'] * df_edited['Capacidade Media']).astype(int)
    df_edited['Municipios Ganhos'] = df_edited[['Municipios Ganhos', 'Sem Levantador']].min(axis=1) 
    df_edited['Gap Restante'] = df_edited['Sem Levantador'] - df_edited['Municipios Ganhos']
    df_edited['Cobertura %'] = np.where(df_edited['Total Municípios'] > 0, ((df_edited['Com Levantador'] + df_edited['Municipios Ganhos']) / df_edited['Total Municípios']) * 100, 0)
    
    total_mun_novo = int(df_edited['Total Municípios'].sum())
    total_com_novo = int(df_edited['Com Levantador'].sum() + df_edited['Municipios Ganhos'].sum())
    total_sem_novo = int(df_edited['Gap Restante'].sum())
    cob_atual_nova = (total_com_novo / total_mun_novo * 100) if total_mun_novo > 0 else 0

    ph_mun.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Total Municípios</b><br><span style='font-size:24px'>{total_mun_novo}</span></div>", unsafe_allow_html=True)
    ph_com.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Municípios Cobertos</b><br><span style='font-size:24px'>{total_com_novo}</span></div>", unsafe_allow_html=True)
    ph_sem.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Municípios Sem Levantador</b><br><span style='font-size:24px'>{total_sem_novo}</span></div>", unsafe_allow_html=True)
    ph_cob.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Cobertura Atual</b><br><span style='font-size:24px'>{cob_atual_nova:.1f}%</span></div>", unsafe_allow_html=True)

    st.markdown("<h4 style='background-color: #4A4F7C; color: white; padding: 5px 10px; margin-top: 20px; border-radius: 5px;'>Projeção Atualizada e Representatividade</h4>", unsafe_allow_html=True)
    col_proj_tab, col_proj_chart = st.columns([2.5, 1.5])
    
    with col_proj_tab:
        df_proj = df_edited[['Regional', 'Total Municípios', 'Com Levantador', 'Sem Levantador', 'Levantadores Atuais', 'Novos Levantadores', 'Gap Restante', 'Cobertura %']].copy()
        linha_total = pd.DataFrame([{
            'Regional': 'TOTAL ESTADO',
            'Total Municípios': df_proj['Total Municípios'].sum(),
            'Com Levantador': df_proj['Com Levantador'].sum(),
            'Sem Levantador': df_proj['Sem Levantador'].sum(),
            'Levantadores Atuais': df_proj['Levantadores Atuais'].sum(),
            'Novos Levantadores': df_proj['Novos Levantadores'].sum(),
            'Gap Restante': df_proj['Gap Restante'].sum(),
            'Cobertura %': ((df_proj['Com Levantador'].sum() + df_edited['Municipios Ganhos'].sum()) / df_proj['Total Municípios'].sum() * 100) if df_proj['Total Municípios'].sum() > 0 else 0
        }])
        df_proj = pd.concat([df_proj, linha_total], ignore_index=True)
        df_proj['Cobertura %'] = df_proj['Cobertura %'].apply(lambda x: f"{x:.1f}%")

        def colorir_cobertura(val):
            try:
                percentual = float(val.replace('%', ''))
                if percentual < 50.0: return 'background-color: #F8D7DA; color: #721C24; font-weight: bold;'
                elif percentual < 100.0: return 'background-color: #FFF3CD; color: #856404; font-weight: bold;'
                else: return 'background-color: #D4EDDA; color: #155724; font-weight: bold;'
            except ValueError: return ''
                
        styled_proj = df_proj.style.map(lambda v: 'color: #D9534F; font-weight: bold;' if (isinstance(v, (int, float)) and v > 0) else '', subset=['Gap Restante']).map(colorir_cobertura, subset=['Cobertura %'])
        st.dataframe(styled_proj, use_container_width=True, hide_index=True)

    with col_proj_chart:
        df_edited['Gap Restante'] = pd.to_numeric(df_edited['Gap Restante'], errors='coerce').fillna(0)
        df_chart = df_edited[df_edited['Gap Restante'] > 0]
        if not df_chart.empty and df_chart['Gap Restante'].sum() > 0:
            fig_rosca = px.pie(df_chart, names='Regional', values='Gap Restante', hole=0.55, title="Gap de Cobertura por Regional")
            fig_rosca.update_traces(textinfo='percent', hoverinfo='label+value', marker=dict(line=dict(color='#000000', width=1)))
            fig_rosca.update_layout(margin=dict(t=40, b=0, l=0, r=0), legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5))
            st.plotly_chart(fig_rosca, use_container_width=True, config={'displayModeBar': False})
        else:
            st.success("✅ 100% de Cobertura Atingida!")

import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap, MarkerCluster
import plotly.express as px
import html
import tempfile
import re

# Importa as ferramentas pesadas do nosso motor central
from database import (load_core_data, vectorized_haversine, 
                      parse_kmz_advanced, calcular_sla_vetorizado, 
                      SEM_LEVANTADOR, STATUS_PRODUTIVIDADE)

# Injeção de CSS para melhorar a Proporção e Legibilidade Global
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }
    .stSelectbox label, .stFileUploader label, .stRadio label { font-size: 15px !important; font-weight: 600 !important; color: #1A4F7C !important; }
</style>
""", unsafe_allow_html=True)

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

def normalizar_municipios(series_mun):
    s = series_mun.astype(str).str.upper()
    s = s.str.replace(r'[ÁÀÂÃÄ]', 'A', regex=True)
    s = s.str.replace(r'[ÉÈÊË]', 'E', regex=True)
    s = s.str.replace(r'[ÍÌÎÏ]', 'I', regex=True)
    s = s.str.replace(r'[ÓÒÔÕÖ]', 'O', regex=True)
    s = s.str.replace(r'[ÚÙÛÜ]', 'U', regex=True)
    s = s.str.replace(r'Ç', 'C', regex=True)
    return s.str.split('-').str[0].str.strip()

def render_mapa_otimizado(df_notas_mapa, df_eq_mapa_view, criticos_tuple, caminho_camada_temp, mapa_lat, mapa_lon, estilo_mapa, visao_cores):
    mapa = folium.Map(location=[-5.2, -45.0], zoom_start=7, tiles=None)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
        attr='Esri', name='Visão de Satélite', overlay=False, control=True
    ).add_to(mapa)
    folium.TileLayer('OpenStreetMap', name='Ruas Padrão', overlay=False, control=True).add_to(mapa)

    if caminho_camada_temp:
        gdf_lines, gdf_points, bounds = parse_kmz_advanced(caminho_camada_temp)
        if not gdf_lines.empty: folium.GeoJson(gdf_lines[['Name', 'geometry']], name="Rede Elétrica", style_function=lambda f: {'color': '#1A4F7C', 'weight': 2.5}).add_to(mapa)
        if not gdf_points.empty: folium.GeoJson(gdf_points[['Name', 'geometry']], name="Equipamentos", marker=folium.CircleMarker(radius=3, color='#dc3545')).add_to(mapa)
        if bounds is not None: mapa.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    fg_equipes = folium.FeatureGroup(name="📍 Bases dos Técnicos")
    if not df_eq_mapa_view.empty:
        df_eq = df_eq_mapa_view.copy()
        if 'LATITUDE' in df_eq.columns and 'LONGITUDE' in df_eq.columns:
            df_eq['Lat'] = pd.to_numeric(df_eq['LATITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            df_eq['Lon'] = pd.to_numeric(df_eq['LONGITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            for _, row in df_eq.dropna(subset=['Lat', 'Lon']).iterrows():
                lev = str(row.get('LEVANTADOR', row.get('Levantador', '')))
                cor = 'red' if lev in criticos_tuple else 'green'
                folium.Marker([row['Lat'], row['Lon']], icon=folium.Icon(color=cor, icon='home', prefix='fa'), tooltip=f"Base: {html.escape(lev)}").add_to(fg_equipes)
    fg_equipes.add_to(mapa)

    if not df_notas_mapa.empty:
        df_ob = df_notas_mapa.copy()
        df_ob.columns = [str(c).upper().strip() for c in df_ob.columns]
        
        if 'LATITUDE' in df_ob.columns and 'LONGITUDE' in df_ob.columns:
            df_ob['Lat_Mapa'] = pd.to_numeric(df_ob['LATITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            df_ob['Lon_Mapa'] = pd.to_numeric(df_ob['LONGITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
        else:
            df_ob['Lat_Mapa'] = df_ob['Lon_Mapa'] = np.nan

        mask_miss = df_ob['Lat_Mapa'].isna() | df_ob['Lon_Mapa'].isna()
        if mask_miss.any() and 'MUNICIPIO' in df_ob.columns:
            dict_ma_lat = {
                'SAO LUIS': -2.53, 'IMPERATRIZ': -5.52, 'SAO JOSE DE RIBAMAR': -2.56, 'TIMON': -5.09,
                'CAXIAS': -4.86, 'ACAILANDIA': -4.94, 'CODO': -4.45, 'BACABAL': -4.22, 'BALSAS': -7.53,
                'SANTA INES': -3.66, 'PINHEIRO': -2.52, 'CHAPADINHA': -3.73, 'SANTA LUZIA': -4.05,
                'BURITICUPU': -4.33, 'GRAJAU': -5.81, 'ITAPECURU MIRIM': -3.39, 'COROATA': -4.12,
                'BARREIRINHAS': -2.75, 'TUTOIA': -2.76, 'VARGEM GRANDE': -3.53, 'VIANA': -3.22,
                'ZE DOCA': -3.27, 'LAGO DA PEDRA': -4.33, 'COELHO NETO': -4.25, 'PRESIDENTE DUTRA': -5.28,
                'SAO DOMINGOS DO MARANHAO': -5.57, 'ARAIOSES': -2.89, 'SANTA HELENA': -2.23, 'ESTREITO': -6.55,
                'PEDREIRAS': -4.57, 'ROSARIO': -2.93, 'SAO JOAO DOS PATOS': -6.49, 'DOM PEDRO': -5.03,
                'BURITI': -3.87, 'TUNTUM': -5.25, 'COLINAS': -6.02, 'AMARANTE DO MARANHAO': -5.57,
                'BOM JARDIM': -3.56, 'PARNARAMA': -4.31, 'MATOES': -5.52, 'ITINGA DO MARANHAO': -4.36,
                'PENALVA': -3.28, 'ALTO ALEGRE DO PINDARE': -3.68, 'TURIACU': -1.66, 'CURURUPU': -1.82,
                'VITORIA DO MEARIM': -3.46, 'CARUTAPERA': -1.19, 'VITORINO FREIRE': -4.32, 'MIRINZAL': -2.06,
                'RAPOSA': -2.42, 'BARRA DO CORDA': -5.50, 'PACO DO LUMIAR': -2.53
            }
            dict_ma_lon = {
                'SAO LUIS': -44.30, 'IMPERATRIZ': -47.47, 'SAO JOSE DE RIBAMAR': -44.05, 'TIMON': -42.83,
                'CAXIAS': -43.35, 'ACAILANDIA': -47.50, 'CODO': -43.89, 'BACABAL': -44.78, 'BALSAS': -46.03,
                'SANTA INES': -45.38, 'PINHEIRO': -45.08, 'CHAPADINHA': -43.35, 'SANTA LUZIA': -45.90,
                'BURITICUPU': -46.40, 'GRAJAU': -46.13, 'ITAPECURU MIRIM': -44.35, 'COROATA': -43.98,
                'BARREIRINHAS': -42.82, 'TUTOIA': -42.27, 'VARGEM GRANDE': -43.92, 'VIANA': -45.00,
                'ZE DOCA': -45.65, 'LAGO DA PEDRA': -45.13, 'COELHO NETO': -42.93, 'PRESIDENTE DUTRA': -44.49,
                'SAO DOMINGOS DO MARANHAO': -44.38, 'ARAIOSES': -41.90, 'SANTA HELENA': -45.29, 'ESTREITO': -47.45,
                'PEDREIRAS': -44.60, 'ROSARIO': -44.23, 'SAO JOAO DOS PATOS': -43.70, 'DOM PEDRO': -44.46,
                'BURITI': -43.08, 'TUNTUM': -44.64, 'COLINAS': -44.24, 'AMARANTE DO MARANHAO': -46.74,
                'BOM JARDIM': -45.98, 'PARNARAMA': -43.09, 'MATOES': -43.19, 'ITINGA DO MARANHAO': -47.53,
                'PENALVA': -45.17, 'ALTO ALEGRE DO PINDARE': -45.85, 'TURIACU': -45.37, 'CURURUPU': -44.86,
                'VITORIA DO MEARIM': -44.87, 'CARUTAPERA': -46.02, 'VITORINO FREIRE': -45.23, 'MIRINZAL': -44.75,
                'RAPOSA': -44.09, 'BARRA DO CORDA': -45.24, 'PACO DO LUMIAR': -44.10
            }
            
            mapa_lat_c = {normalizar_municipios(pd.Series([k])).iloc[0]: v for k, v in mapa_lat.items()} if mapa_lat else {}
            mapa_lon_c = {normalizar_municipios(pd.Series([k])).iloc[0]: v for k, v in mapa_lon.items()} if mapa_lon else {}
            dict_ma_lat.update(mapa_lat_c); dict_ma_lon.update(mapa_lon_c)
            
            muns_norm = normalizar_municipios(df_ob.loc[mask_miss, 'MUNICIPIO'])
            df_ob.loc[mask_miss, 'Lat_Mapa'] = muns_norm.map(dict_ma_lat)
            df_ob.loc[mask_miss, 'Lon_Mapa'] = muns_norm.map(dict_ma_lon)
            
        mask_still_miss = df_ob['Lat_Mapa'].isna() | df_ob['Lon_Mapa'].isna()
        if mask_still_miss.any():
            df_ob.loc[mask_still_miss, 'Lat_Mapa'] = -5.2
            df_ob.loc[mask_still_miss, 'Lon_Mapa'] = -45.0
            
        np.random.seed(42)
        raio = 0.012  
        r_dist = raio * np.sqrt(np.random.uniform(0, 1, len(df_ob)))
        angulos = np.random.uniform(0, 2 * np.pi, len(df_ob))
        
        df_ob['Lat_Mapa'] += r_dist * np.cos(angulos)
        df_ob['Lon_Mapa'] += r_dist * np.sin(angulos)
        
        def get_s(val):
            if pd.isna(val): return "-"
            s = str(val).strip()
            return "-" if s.lower() in ['nan', 'none', '<na>', ''] else html.escape(s)

        if estilo_mapa == "Calor (Heatmap)":
            heat_data = [[row['Lat_Mapa'], row['Lon_Mapa']] for _, row in df_ob.iterrows()]
            HeatMap(heat_data, name="🔥 Densidade de Obras", radius=15, blur=20, max_zoom=10).add_to(mapa)
            
        elif estilo_mapa == "Agrupamentos (Clusters)":
            cluster_obras = MarkerCluster(name=f"🏗️ Obras Agrupadas ({len(df_ob)})", maxClusterRadius=45, spiderfyOnMaxZoom=True)
            for row in df_ob.to_dict('records'):
                if visao_cores == "Prazos (SLA)":
                    sla_status = row.get('STATUS_SLA', row.get('STATUS SLA', 'No Prazo'))
                    if 'Vencida' in str(sla_status): cor_marcador = 'darkred'
                    elif 'Próximo' in str(sla_status) or 'Proximo' in str(sla_status): cor_marcador = 'orange'
                    else: cor_marcador = 'green'
                else:
                    lev_obra = get_s(row.get('LEVANTADOR'))
                    if lev_obra == '-': lev_obra = SEM_LEVANTADOR
                    cor_marcador = 'orange' if lev_obra == SEM_LEVANTADOR else ('red' if lev_obra in criticos_tuple else 'blue')
                
                info_html = f"""
                <div style="min-width: 250px; font-size: 13px; line-height: 1.5; font-family: sans-serif;">
                    <b>Regional:</b> {get_s(row.get('REGIONAL'))} <br>
                    <b>Município:</b> {get_s(row.get('MUNICIPIO'))} <br>
                    <b>Protocolo:</b> {get_s(row.get('PROTOCOLO'))} <br>
                    <b>Solicitante:</b> {get_s(row.get('NOME DO SOLICITANTE'))} <br>
                    <b>Status List:</b> {get_s(row.get('STATUS LIST'))} <br>
                    <b>Status SAP:</b> {get_s(row.get('STATUS SAP'))} <br>
                    <b>SLA:</b> {get_s(row.get('STATUS_SLA', row.get('STATUS SLA', '-')))} <br>
                    <b>ID Sisco:</b> {get_s(row.get('ID SISCO'))} <br>
                    <b>Tipo Ligação:</b> {get_s(row.get('TIPO LIGACAO'))}
                </div>
                """
                folium.Marker(location=[row['Lat_Mapa'], row['Lon_Mapa']], icon=folium.Icon(color=cor_marcador, icon='wrench', prefix='fa'), popup=folium.Popup(info_html, max_width=350)).add_to(cluster_obras)
            cluster_obras.add_to(mapa)

        else:
            camada_obras = folium.FeatureGroup(name=f"🏗️ Pinos Individuais ({len(df_ob)})")
            for row in df_ob.to_dict('records'):
                if visao_cores == "Prazos (SLA)":
                    sla_status = row.get('STATUS_SLA', row.get('STATUS SLA', 'No Prazo'))
                    if 'Vencida' in str(sla_status): cor_marcador = 'darkred'
                    elif 'Próximo' in str(sla_status) or 'Proximo' in str(sla_status): cor_marcador = 'orange'
                    else: cor_marcador = 'green'
                else:
                    lev_obra = get_s(row.get('LEVANTADOR'))
                    if lev_obra == '-': lev_obra = SEM_LEVANTADOR
                    cor_marcador = 'orange' if lev_obra == SEM_LEVANTADOR else ('red' if lev_obra in criticos_tuple else 'blue')
                
                info_html = f"""
                <div style="min-width: 250px; font-size: 13px; line-height: 1.5; font-family: sans-serif;">
                    <b>Regional:</b> {get_s(row.get('REGIONAL'))} <br>
                    <b>Município:</b> {get_s(row.get('MUNICIPIO'))} <br>
                    <b>Protocolo:</b> {get_s(row.get('PROTOCOLO'))} <br>
                    <b>Solicitante:</b> {get_s(row.get('NOME DO SOLICITANTE'))} <br>
                    <b>Status List:</b> {get_s(row.get('STATUS LIST'))} <br>
                    <b>Status SAP:</b> {get_s(row.get('STATUS SAP'))} <br>
                    <b>SLA:</b> {get_s(row.get('STATUS_SLA', row.get('STATUS SLA', '-')))} <br>
                    <b>ID Sisco:</b> {get_s(row.get('ID SISCO'))} <br>
                    <b>Tipo Ligação:</b> {get_s(row.get('TIPO LIGACAO'))}
                </div>
                """
                folium.Marker(location=[row['Lat_Mapa'], row['Lon_Mapa']], icon=folium.Icon(color=cor_marcador, icon='wrench', prefix='fa'), popup=folium.Popup(info_html, max_width=350)).add_to(camada_obras)
            camada_obras.add_to(mapa)

    folium.LayerControl(position='bottomright').add_to(mapa)
    st_folium(mapa, use_container_width=True, height=650, returned_objects=[])

def view_painel_executivo():
    df_notas_db, df_equipes_db, resumo_levantadores, levantadores_criticos, todos_levantadores, mapa_lat, mapa_lon, _ = load_core_data()
    
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")
    
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        df_notas_db = df_notas_db[df_notas_db['LEVANTADOR'].str.strip().str.upper() == usuario_limpo]
        df_equipes_db = df_equipes_db[df_equipes_db['Levantador'].str.strip().str.upper() == usuario_limpo]
        resumo_levantadores = resumo_levantadores[resumo_levantadores['Levantador'].str.strip().str.upper() == usuario_limpo]
        todos_levantadores = [usuario_limpo]
        st.info(f"👁️ **Modo Foco (RLS Ativo):** Exibindo apenas a base e as obras atribuídas a você ({usuario_atual}).")
    
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("Nenhum dado encontrado para exibição nos filtros atuais ou banco vazio.")
        return

    try: df_notas_db = calcular_sla_vetorizado(df_notas_db)
    except: pass
        
    st.markdown("### 📈 Visão Global de Produtividade")
    k1, k2, k3, k4, k5 = st.columns(5)
    
    k1.markdown(kpi_card("Obras", int(resumo_levantadores['Total_Obras_Real'].sum()), "Em execução", "🏗️", "#1A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Equipes", len(resumo_levantadores), "Ativas em campo", "👥", "#10B981"), unsafe_allow_html=True)
    fila_count = 0 if perfil_atual == "LEVANTADOR" else len(df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))])
    k3.markdown(kpi_card("Fila", fila_count, "Aguardando", "⏳", "#F59E0B"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Risco", len(levantadores_criticos), "Abaixo da meta", "🚨", "#EF4444" if len(levantadores_criticos) > 0 else "#10B981"), unsafe_allow_html=True)
    
    taxa_dados = calcular_saude_dados(df_notas_db)
    k5.markdown(kpi_card("Data Quality", f"{taxa_dados:.1f}%", "Precisão Geoespacial", "🎯", "#8B5CF6"), unsafe_allow_html=True)
    
    st.markdown("<br><hr>", unsafe_allow_html=True)
    
    # Renderização Gráfica Integrada
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

    st.markdown("---")
    st.markdown("### 🗺️ Roteirização Geoespacial")
    
    with st.sidebar:
        st.markdown("### 🔍 Filtros Territoriais")
        
        lista_tecnicos_limpa = sorted(list(set([str(x).strip() for x in df_notas_db['LEVANTADOR'].unique() if str(x).strip().upper() not in ['0', '0.0', 'NAN', 'NONE', '']])))
        lista_sap_limpa = sorted(list(set([str(x).strip().upper() for x in df_notas_db['STATUS SAP'].unique() if str(x).strip().upper() not in ['NAN', 'NONE', '']])))
        lista_list_limpa = sorted(list(set([str(x).strip().upper() for x in df_notas_db['STATUS LIST'].unique() if str(x).strip().upper() not in ['NAN', 'NONE', '']])))
        lista_reg_limpa = sorted(list(set([str(x).strip().upper() for x in df_notas_db['REGIONAL'].unique() if str(x).strip().upper() not in ['NAN', 'NONE', '']])))
        lista_mun_limpa = sorted(list(set([str(x).strip().upper() for x in df_notas_db['MUNICIPIO'].unique() if str(x).strip().upper() not in ['NAN', 'NONE', '']])))

        op_map_lev = ["TODOS"] + lista_tecnicos_limpa
        op_map_reg = ["TODOS"] + lista_reg_limpa
        op_map_mun = ["TODOS"] + lista_mun_limpa
        op_map_sap = ["TODOS"] + lista_sap_limpa
        op_map_list = ["TODOS"] + lista_list_limpa

        if perfil_atual == "LEVANTADOR":
            f_lev = usuario_atual.upper()
            st.markdown(f"**Técnico:**<br>{f_lev}", unsafe_allow_html=True)
        else:
            f_lev = st.selectbox("Técnico / Equipe", op_map_lev)
            
        f_reg = st.selectbox("Regional", op_map_reg)
        f_mun = st.selectbox("Município Alvo", op_map_mun)
        f_sap = st.selectbox("Status SAP", op_map_sap)
        f_list = st.selectbox("Status List", op_map_list)
        
        st.markdown("---")
        st.markdown("### ⚙️ Configurações do Mapa")
        
        estilo_mapa = st.radio("Visualização do Mapa:", [
            "Agrupamentos (Clusters)", 
            "Pinos Individuais", 
            "Calor (Heatmap)"
        ])
        
        visao_cores = "Produtividade"
        if estilo_mapa in ["Pinos Individuais", "Agrupamentos (Clusters)"]:
            visao_cores = st.radio("Colorir pinos por:", ["Técnico (Produtividade)", "Prazos (SLA)"])
        
        st.markdown("---")
        camada = st.file_uploader("Sobrepor Camada (KML/KMZ)", type=['kml', 'kmz'])

    df_m = df_notas_db.copy()
    
    if f_lev != "TODOS": df_m = df_m[df_m['LEVANTADOR'].astype(str).str.strip() == f_lev]
    if f_reg != "TODOS": df_m = df_m[df_m['REGIONAL'].astype(str).str.strip().str.upper() == f_reg]
    if f_mun != "TODOS": df_m = df_m[df_m['MUNICIPIO'].astype(str).str.strip().str.upper() == f_mun]
    if f_sap != "TODOS": df_m = df_m[df_m['STATUS SAP'].astype(str).str.strip().str.upper() == f_sap]
    if f_list != "TODOS": df_m = df_m[df_m['STATUS LIST'].astype(str).str.strip().str.upper() == f_list]
    
    df_m = df_m[~df_m['LEVANTADOR'].astype(str).isin(['0', '0.0'])]
    
    st.caption(f"📍 Renderizando **{len(df_m)}** obras baseadas nos filtros selecionados na barra lateral.")
    
    camada_p = None
    if camada:
        ext = camada.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp: 
            tmp.write(camada.getvalue())
            camada_p = tmp.name

    df_e = df_equipes_db.copy()
    if f_lev != "TODOS": df_e = df_e[df_e['Levantador'].astype(str).str.upper() == f_lev]
    
    with st.spinner("Construindo renderização geográfica do terreno..."):
        render_mapa_otimizado(df_m, df_e, tuple(levantadores_criticos), camada_p, mapa_lat, mapa_lon, estilo_mapa, visao_cores)

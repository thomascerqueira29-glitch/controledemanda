import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster, HeatMap
import plotly.express as px
import io
import html
import tempfile
from datetime import datetime

# Importa as ferramentas pesadas do nosso motor central
from database import (load_core_data, save_notas_to_db, vectorized_haversine, 
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
            dict_ma_lat = {'SAO LUIS': -2.53, 'IMPERATRIZ': -5.52, 'SAO JOSE DE RIBAMAR': -2.56, 'TIMON': -5.09, 'CAXIAS': -4.86, 'ACAILANDIA': -4.94, 'CODO': -4.45, 'BACABAL': -4.22, 'BALSAS': -7.53, 'SANTA INES': -3.66}
            dict_ma_lon = {'SAO LUIS': -44.30, 'IMPERATRIZ': -47.47, 'SAO JOSE DE RIBAMAR': -44.05, 'TIMON': -42.83, 'CAXIAS': -43.35, 'ACAILANDIA': -47.50, 'CODO': -43.89, 'BACABAL': -44.78, 'BALSAS': -46.03, 'SANTA INES': -45.38}
            mapa_lat_c = {str(k).upper(): v for k, v in mapa_lat.items()} if mapa_lat else {}
            mapa_lon_c = {str(k).upper(): v for k, v in mapa_lon.items()} if mapa_lon else {}
            dict_ma_lat.update(mapa_lat_c); dict_ma_lon.update(mapa_lon_c)
            
            muns = df_ob.loc[mask_miss, 'MUNICIPIO'].astype(str).str.upper().str.replace('Ó','O').str.replace('Í','I').str.replace('Á','A').str.replace('Ã','A').str.replace('É','E').str.split('-').str[0].str.strip()
            df_ob.loc[mask_miss, 'Lat_Mapa'] = muns.map(dict_ma_lat)
            df_ob.loc[mask_miss, 'Lon_Mapa'] = muns.map(dict_ma_lon)
            
        mask_still_miss = df_ob['Lat_Mapa'].isna() | df_ob['Lon_Mapa'].isna()
        if mask_still_miss.any():
            df_ob.loc[mask_still_miss, 'Lat_Mapa'] = -5.2
            df_ob.loc[mask_still_miss, 'Lon_Mapa'] = -45.0
            
        np.random.seed(42)
        df_ob['Lat_Mapa'] += np.random.uniform(-0.010, 0.010, len(df_ob))
        df_ob['Lon_Mapa'] += np.random.uniform(-0.010, 0.010, len(df_ob))
        
        if estilo_mapa == "Calor (Heatmap)":
            heat_data = [[row['Lat_Mapa'], row['Lon_Mapa']] for _, row in df_ob.iterrows()]
            HeatMap(heat_data, name="🔥 Densidade de Obras", radius=15, blur=20, max_zoom=10).add_to(mapa)
        else:
            cluster_obras = MarkerCluster(name=f"🏗️ Demandas Ativas ({len(df_ob)} obras)")
            
            def get_s(val):
                if pd.isna(val): return "-"
                s = str(val).strip()
                return "-" if s.lower() in ['nan', 'none', '<na>', ''] else html.escape(s)

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
                folium.Marker(
                    location=[row['Lat_Mapa'], row['Lon_Mapa']], 
                    icon=folium.Icon(color=cor_marcador, icon='wrench', prefix='fa'), 
                    popup=folium.Popup(info_html, max_width=350)
                ).add_to(cluster_obras)
                
            cluster_obras.add_to(mapa)

    folium.LayerControl(position='bottomright').add_to(mapa)
    st_folium(mapa, use_container_width=True, height=650, returned_objects=[])

def view_painel_executivo():
    df_notas_db, df_equipes_db, resumo_levantadores, levantadores_criticos, todos_levantadores, mapa_lat, mapa_lon, municipios_por_levantador = load_core_data()
    
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("O banco de dados está vazio. Realize uma carga em lote para popular o painel.")
        return

    try: df_notas_db = calcular_sla_vetorizado(df_notas_db)
    except: pass
        
    st.markdown("### 📈 Visão Global de Produtividade")
    k1, k2, k3, k4, k5 = st.columns(5)
    
    k1.markdown(kpi_card("Obras", int(resumo_levantadores['Total_Obras_Real'].sum()), "Em execução", "🏗️", "#1A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Equipes", len(resumo_levantadores), "Ativas em campo", "👥", "#10B981"), unsafe_allow_html=True)
    k3.markdown(kpi_card("Fila", len(df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))]), "Aguardando", "⏳", "#F59E0B"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Risco", len(levantadores_criticos), "Abaixo da meta", "🚨", "#EF4444" if len(levantadores_criticos) > 0 else "#10B981"), unsafe_allow_html=True)
    
    taxa_dados = calcular_saude_dados(df_notas_db)
    k5.markdown(kpi_card("Data Quality", f"{taxa_dados:.1f}%", "Precisão Geoespacial", "🎯", "#8B5CF6"), unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_t1, col_t2 = st.columns([1.5, 1])
    with col_t1:
        st.markdown("#### 📋 Desempenho e Alocação")
        st.dataframe(resumo_levantadores[['Levantador', 'Equipe', 'Total_Obras_Real']].sort_values('Total_Obras_Real', ascending=False), 
                     use_container_width=True, hide_index=True, height=280, 
                     column_config={"Levantador": "Técnico", "Equipe": "Equipe", "Total_Obras_Real": st.column_config.ProgressColumn("Carga (Meta: 45)", format="%d", min_value=0, max_value=45)})
        
    with col_t2:
        st.markdown("#### ⚡ Gestão de Fila")
        with st.container(border=True):
            c_sel, c_inf = st.columns([3, 1])
            lev_sel = c_sel.selectbox("Selecione o Técnico:", todos_levantadores, label_visibility="collapsed")
            if st.session_state.get('last_lev') != lev_sel:
                st.session_state.assign_step = 0; st.session_state.show_demanda = False; st.session_state.last_lev = lev_sel
                
            obras_do_lev = int(resumo_levantadores[resumo_levantadores['Levantador'] == lev_sel]['Total_Obras_Real'].iloc[0]) if not resumo_levantadores[resumo_levantadores['Levantador'] == lev_sel].empty else 0
            cor_badge = "#e8f4f8" if obras_do_lev >= 45 else "#fce8e8"
            c_inf.markdown(f"<div style='text-align:center; background:{cor_badge}; border-radius:5px; padding:6px;'><b style='font-size:18px;'>{obras_do_lev}</b><br><small style='font-size:10px; font-weight:bold;'>OBRAS</small></div>", unsafe_allow_html=True)
            
            st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
            
            if st.session_state.get('perfil_usuario') == "ADMIN":
                if obras_do_lev < 45:
                    if st.session_state.get('assign_step', 0) == 0:
                        if st.button(f"➕ Atribuir {45 - obras_do_lev} Obras", use_container_width=True, type="primary"): st.session_state.assign_step = 1; st.rerun()
                    elif st.session_state.assign_step == 1:
                        st.info("Confirmar geo-atribuição?")
                        c_a, c_b = st.columns(2)
                        if c_a.button("✅ Sim", use_container_width=True, type="primary"):
                            df_livres = df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))].copy()
                            if len(df_livres) == 0: st.error("Fila Vazia!"); st.session_state.assign_step = 0
                            else:
                                tr = df_equipes_db[df_equipes_db['Levantador'] == lev_sel]
                                r_lat = mapa_lat.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Latitude']).replace(',','.'))
                                r_lon = mapa_lon.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Longitude']).replace(',','.'))
                                
                                df_livres['L_Lat'] = pd.to_numeric(df_livres['MUNICIPIO'].map(mapa_lat), errors='coerce')
                                df_livres['L_Lon'] = pd.to_numeric(df_livres['MUNICIPIO'].map(mapa_lon), errors='coerce')
                                df_livres['D_KM'] = vectorized_haversine(r_lat, r_lon, df_livres['L_Lat'], df_livres['L_Lon'])
                                
                                att = df_livres.sort_values('D_KM').head(45 - obras_do_lev).index
                                df_update = df_notas_db.copy()
                                df_update.loc[att, 'LEVANTADOR'] = lev_sel
                                if save_notas_to_db(df_update): st.success("Viculado!"); st.session_state.assign_step = 2; load_core_data.clear(); st.rerun()
                        if c_b.button("❌ Não", use_container_width=True): st.session_state.assign_step = 0; st.rerun()
                    elif st.session_state.assign_step == 2:
                        st.success("✅ Atribuição Concluída.")
                        if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"): st.session_state.show_demanda = True; st.session_state.assign_step = 0; st.rerun()
                else:
                    st.success("✅ Meta Atingida.")
                    if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"): st.session_state.show_demanda = True
            else: 
                st.warning("🔒 Atribuição restrita.")
            
    if st.session_state.get('show_demanda', False):
        st.markdown("---")
        df_demanda = df_notas_db[(df_notas_db['LEVANTADOR'] == lev_sel) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))].copy()
        if len(df_demanda) > 0:
            tr = df_equipes_db[df_equipes_db['Levantador'] == lev_sel]
            r_lat = mapa_lat.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Latitude']).replace(',','.'))
            r_lon = mapa_lon.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Longitude']).replace(',','.'))
            
            df_demanda['D_KM'] = vectorized_haversine(r_lat, r_lon, pd.to_numeric(df_demanda['MUNICIPIO'].map(mapa_lat), errors='coerce'), pd.to_numeric(df_demanda['MUNICIPIO'].map(mapa_lon), errors='coerce'))
            df_demanda = df_demanda.sort_values('D_KM')
            
            valid_mask = df_demanda.apply(lambda r: all(str(r.get(k, '')).strip().upper() not in ['', 'NAN', 'NONE', '<NA>', '0', '0.0'] for k in ['TIPO LIGACAO', 'NOME DO SOLICITANTE', 'LATITUDE', 'LONGITUDE']), axis=1)
            df_exp = df_demanda[valid_mask][['PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO']].copy()
            
            buf = io.BytesIO()
            df_exp.to_excel(buf, index=False, engine='openpyxl')
            
            st.info(f"⚡ **{len(df_exp)} obras validadas** prontas para exportação.")
            c_b1, c_b3 = st.columns([2.5, 4])
            hj = datetime.now().strftime('%d_%m_%Y')
            c_b1.download_button("📥 Planilha Oficial (Excel)", data=buf.getvalue(), file_name=f"Demanda_{lev_sel}_{hj}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            if c_b3.button("Fechar Ferramenta", use_container_width=True): st.session_state.show_demanda = False; st.rerun()

    st.markdown("---")
    
    # Restauração e limpeza do Gráfico de Municípios
    c_g1, c_g2 = st.columns(2)
    with c_g1:
        if not municipios_por_levantador.empty: 
            # Filtro para varrer e ocultar qualquer "0" ou "SEM LEVANTADOR" do gráfico
            df_grafico = municipios_por_levantador[~municipios_por_levantador['Levantador'].astype(str).str.strip().isin(['0', '0.0', 'nan', 'SEM LEVANTADOR'])].copy()
            
            if not df_grafico.empty:
                fig1 = px.bar(df_grafico.sort_values('Qtd_Municipios', ascending=False).head(15).sort_values('Qtd_Municipios'), 
                              x='Qtd_Municipios', y='Levantador', orientation='h', title="Top 15 Concentração por Município", 
                              text='Qtd_Municipios', color_discrete_sequence=['#1A4F7C'])
                fig1.update_traces(textposition='outside')
                fig1.update_layout(margin=dict(l=150, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, xaxis=dict(showticklabels=False))
                st.plotly_chart(fig1, use_container_width=True)
            
    with c_g2:
        try:
            df_sla = df_notas_db[df_notas_db['Status_SLA'].isin(['No Prazo', 'Vencimento Próximo', 'Vencida'])]
            if not df_sla.empty:
                df_g = df_sla.groupby(['REGIONAL', 'Status_SLA']).size().reset_index(name='Qtd')
                df_g['Status_SLA'] = pd.Categorical(df_g['Status_SLA'], categories=['No Prazo', 'Vencimento Próximo', 'Vencida'], ordered=True)
                fig2 = px.bar(df_g.sort_values(['REGIONAL', 'Status_SLA']), x='REGIONAL', y='Qtd', color='Status_SLA', title="Monitoramento de SLA Regional", barmode='group', text='Qtd', color_discrete_map={'No Prazo': '#10B981', 'Vencimento Próximo': '#F59E0B', 'Vencida': '#EF4444'})
                fig2.update_traces(textposition='outside')
                fig2.update_layout(margin=dict(l=20, r=20, t=40, b=40), xaxis_title=None, yaxis=dict(showticklabels=False), legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5, title=None))
                st.plotly_chart(fig2, use_container_width=True)
        except Exception: pass

    st.markdown("---")
    st.markdown("### 🗺️ Roteirização Geoespacial")
    
    # ---------------------------------------------------------
    # BARRA LATERAL (SIDEBAR) EXPANDIDA COM NOVOS FILTROS
    # ---------------------------------------------------------
    with st.sidebar:
        st.markdown("### 🔍 Filtros Territoriais")
        
        lista_tecnicos_limpa = [str(x) for x in df_notas_db['LEVANTADOR'].unique() if str(x).strip() not in ['0', '0.0', 'nan']]
        lista_sap_limpa = [str(x) for x in df_notas_db['STATUS SAP'].unique() if str(x).strip() not in ['nan', 'None', '']]
        lista_list_limpa = [str(x) for x in df_notas_db['STATUS LIST'].unique() if str(x).strip() not in ['nan', 'None', '']]
        
        op_map_lev = ["TODOS"] + sorted(lista_tecnicos_limpa)
        op_map_reg = ["TODOS"] + sorted([str(x) for x in df_notas_db['REGIONAL'].unique() if str(x).strip() != 'nan'])
        op_map_mun = ["TODOS"] + sorted([str(x) for x in df_notas_db['MUNICIPIO'].unique() if str(x).strip() != 'nan'])
        op_map_sap = ["TODOS"] + sorted(lista_sap_limpa)
        op_map_list = ["TODOS"] + sorted(lista_list_limpa)

        f_lev = st.selectbox("Técnico / Equipe", op_map_lev)
        f_reg = st.selectbox("Regional", op_map_reg)
        f_mun = st.selectbox("Município Alvo", op_map_mun)
        f_sap = st.selectbox("Status SAP", op_map_sap)
        f_list = st.selectbox("Status List", op_map_list)
        
        st.markdown("---")
        st.markdown("### ⚙️ Configurações do Mapa")
        
        # Escolha explícita entre Clusters (Agrupamento interativo) ou Calor (Mancha Térmica)
        estilo_mapa = st.radio("Visualização do Mapa:", ["Agrupamentos (Clusters)", "Calor (Heatmap)"])
        
        # Cores só importam se estiver no modo Cluster
        visao_cores = "Produtividade"
        if estilo_mapa == "Agrupamentos (Clusters)":
            visao_cores = st.radio("Colorir pinos por:", ["Técnico (Produtividade)", "Prazos (SLA)"])
        
        st.markdown("---")
        camada = st.file_uploader("Sobrepor Camada (KML/KMZ)", type=['kml', 'kmz'])

    # Aplicação massiva de filtros na base baseada na barra lateral
    df_m = df_notas_db.copy()
    if f_lev != "TODOS": df_m = df_m[df_m['LEVANTADOR'].astype(str) == f_lev]
    if f_reg != "TODOS": df_m = df_m[df_m['REGIONAL'].astype(str) == f_reg]
    if f_mun != "TODOS": df_m = df_m[df_m['MUNICIPIO'].astype(str) == f_mun]
    if f_sap != "TODOS": df_m = df_m[df_m['STATUS SAP'].astype(str) == f_sap]
    if f_list != "TODOS": df_m = df_m[df_m['STATUS LIST'].astype(str) == f_list]
    
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

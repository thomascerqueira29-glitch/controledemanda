import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster, FastMarkerCluster
import plotly.express as px
import io
import html
import tempfile
from datetime import datetime

# Importa as ferramentas pesadas do nosso motor central
from database import (load_core_data, save_notas_to_db, vectorized_haversine, 
                      parse_kmz_advanced, calcular_sla_vetorizado, 
                      SEM_LEVANTADOR, STATUS_PRODUTIVIDADE)

def kpi_card(title, value, subtitle="", border_color="#1A4F7C"):
    return f"""
    <div style="background-color: #f8f9fa; border-radius: 8px; padding: 15px; border-left: 5px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.05); height: 100%;">
        <p style="margin:0; font-size: 14px; color: #555; text-transform: uppercase; letter-spacing: 0.5px;">{title}</p>
        <h2 style="margin: 5px 0 0 0; color: #333; font-size: 32px;">{value}</h2>
        {f'<p style="margin: 5px 0 0 0; font-size: 12px; color: #777;">{subtitle}</p>' if subtitle else ''}
    </div>
    """

def render_mapa_otimizado(df_notas_mapa, df_eq_mapa_view, criticos_tuple, caminho_camada_temp):
    mapa = folium.Map(location=[-5.2, -45.0], zoom_start=7, tiles=None)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
        attr='Esri', name='Visão de Satélite', overlay=False, control=True
    ).add_to(mapa)
    folium.TileLayer('OpenStreetMap', name='Ruas Padrão', overlay=False, control=True).add_to(mapa)

    if caminho_camada_temp:
        gdf_lines, gdf_points, bounds = parse_kmz_advanced(caminho_camada_temp)
        if not gdf_lines.empty:
            folium.GeoJson(gdf_lines[['Name', 'geometry']], name="Rede Elétrica (Linhas)", style_function=lambda feature: {'color': '#1A4F7C', 'weight': 2.5, 'fillOpacity': 0.2}).add_to(mapa)
        if not gdf_points.empty:
            folium.GeoJson(gdf_points[['Name', 'geometry']], name="Equipamentos (Pontos)", marker=folium.CircleMarker(radius=3, fill_color='#dc3545', color='#dc3545', fill_opacity=0.9)).add_to(mapa)
        if bounds is not None:
            mapa.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    fg_equipes = folium.FeatureGroup(name="📍 Bases dos Levantadores")
    if not df_eq_mapa_view.empty:
        df_eq = df_eq_mapa_view.copy(deep=True)
        lat_col_eq = next((c for c in df_eq.columns if str(c).upper() == 'LATITUDE'), None)
        lon_col_eq = next((c for c in df_eq.columns if str(c).upper() == 'LONGITUDE'), None)
        
        val_lat = pd.to_numeric(df_eq[lat_col_eq].astype(str).str.replace(',', '.'), errors='coerce') if lat_col_eq else np.nan
        val_lon = pd.to_numeric(df_eq[lon_col_eq].astype(str).str.replace(',', '.'), errors='coerce') if lon_col_eq else np.nan
        df_eq = df_eq.assign(Lat=val_lat, Lon=val_lon)
        
        if 'Lat' in df_eq.columns and 'Lon' in df_eq.columns:
            df_eq_valid = df_eq.dropna(subset=['Lat', 'Lon'])
            for _, row in df_eq_valid.iterrows():
                lev = str(row.get('Levantador', ''))
                cor = 'red' if lev in criticos_tuple else 'green'
                folium.Marker(
                    location=[row['Lat'], row['Lon']], 
                    icon=folium.Icon(color=cor, icon='home', prefix='fa'), 
                    tooltip=f"Base: {html.escape(lev)}"
                ).add_to(fg_equipes)
    fg_equipes.add_to(mapa)

    if not df_notas_mapa.empty:
        df_ob = df_notas_mapa.copy(deep=True)
        lat_col = next((c for c in df_ob.columns if str(c).upper() == 'LATITUDE'), None)
        lon_col = next((c for c in df_ob.columns if str(c).upper() == 'LONGITUDE'), None)
        
        v_lat = pd.to_numeric(df_ob[lat_col].astype(str).str.replace(',', '.'), errors='coerce') if lat_col else np.nan
        v_lon = pd.to_numeric(df_ob[lon_col].astype(str).str.replace(',', '.'), errors='coerce') if lon_col else np.nan
        df_ob = df_ob.assign(Lat_Mapa=v_lat, Lon_Mapa=v_lon)

        if 'Lat_Mapa' in df_ob.columns and 'Lon_Mapa' in df_ob.columns:
            df_ob = df_ob.dropna(subset=['Lat_Mapa', 'Lon_Mapa'])
            
            if not df_ob.empty:
                df_ob['Lat_Mapa'] += np.random.normal(0, 0.003, len(df_ob))
                df_ob['Lon_Mapa'] += np.random.normal(0, 0.003, len(df_ob))
                
                if len(df_ob) > 500:
                    coords = df_ob[['Lat_Mapa', 'Lon_Mapa']].values.tolist()
                    FastMarkerCluster(data=coords, name=f"🏗️ Demandas Ativas ({len(coords)} obras)").add_to(mapa)
                else:
                    cluster_obras = MarkerCluster(name=f"🏗️ Demandas Ativas ({len(df_ob)} obras)")
                    for _, row in df_ob.iterrows():
                        lev_obra = str(row.get('LEVANTADOR', SEM_LEVANTADOR))
                        cor_marcador = 'orange' if lev_obra == SEM_LEVANTADOR else ('red' if lev_obra in criticos_tuple else 'blue')
                        info_html = f"<b>Protocolo:</b> {row.get('PROTOCOLO', '')}<br><b>Levantador:</b> {lev_obra}"
                        folium.Marker(
                            location=[row['Lat_Mapa'], row['Lon_Mapa']], 
                            icon=folium.Icon(color=cor_marcador, icon='wrench', prefix='fa'), 
                            popup=folium.Popup(info_html, max_width=300)
                        ).add_to(cluster_obras)
                    cluster_obras.add_to(mapa)

    folium.LayerControl(position='bottomright').add_to(mapa)
    st_folium(mapa, use_container_width=True, height=800, returned_objects=[])

def filtrar_levantador_governanca(nome_lev):
    # =====================================================================
    # CORREÇÃO DE ROTEAMENTO E STATUS LIST
    # =====================================================================
    st.session_state.ui_lev = nome_lev
    st.session_state.ui_reg = 'TODAS'
    st.session_state.ui_mun = 'TODOS'
    st.session_state.ui_sap = 'TODOS'
    st.session_state.ui_list = 'EM LEVANTAMENTO' # Filtro automático exigido
    
    # O GPS do Menu: O índice da Governança muda dependendo do perfil
    if st.session_state.get('perfil_usuario') == "ADMIN":
        st.session_state.menu_idx = 2  # 0=Painel, 1=Carga, 2=Governança
    else:
        st.session_state.menu_idx = 1  # 0=Painel, 1=Governança
        
    st.toast(f"Filtrando obras em levantamento de {nome_lev}...", icon="🔍")

def view_painel_executivo():
    df_notas_db, df_equipes_db, resumo_levantadores, levantadores_criticos, todos_levantadores, mapa_lat, mapa_lon, municipios_por_levantador = load_core_data()
    
    st.markdown("### 📈 Visão Global de Produtividade")
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("O banco de dados está vazio. Realize uma carga em lote.")
        return
        
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi_card("Obras Reais Atribuídas", int(resumo_levantadores['Total_Obras_Real'].sum()), "Volume em operação", "#4A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Equipes/Levantadores", len(resumo_levantadores), "Ativos em campo", "#5CB85C"), unsafe_allow_html=True)
    k3.markdown(kpi_card("Obras Livres (Fila)", len(df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))]), "Sem atribuição", "#F0AD4E"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Levantadores Críticos", len(levantadores_criticos), "Abaixo de 45 obras", "#D9534F" if len(levantadores_criticos) > 0 else "#5CB85C"), unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    col_t1, col_t2 = st.columns([2.5, 1.5])
    with col_t1:
        st.markdown("#### 📋 Desempenho e Alocação das Equipes")
        st.dataframe(resumo_levantadores[['Levantador', 'Equipe', 'Total_Obras_Real']].sort_values('Total_Obras_Real', ascending=False), 
                     use_container_width=True, hide_index=True, height=320, 
                     column_config={
                         "Levantador": "Técnico", 
                         "Equipe": "Equipe", 
                         "Total_Obras_Real": st.column_config.ProgressColumn("Obras (Meta: 45)", format="%d", min_value=0, max_value=45)
                     })
        
    with col_t2:
        st.markdown("#### ⚡ Painel de Ações Rápidas")
        with st.container(border=True):
            lev_sel = st.selectbox("Levantador:", todos_levantadores, label_visibility="collapsed")
            if st.session_state.get('last_lev') != lev_sel:
                st.session_state.assign_step = 0; st.session_state.show_demanda = False; st.session_state.last_lev = lev_sel
                
            obras_do_lev = int(resumo_levantadores[resumo_levantadores['Levantador'] == lev_sel]['Total_Obras_Real'].iloc[0]) if not resumo_levantadores[resumo_levantadores['Levantador'] == lev_sel].empty else 0
            st.info(f"Obras Vinculadas Atualmente: **{obras_do_lev}**")
            
            if st.session_state.perfil_usuario == "ADMIN":
                if obras_do_lev < 45:
                    if st.session_state.get('assign_step', 0) == 0:
                        if st.button(f"⚡ Atribuir +{45 - obras_do_lev} Obras", use_container_width=True, type="primary"):
                            st.session_state.assign_step = 1; st.rerun()
                    elif st.session_state.assign_step == 1:
                        st.warning("Confirmar atribuição?")
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
                                if save_notas_to_db(df_update, acao_auditoria=f"Geo-Atribuição de {len(att)} notas para {lev_sel}"):
                                    st.success("Obras vinculadas!"); st.session_state.assign_step = 2; load_core_data.clear(); st.rerun()
                        if c_b.button("❌ Não", use_container_width=True): st.session_state.assign_step = 0; st.rerun()
                    elif st.session_state.assign_step == 2:
                        st.success("✅ Atribuído.")
                        if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"):
                            st.session_state.show_demanda = True; st.session_state.assign_step = 0; st.rerun()
                else:
                    st.success("✅ Meta Atingida.")
                    if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"): st.session_state.show_demanda = True
            else: st.warning("🔒 Restrito à Coordenação.")
            
            # Botão agora aponta para os índices corretos e leva a variável 'EM LEVANTAMENTO'
            st.button("🔍 Ver Base", on_click=filtrar_levantador_governanca, args=(lev_sel,), use_container_width=True)
            
    if st.session_state.get('show_demanda', False):
        st.markdown("---")
        st.markdown(f"#### 📋 Gerador de Demanda - {lev_sel}")
        df_demanda = df_notas_db[(df_notas_db['LEVANTADOR'] == lev_sel) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))].copy()
        
        if len(df_demanda) > 0:
            tr = df_equipes_db[df_equipes_db['Levantador'] == lev_sel]
            r_lat = mapa_lat.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Latitude']).replace(',','.'))
            r_lon = mapa_lon.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Longitude']).replace(',','.'))
            
            df_demanda['D_KM'] = vectorized_haversine(r_lat, r_lon, pd.to_numeric(df_demanda['MUNICIPIO'].map(mapa_lat), errors='coerce'), pd.to_numeric(df_demanda['MUNICIPIO'].map(mapa_lon), errors='coerce'))
            df_demanda = df_demanda.sort_values('D_KM')
            
            valid_mask = df_demanda.apply(lambda r: all(str(r.get(k, '')).strip().upper() not in ['', 'NAN', 'NONE', '<NA>', '0', '0.0', '0,0'] for k in ['TIPO LIGACAO', 'NOME DO SOLICITANTE', 'LATITUDE', 'LONGITUDE']), axis=1)
            df_exp = df_demanda[valid_mask][['PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO']].copy()
            
            def color_excel(row):
                try: d = float(df_demanda.loc[row.name, 'D_KM'])
                except: return [''] * len(row)
                if d <= 50: return ['background-color: #00B050; color: white;'] * len(row)
                if d <= 100: return ['background-color: #FFFF00; color: black;'] * len(row)
                return ['background-color: #FF0000; color: white;'] * len(row)

            buf = io.BytesIO()
            df_exp.style.apply(color_excel, axis=1).to_excel(buf, index=False, engine='openpyxl')
            
            kml = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
            for _, r in df_exp.iterrows():
                try: kml += f"<Placemark><name>{html.escape(str(r['PROTOCOLO']))}</name><description>{html.escape(str(r['ENDEREÇO']))}</description><Point><coordinates>{float(str(r['LONGITUDE']).replace(',','.'))},{float(str(r['LATITUDE']).replace(',','.'))},0</coordinates></Point></Placemark>\n"
                except: pass
            kml += '</Document>\n</kml>'
            
            st.info(f"⚡ **{len(df_exp)} obras validadas** (Tipo Ligação, Coordenadas e Nome devidamente preenchidos).")
            c_b1, c_b2, c_b3 = st.columns([2.5, 2.5, 4])
            hj = datetime.now().strftime('%d_%m_%Y')
            c_b1.download_button("📥 Planilha Oficial (Excel)", data=buf.getvalue(), file_name=f"Demanda_{lev_sel}_{hj}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            c_b2.download_button("🗺️ Pontos de Rota (KML)", data=kml.encode('utf-8'), file_name=f"Demanda_{lev_sel}_{hj}.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
            if c_b3.button("Fechar Aba", use_container_width=True): st.session_state.show_demanda = False; st.rerun()
        else:
            st.warning("Fila vazia para este levantador.")
            if st.button("Fechar"): st.session_state.show_demanda = False; st.rerun()

    st.markdown("---")
    c_g1, c_g2 = st.columns(2)
    with c_g1:
        if not municipios_por_levantador.empty: st.plotly_chart(px.bar(municipios_por_levantador.sort_values('Qtd_Municipios', ascending=False).head(15).sort_values('Qtd_Municipios'), x='Qtd_Municipios', y='Levantador', orientation='h', title="Top 15 Municípios/Levantador", color_discrete_sequence=['#4A4F7C']), use_container_width=True)
    with c_g2:
        try:
            df_sla = calcular_sla_vetorizado(df_notas_db)
            df_sla = df_sla[df_sla['Status_SLA'].isin(['No Prazo', 'Vencimento Próximo', 'Vencida'])]
            if not df_sla.empty:
                df_g = df_sla.groupby(['REGIONAL', 'Status_SLA']).size().reset_index(name='Qtd')
                df_g['Status_SLA'] = pd.Categorical(df_g['Status_SLA'], categories=['No Prazo', 'Vencimento Próximo', 'Vencida'], ordered=True)
                st.plotly_chart(px.bar(df_g.sort_values(['REGIONAL', 'Status_SLA']), x='REGIONAL', y='Qtd', color='Status_SLA', title="SLA Regional", barmode='group', color_discrete_map={'No Prazo': '#5CB85C', 'Vencimento Próximo': '#F0AD4E', 'Vencida': '#D9534F'}), use_container_width=True)
        except Exception: pass

    st.markdown("---")
    st.markdown("### 🗺️ Roteirização Geoespacial (Híbrida)")
    col_f1, col_f2, col_f3 = st.columns(3)
    
    op_map_lev = ["TODOS"] + sorted([str(x) for x in df_notas_db['LEVANTADOR'].unique()])
    op_map_reg = ["TODOS"] + sorted([str(x) for x in df_notas_db['REGIONAL'].unique()])
    op_map_mun = ["TODOS"] + sorted([str(x) for x in df_notas_db['MUNICIPIO'].unique()])

    f_lev = col_f1.selectbox("Filtro Levantador:", op_map_lev)
    f_reg = col_f2.selectbox("Filtro Regional:", op_map_reg)
    f_mun = col_f3.selectbox("Filtro Município:", op_map_mun)
    
    df_m = df_notas_db.copy()
    if f_lev != "TODOS": df_m = df_m[df_m['LEVANTADOR'].astype(str) == f_lev]
    if f_reg != "TODOS": df_m = df_m[df_m['REGIONAL'].astype(str) == f_reg]
    if f_mun != "TODOS": df_m = df_m[df_m['MUNICIPIO'].astype(str) == f_mun]
    
    st.info(f"📍 Renderizando {len(df_m)} obras no mapa.")
    camada = st.file_uploader("Sobrepor KML/KMZ Rápido", type=['kml', 'kmz'], label_visibility="collapsed")
    camada_p = None
    if camada:
        ext = camada.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp: 
            tmp.write(camada.getvalue())
            camada_p = tmp.name

    df_e = df_equipes_db.copy()
    if f_lev != "TODOS": df_e = df_e[df_e['Levantador'].astype(str).str.upper() == f_lev]
    
    with st.spinner("Construindo base geográfica de satélite..."):
        render_mapa_otimizado(df_m, df_e, tuple(levantadores_criticos), camada_p)

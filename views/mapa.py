import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import html
import tempfile
import io

# Ferramentas Avançadas do Folium
from folium.plugins import HeatMap, MarkerCluster, Fullscreen, Draw, MiniMap, LocateControl, MeasureControl
try:
    from folium.plugins import Geocoder
except ImportError:
    Geocoder = None

from database import load_core_data, parse_kmz_advanced, vectorized_haversine, SEM_LEVANTADOR

# Injeção de CSS para melhorar a Proporção e Legibilidade Global
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }
    .stSelectbox label, .stFileUploader label, .stRadio label, .stSlider label { font-size: 15px !important; font-weight: 600 !important; color: #1A4F7C !important; }
</style>
""", unsafe_allow_html=True)

def normalizar_municipios(series_mun):
    s = series_mun.astype(str).str.upper()
    s = s.str.replace(r'[ÁÀÂÃÄ]', 'A', regex=True)
    s = s.str.replace(r'[ÉÈÊË]', 'E', regex=True)
    s = s.str.replace(r'[ÍÌÎÏ]', 'I', regex=True)
    s = s.str.replace(r'[ÓÒÔÕÖ]', 'O', regex=True)
    s = s.str.replace(r'[ÚÙÛÜ]', 'U', regex=True)
    s = s.str.replace(r'Ç', 'C', regex=True)
    return s.str.split('-').str[0].str.strip()

def get_s(val):
    if pd.isna(val): return "-"
    s = str(val).strip()
    return "-" if s.lower() in ['nan', 'none', '<na>', ''] else html.escape(s)

# Algoritmo de roteirização em cadeia (Guloso / Nearest Neighbor)
def get_optimized_route(base_lat, base_lon, df_points):
    route = [(base_lat, base_lon)]
    unvisited = df_points[['Lat_Mapa', 'Lon_Mapa']].copy()
    
    curr_lat, curr_lon = base_lat, base_lon
    while not unvisited.empty:
        dist = vectorized_haversine(curr_lat, curr_lon, unvisited['Lat_Mapa'], unvisited['Lon_Mapa'])
        closest_idx = dist.idxmin()
        closest = unvisited.loc[closest_idx]
        route.append((closest['Lat_Mapa'], closest['Lon_Mapa']))
        curr_lat, curr_lon = closest['Lat_Mapa'], closest['Lon_Mapa']
        unvisited = unvisited.drop(closest_idx)
    return route

# Motor de colisão para capturar obras dentro dos desenhos do mapa
def point_in_polygon(lat, lon, poly_points):
    x, y = lat, lon
    n = len(poly_points)
    inside = False
    p1x, p1y = poly_points[0]
    for i in range(1, n + 1):
        p2x, p2y = poly_points[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def render_mapa_otimizado(df_notas_mapa, df_eq_mapa_view, criticos_tuple, caminho_camada_temp, mapa_lat, mapa_lon, estilo_mapa, visao_cores, camada_fundo, raio_km, tipo_rota):
    # Base vazia para adicionar o TileLayer correto depois
    mapa = folium.Map(location=[-5.2, -45.0], zoom_start=7, tiles=None, control_scale=True)
    
    # --- CAMADAS DE MAPA AVANÇADAS ---
    if camada_fundo == "Satélite":
        folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Satélite', control=True).add_to(mapa)
    elif camada_fundo == "Modo Escuro (Dark)":
        folium.TileLayer('CartoDB dark_matter', name='Modo Escuro', control=True).add_to(mapa)
    elif camada_fundo == "Topografia":
        folium.TileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', attr='Topo', name='Topografia', control=True).add_to(mapa)
    else:
        folium.TileLayer('OpenStreetMap', name='Ruas Padrão', control=True).add_to(mapa)
    
    # ==========================================
    # NOVAS FUNCIONALIDADES DO MAPA (PLUGINS)
    # ==========================================
    Fullscreen(position='topright', title='Expandir para Tela Cheia', title_cancel='Sair da Tela Cheia', force_separate_button=True).add_to(mapa)
    Draw(export=False, position='topleft', draw_options={'polyline': False, 'polygon': True, 'rectangle': True, 'circle': False, 'marker': False, 'circlemarker': False}).add_to(mapa)
    MeasureControl(position='topright', primary_length_unit='kilometers', secondary_length_unit='meters', primary_area_unit='sqmeters').add_to(mapa)
    LocateControl(auto_start=False, position='topleft', strings={'title': 'Mostrar minha localização no GPS'}).add_to(mapa)
    MiniMap(toggle_display=True, position='bottomleft', zoom_level_offset=-5, width=150, height=150).add_to(mapa)
    
    if Geocoder: Geocoder(position='topright').add_to(mapa)
    # ==========================================

    if caminho_camada_temp:
        gdf_lines, gdf_points, bounds = parse_kmz_advanced(caminho_camada_temp)
        if not gdf_lines.empty: folium.GeoJson(gdf_lines[['Name', 'geometry']], name="Rede Elétrica", style_function=lambda f: {'color': '#1A4F7C', 'weight': 2.5}).add_to(mapa)
        if not gdf_points.empty: folium.GeoJson(gdf_points[['Name', 'geometry']], name="Equipamentos", marker=folium.CircleMarker(radius=3, color='#dc3545')).add_to(mapa)
        if bounds is not None: mapa.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    fg_equipes = folium.FeatureGroup(name="📍 Bases dos Técnicos")
    dict_bases = {}
    
    if not df_eq_mapa_view.empty:
        df_eq = df_eq_mapa_view.copy()
        if 'LATITUDE' in df_eq.columns and 'LONGITUDE' in df_eq.columns:
            df_eq['Lat'] = pd.to_numeric(df_eq['LATITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            df_eq['Lon'] = pd.to_numeric(df_eq['LONGITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            for _, row in df_eq.dropna(subset=['Lat', 'Lon']).iterrows():
                lev = str(row.get('LEVANTADOR', row.get('Levantador', ''))).strip().upper()
                cor = 'red' if lev in [c.upper() for c in criticos_tuple] else 'green'
                folium.Marker([row['Lat'], row['Lon']], icon=folium.Icon(color=cor, icon='home', prefix='fa'), tooltip=f"Base: {html.escape(lev)}").add_to(fg_equipes)
                dict_bases[lev] = (row['Lat'], row['Lon'])
                
                # --- RAIO LOGÍSTICO (BUFFER) ---
                if raio_km > 0:
                    folium.Circle(
                        location=[row['Lat'], row['Lon']],
                        radius=raio_km * 1000, # Em metros
                        color='#10b981', fill=True, fill_opacity=0.1, weight=1,
                        tooltip=f"Cobertura Logística: {raio_km}km"
                    ).add_to(fg_equipes)
                    
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
        df_ob['GPS_ESTIMADO'] = mask_miss

        if mask_miss.any() and 'MUNICIPIO' in df_ob.columns:
            dict_ma_lat = {'SAO LUIS': -2.53, 'IMPERATRIZ': -5.52, 'BALSAS': -7.53, 'PINHEIRO': -2.52} # Adicionado suporte principal
            dict_ma_lon = {'SAO LUIS': -44.30, 'IMPERATRIZ': -47.47, 'BALSAS': -46.03, 'PINHEIRO': -45.08}
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
        
        # --- ROTEIRIZAÇÃO LINEAR ---
        if tipo_rota != "Nenhuma":
            fg_linhas = folium.FeatureGroup(name="🛣️ Roteamento de Obras", show=True)
            for lev, base_coords in dict_bases.items():
                obras_lev = df_ob[df_ob['LEVANTADOR'].str.upper() == lev]
                if obras_lev.empty: continue
                
                if tipo_rota == "Teia de Aranha (Base -> Obra)":
                    for _, row in obras_lev.iterrows():
                        if pd.notna(row['Lat_Mapa']):
                            folium.PolyLine([base_coords, (row['Lat_Mapa'], row['Lon_Mapa'])], color='#1A4F7C', weight=1, opacity=0.4, dash_array='5, 5').add_to(fg_linhas)
                elif tipo_rota == "Caminho Otimizado (Cadeia)":
                    valid_obras = obras_lev.dropna(subset=['Lat_Mapa', 'Lon_Mapa'])
                    if not valid_obras.empty:
                        rota_opt = get_optimized_route(base_coords[0], base_coords[1], valid_obras)
                        folium.PolyLine(rota_opt, color='#e63946', weight=2, opacity=0.8).add_to(fg_linhas)
            fg_linhas.add_to(mapa)

        if estilo_mapa == "Calor (Heatmap)":
            heat_data = [[row['Lat_Mapa'], row['Lon_Mapa']] for _, row in df_ob.iterrows()]
            HeatMap(heat_data, name="🔥 Densidade de Obras", radius=15, blur=20, max_zoom=10).add_to(mapa)
            
        elif estilo_mapa == "Agrupamentos (Clusters)":
            cluster_obras = MarkerCluster(name=f"🏗️ Obras Agrupadas ({len(df_ob)})", maxClusterRadius=45, spiderfyOnMaxZoom=True)
            for row in df_ob.to_dict('records'):
                if row.get('GPS_ESTIMADO', False): cor_marcador, icone = 'lightgray', 'question'
                else:
                    icone = 'wrench'
                    if visao_cores == "Prazos (SLA)":
                        sla_status = row.get('STATUS_SLA', row.get('STATUS SLA', 'No Prazo'))
                        if 'Vencida' in str(sla_status): cor_marcador = 'darkred'
                        elif 'Próximo' in str(sla_status) or 'Proximo' in str(sla_status): cor_marcador = 'orange'
                        else: cor_marcador = 'green'
                    else:
                        lev_obra = get_s(row.get('LEVANTADOR')).upper()
                        if lev_obra == '-' or lev_obra == SEM_LEVANTADOR.upper(): cor_marcador = 'orange'
                        else: cor_marcador = 'red' if lev_obra in [c.upper() for c in criticos_tuple] else 'blue'
                
                info_html = f"""
                <div style="min-width: 260px; font-size: 13px; line-height: 1.5; font-family: sans-serif;">
                    <b>Regional:</b> {get_s(row.get('REGIONAL'))} <br>
                    <b>Município:</b> {get_s(row.get('MUNICIPIO'))} <br>
                    <b>Protocolo:</b> {get_s(row.get('PROTOCOLO'))} <br>
                    <b>Solicitante:</b> {get_s(row.get('NOME DO SOLICITANTE'))} <br>
                    <b>Status List:</b> {get_s(row.get('STATUS LIST'))} <br>
                    <b>SLA:</b> {get_s(row.get('STATUS_SLA', row.get('STATUS SLA', '-')))} <br>
                    <b>Tipo Ligação:</b> {get_s(row.get('TIPO LIGACAO'))}
                    <a href="https://www.google.com/maps/dir/?api=1&destination={row['Lat_Mapa']},{row['Lon_Mapa']}" target="_blank" style="display:block; margin-top:12px; background-color:#1A4F7C; color:white; text-align:center; padding:8px; border-radius:6px; text-decoration:none; font-weight:bold;">🚗 Traçar Rota no Google Maps</a>
                </div>
                """
                folium.Marker(location=[row['Lat_Mapa'], row['Lon_Mapa']], icon=folium.Icon(color=cor_marcador, icon=icone, prefix='fa'), popup=folium.Popup(info_html, max_width=350)).add_to(cluster_obras)
            cluster_obras.add_to(mapa)

        else:
            camada_obras = folium.FeatureGroup(name=f"🏗️ Pinos Individuais ({len(df_ob)})")
            for row in df_ob.to_dict('records'):
                if row.get('GPS_ESTIMADO', False): cor_marcador, icone = 'lightgray', 'question'
                else:
                    icone = 'wrench'
                    if visao_cores == "Prazos (SLA)":
                        sla_status = row.get('STATUS_SLA', row.get('STATUS SLA', 'No Prazo'))
                        if 'Vencida' in str(sla_status): cor_marcador = 'darkred'
                        elif 'Próximo' in str(sla_status) or 'Proximo' in str(sla_status): cor_marcador = 'orange'
                        else: cor_marcador = 'green'
                    else:
                        lev_obra = get_s(row.get('LEVANTADOR')).upper()
                        if lev_obra == '-' or lev_obra == SEM_LEVANTADOR.upper(): cor_marcador = 'orange'
                        else: cor_marcador = 'red' if lev_obra in [c.upper() for c in criticos_tuple] else 'blue'
                
                info_html = f"""
                <div style="min-width: 260px; font-size: 13px; line-height: 1.5; font-family: sans-serif;">
                    <b>Regional:</b> {get_s(row.get('REGIONAL'))} <br>
                    <b>Município:</b> {get_s(row.get('MUNICIPIO'))} <br>
                    <b>Protocolo:</b> {get_s(row.get('PROTOCOLO'))} <br>
                    <b>Solicitante:</b> {get_s(row.get('NOME DO SOLICITANTE'))} <br>
                    <b>Status List:</b> {get_s(row.get('STATUS LIST'))} <br>
                    <b>SLA:</b> {get_s(row.get('STATUS_SLA', row.get('STATUS SLA', '-')))} <br>
                    <b>Tipo Ligação:</b> {get_s(row.get('TIPO LIGACAO'))}
                    <a href="https://www.google.com/maps/dir/?api=1&destination={row['Lat_Mapa']},{row['Lon_Mapa']}" target="_blank" style="display:block; margin-top:12px; background-color:#1A4F7C; color:white; text-align:center; padding:8px; border-radius:6px; text-decoration:none; font-weight:bold;">🚗 Traçar Rota no Google Maps</a>
                </div>
                """
                folium.Marker(location=[row['Lat_Mapa'], row['Lon_Mapa']], icon=folium.Icon(color=cor_marcador, icon=icone, prefix='fa'), popup=folium.Popup(info_html, max_width=350)).add_to(camada_obras)
            camada_obras.add_to(mapa)

    folium.LayerControl(position='bottomright').add_to(mapa)
    
    # Extrai o estado do mapa para habilitar o Filtro por Desenho (Lasso)
    map_data = st_folium(mapa, use_container_width=True, height=850, returned_objects=["all_drawings"])
    return map_data, df_ob


def view_mapa():
    st.markdown("### 🗺️ Mapa de Obras e Roteirização Geoespacial")
    st.markdown("Visualize o território, meça distâncias, gere rotas de execução ou desenhe áreas no mapa para extrair dados.")
    
    df_notas_db, df_equipes_db, _, levantadores_criticos, _, mapa_lat, mapa_lon, _ = load_core_data()
    
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")
    
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        df_notas_db = df_notas_db[df_notas_db['LEVANTADOR'].str.strip().str.upper() == usuario_limpo]
        df_equipes_db = df_equipes_db[df_equipes_db['Levantador'].str.strip().str.upper() == usuario_limpo]
        st.info(f"👁️ **Modo Foco:** Exibindo rotas exclusivas para {usuario_atual}.")

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
        
        camada_fundo = st.selectbox("Fundo do Mapa", ["Ruas (Padrão)", "Satélite", "Modo Escuro (Dark)", "Topografia"])
        
        estilo_mapa = st.radio("Visualização das Obras:", ["Pinos Individuais", "Agrupamentos (Clusters)", "Calor (Heatmap)"])
        
        visao_cores = "Produtividade"
        if estilo_mapa in ["Pinos Individuais", "Agrupamentos (Clusters)"]:
            visao_cores = st.radio("Colorir pinos por:", ["Técnico (Produtividade)", "Prazos (SLA)"])
            
        tipo_rota = st.radio("Roteirização e Linhas:", ["Nenhuma", "Teia de Aranha (Base -> Obra)", "Caminho Otimizado (Cadeia)"])
        
        raio_km = st.slider("Raio Logístico da Base (KM)", 0, 100, 0, step=5, help="Desenha um círculo de cobertura ao redor da Base do Levantador")
        
        st.markdown("---")
        camada = st.file_uploader("Sobrepor Camada (KML/KMZ)", type=['kml', 'kmz'])

    df_m = df_notas_db.copy()
    
    if f_lev != "TODOS": df_m = df_m[df_m['LEVANTADOR'].astype(str).str.strip() == f_lev]
    if f_reg != "TODOS": df_m = df_m[df_m['REGIONAL'].astype(str).str.strip().str.upper() == f_reg]
    if f_mun != "TODOS": df_m = df_m[df_m['MUNICIPIO'].astype(str).str.strip().str.upper() == f_mun]
    if f_sap != "TODOS": df_m = df_m[df_m['STATUS SAP'].astype(str).str.strip().str.upper() == f_sap]
    if f_list != "TODOS": df_m = df_m[df_m['STATUS LIST'].astype(str).str.strip().str.upper() == f_list]
    
    df_m = df_m[~df_m['LEVANTADOR'].astype(str).isin(['0', '0.0'])]
    
    camada_p = None
    if camada:
        ext = camada.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp: 
            tmp.write(camada.getvalue())
            camada_p = tmp.name

    df_e = df_equipes_db.copy()
    if f_lev != "TODOS": df_e = df_e[df_e['Levantador'].astype(str).str.upper() == f_lev]
    
    with st.spinner("Construindo renderização geográfica de alta precisão..."):
        map_state, df_plotado = render_mapa_otimizado(df_m, df_e, tuple(levantadores_criticos), camada_p, mapa_lat, mapa_lon, estilo_mapa, visao_cores, camada_fundo, raio_km, tipo_rota)

    # --- SELEÇÃO MÁGICA POR DESENHO (LASSO) ---
    if map_state and map_state.get("all_drawings"):
        drawings = map_state["all_drawings"]
        polygons = []
        
        # Procura os desenhos feitos pelo usuário
        for d in drawings:
            geom = d.get("geometry", {})
            if geom.get("type") in ["Polygon", "Rectangle"]:
                coords = geom.get("coordinates", [[]])[0]
                polygons.append([(c[1], c[0]) for c in coords]) # Converte GeoJSON [lon, lat] para [lat, lon]
                
        if polygons:
            st.markdown("---")
            st.markdown("### 🖍️ Extrator de Dados por Área Desenhada")
            st.info("O sistema identificou uma área selecionada no mapa e cruzou com o banco de dados.")
            
            # Junta todos os polígonos e filtra a base principal
            mask_total = pd.Series([False] * len(df_plotado), index=df_plotado.index)
            for poly in polygons:
                mask_poly = df_plotado.apply(lambda row: point_in_polygon(row['Lat_Mapa'], row['Lon_Mapa'], poly), axis=1)
                mask_total = mask_total | mask_poly
                
            df_selecionado = df_plotado[mask_total]
            
            if not df_selecionado.empty:
                st.success(f"Foram encontradas **{len(df_selecionado)} obras** dentro da área desenhada!")
                
                # Exibe uma tabela compacta das obras capturadas
                colunas_mostrar = ['PROTOCOLO', 'NOME DO SOLICITANTE', 'MUNICIPIO', 'TIPO LIGACAO', 'STATUS LIST', 'LEVANTADOR']
                cols_presentes = [c for c in colunas_mostrar if c in df_selecionado.columns]
                st.dataframe(df_selecionado[cols_presentes], use_container_width=True, hide_index=True)
                
                # Botão para baixar apenas as obras dentro do desenho
                buf = io.BytesIO()
                df_selecionado.to_excel(buf, index=False, engine='openpyxl')
                st.download_button("📥 Baixar Planilha dessa Área (Excel)", data=buf.getvalue(), file_name="Extracao_Mapa_Desenhado.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("Nenhuma obra foi encontrada dentro do desenho.")

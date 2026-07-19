import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster
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
    /* Reduz o espaço em branco inútil no topo e laterais */
    .block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }
    
    /* Aumenta a legibilidade base de elementos de UI */
    .stSelectbox label, .stFileUploader label { font-size: 15px !important; font-weight: 600 !important; color: #1A4F7C !important; }
</style>
""", unsafe_allow_html=True)

def kpi_card(title, value, subtitle="", icon="📌", border_color="#1A4F7C"):
    """Novo Card de KPI: Maior legibilidade, hierarquia e contexto visual."""
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

def render_mapa_otimizado(df_notas_mapa, df_eq_mapa_view, criticos_tuple, caminho_camada_temp, mapa_lat=None, mapa_lon=None):
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
        cols_upper_eq = {str(c).upper().strip(): c for c in df_eq.columns}
        
        c_lat_eq = cols_upper_eq.get('LATITUDE')
        c_lon_eq = cols_upper_eq.get('LONGITUDE')
        
        if c_lat_eq and c_lon_eq:
            df_eq['Lat'] = pd.to_numeric(df_eq[c_lat_eq].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            df_eq['Lon'] = pd.to_numeric(df_eq[c_lon_eq].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            df_eq_valid = df_eq.dropna(subset=['Lat', 'Lon'])
            
            for _, row in df_eq_valid.iterrows():
                lev = str(row.get(cols_upper_eq.get('LEVANTADOR', 'Levantador'), ''))
                cor = 'red' if lev in criticos_tuple else 'green'
                folium.Marker(
                    location=[row['Lat'], row['Lon']], 
                    icon=folium.Icon(color=cor, icon='home', prefix='fa'), 
                    tooltip=f"Base: {html.escape(lev)}"
                ).add_to(fg_equipes)
    fg_equipes.add_to(mapa)

    # =========================================================================
    # RENDERIZAÇÃO ABSOLUTA DE OBRAS (REGRA DO DESCARTE ZERO)
    # =========================================================================
    if not df_notas_mapa.empty:
        df_ob = df_notas_mapa.copy(deep=True)
        
        # Padroniza todas as colunas para maiúsculo para garantir a leitura dos 8 itens solicitados
        df_ob.columns = [str(c).upper().strip() for c in df_ob.columns]
        
        # 1. Leitura Extrema de Coordenadas (substitui vírgula brasileira por ponto e força número)
        if 'LATITUDE' in df_ob.columns and 'LONGITUDE' in df_ob.columns:
            df_ob['Lat_Mapa'] = pd.to_numeric(df_ob['LATITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
            df_ob['Lon_Mapa'] = pd.to_numeric(df_ob['LONGITUDE'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce')
        else:
            df_ob['Lat_Mapa'] = np.nan
            df_ob['Lon_Mapa'] = np.nan

        # 2. Resgate de Emergência (Para obras onde a coordenada falhou ou está vazia)
        mask_miss = df_ob['Lat_Mapa'].isna() | df_ob['Lon_Mapa'].isna()
        if mask_miss.any() and 'MUNICIPIO' in df_ob.columns:
            # Dicionário do Estado do MA para garantir que a obra caia em sua respectiva cidade
            dict_ma_lat = {'SAO LUIS': -2.53, 'IMPERATRIZ': -5.52, 'SAO JOSE DE RIBAMAR': -2.56, 'TIMON': -5.09, 'CAXIAS': -4.86, 'ACAILANDIA': -4.94, 'CODO': -4.45, 'PACO DO LUMIAR': -2.52, 'BACABAL': -4.22, 'BALSAS': -7.53, 'SANTA INES': -3.66, 'PINHEIRO': -2.52, 'CHAPADINHA': -3.74, 'SANTA LUZIA': -4.15, 'BURITICUPU': -4.34, 'GRAJAU': -5.81, 'ITAPECURU MIRIM': -3.40, 'COROATA': -4.12, 'BARREIRINHAS': -2.74, 'TUTOIA': -2.76, 'VARGEM GRANDE': -3.53, 'VIANA': -3.21, 'ZE DOCA': -3.27, 'LAGO DA PEDRA': -4.33, 'COELHO NETO': -4.25, 'PRESIDENTE DUTRA': -5.28, 'BOM JARDIM': -3.56, 'SAO JOAO DOS PATOS': -6.49, 'ARARI': -3.45, 'AMARANTE DO MARANHAO': -5.56, 'PENALVA': -3.28, 'COLINAS': -6.02, 'ESTREITO': -6.56, 'ALDEIAS ALTAS': -4.62, 'BARRA DO CORDA': -5.50, 'TUNTUM': -5.25, 'DOM PEDRO': -5.03, 'MIRADOR': -6.37, 'RAPOSA': -2.42, 'ROSARIO': -2.93, 'SAO MATEUS DO MARANHAO': -4.04, 'ALCANTARA': -2.40, 'PINDARE MIRIM': -3.60, 'VITORINO FREIRE': -4.33, 'PEDREIRAS': -4.56, 'ESPERANTINOPOLIS': -4.86, 'PARNARAMA': -5.67, 'MATOES': -5.45, 'CAROLINA': -7.33, 'RIACHAO': -7.36, 'LORETO': -7.11, 'PASTOS BONS': -6.60, 'SAO RAIMUNDO DAS MANGABEIRAS': -7.02}
            dict_ma_lon = {'SAO LUIS': -44.30, 'IMPERATRIZ': -47.47, 'SAO JOSE DE RIBAMAR': -44.05, 'TIMON': -42.83, 'CAXIAS': -43.35, 'ACAILANDIA': -47.50, 'CODO': -43.89, 'PACO DO LUMIAR': -44.10, 'BACABAL': -44.78, 'BALSAS': -46.03, 'SANTA INES': -45.38, 'PINHEIRO': -45.08, 'CHAPADINHA': -43.35, 'SANTA LUZIA': -45.66, 'BURITICUPU': -46.40, 'GRAJAU': -46.14, 'ITAPECURU MIRIM': -44.35, 'COROATA': -44.12, 'BARREIRINHAS': -42.82, 'TUTOIA': -42.27, 'VARGEM GRANDE': -43.91, 'VIANA': -45.00, 'ZE DOCA': -45.65, 'LAGO DA PEDRA': -45.12, 'COELHO NETO': -43.01, 'PRESIDENTE DUTRA': -44.48, 'BOM JARDIM': -45.99, 'SAO JOAO DOS PATOS': -43.70, 'ARARI': -44.77, 'AMARANTE DO MARANHAO': -46.74, 'PENALVA': -45.17, 'COLINAS': -44.24, 'ESTREITO': -47.45, 'ALDEIAS ALTAS': -43.47, 'BARRA DO CORDA': -45.24, 'TUNTUM': -44.64, 'DOM PEDRO': -44.43, 'MIRADOR': -44.36, 'RAPOSA': -44.03, 'ROSARIO': -44.24, 'SAO MATEUS DO MARANHAO': -44.47, 'ALCANTARA': -44.41, 'PINDARE MIRIM': -45.34, 'VITORINO FREIRE': -45.23, 'PEDREIRAS': -44.60, 'ESPERANTINOPOLIS': -44.70, 'PARNARAMA': -43.09, 'MATOES': -43.19, 'CAROLINA': -47.46, 'RIACHAO': -46.38, 'LORETO': -45.13, 'PASTOS BONS': -44.07, 'SAO RAIMUNDO DAS MANGABEIRAS': -45.31}
            
            # Limpa o texto da cidade para casar com o dicionário
            muns = df_ob.loc[mask_miss, 'MUNICIPIO'].astype(str).str.upper().str.strip()
            muns = muns.str.replace('Ó', 'O').str.replace('Í', 'I').str.replace('Á', 'A').str.replace('Ã', 'A').str.replace('É', 'E').str.replace('Ê', 'E').str.split('-').str[0].str.strip()
            
            df_ob.loc[mask_miss, 'Lat_Mapa'] = muns.map(dict_ma_lat)
            df_ob.loc[mask_miss, 'Lon_Mapa'] = muns.map(dict_ma_lon)
            
        # 3. Resgate Final: Se ainda assim a obra não tiver coordenada (ex: cidade não listada e coord vazia)
        # ELA NÃO SERÁ APAGADA DA TELA. Receberá o centro geográfico do mapa para exibição obrigatória.
        mask_still_miss = df_ob['Lat_Mapa'].isna() | df_ob['Lon_Mapa'].isna()
        if mask_still_miss.any():
            df_ob.loc[mask_still_miss, 'Lat_Mapa'] = -5.2
            df_ob.loc[mask_still_miss, 'Lon_Mapa'] = -45.0
            
        # 4. MICRO-ESPALHAMENTO MATEMÁTICO UNIVERSAL
        # Desloca minunciosamente todas as 7352 obras para que elas não fiquem empilhadas milimetricamente no mesmo pixel
        np.random.seed(42)
        df_ob['Lat_Mapa'] += np.random.uniform(-0.010, 0.010, len(df_ob))
        df_ob['Lon_Mapa'] += np.random.uniform(-0.010, 0.010, len(df_ob))
        
        # 5. Instanciação do Agrupador com as 7352 obras garantidas
        cluster_obras = MarkerCluster(name=f"🏗️ Demandas Ativas ({len(df_ob)} obras)")
        
        # Função para garantir a leitura de textos quebrando qualquer formatação vazia
        def get_s(val):
            if pd.isna(val): return "-"
            s = str(val).strip()
            if s.lower() in ['nan', 'none', '<na>', '']: return "-"
            return html.escape(s)

        # 6. Renderização dos Pop-ups com os 8 atributos solicitados
        records = df_ob.to_dict('records')
        for row in records:
            lev_obra = get_s(row.get('LEVANTADOR'))
            if lev_obra == '-': lev_obra = SEM_LEVANTADOR
            cor_marcador = 'orange' if lev_obra == SEM_LEVANTADOR else ('red' if lev_obra in criticos_tuple else 'blue')
            
            # POP-UP BLINDADO CONTRA FALHAS HTML (Campos Exatos Solicitados)
            info_html = f"""
            <div style="min-width: 250px; font-size: 13px; line-height: 1.5; font-family: sans-serif;">
                <b>Regional:</b> {get_s(row.get('REGIONAL'))} <br>
                <b>Município:</b> {get_s(row.get('MUNICIPIO'))} <br>
                <b>Protocolo:</b> {get_s(row.get('PROTOCOLO'))} <br>
                <b>Solicitante:</b> {get_s(row.get('NOME DO SOLICITANTE'))} <br>
                <b>Status List:</b> {get_s(row.get('STATUS LIST'))} <br>
                <b>Status SAP:</b> {get_s(row.get('STATUS SAP'))} <br>
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

def filtrar_levantador_governanca(nome_lev):
    st.session_state['filtro_lev_widget'] = nome_lev
    st.session_state['filtro_reg_widget'] = 'TODAS'
    st.session_state['filtro_mun_widget'] = 'TODOS'
    st.session_state['filtro_sap_widget'] = 'TODOS'
    st.session_state['target_status_list'] = 'EM LEVANTAMENTO'

    if st.session_state.get('perfil_usuario') == "ADMIN":
        st.session_state.menu_idx = 4
    else:
        st.session_state.menu_idx = 1
        
    st.toast(f"Redirecionando para as obras de {nome_lev}...", icon="🚀")

def view_painel_executivo():
    df_notas_db, df_equipes_db, resumo_levantadores, levantadores_criticos, todos_levantadores, mapa_lat, mapa_lon, municipios_por_levantador = load_core_data()
    
    st.markdown("### 📈 Visão Global de Produtividade")
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("O banco de dados está vazio. Realize uma carga em lote para popular o painel.")
        return
        
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi_card("Obras Atribuídas", int(resumo_levantadores['Total_Obras_Real'].sum()), "Em execução no momento", "🏗️", "#1A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Equipes em Campo", len(resumo_levantadores), "Levantadores ativos", "👥", "#10B981"), unsafe_allow_html=True)
    k3.markdown(kpi_card("Obras Livres", len(df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))]), "Aguardando atribuição", "⏳", "#F59E0B"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Risco Crítico", len(levantadores_criticos), "Abaixo da meta (45 obras)", "🚨", "#EF4444" if len(levantadores_criticos) > 0 else "#10B981"), unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_t1, col_t2 = st.columns([1.5, 1])
    with col_t1:
        st.markdown("#### 📋 Desempenho e Alocação")
        st.dataframe(resumo_levantadores[['Levantador', 'Equipe', 'Total_Obras_Real']].sort_values('Total_Obras_Real', ascending=False), 
                     use_container_width=True, hide_index=True, height=280, 
                     column_config={
                         "Levantador": "Técnico", 
                         "Equipe": "Equipe", 
                         "Total_Obras_Real": st.column_config.ProgressColumn("Carga de Obras (Meta: 45)", format="%d", min_value=0, max_value=45)
                     })
        
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
            
            if st.session_state.perfil_usuario == "ADMIN":
                if obras_do_lev < 45:
                    if st.session_state.get('assign_step', 0) == 0:
                        if st.button(f"➕ Atribuir {45 - obras_do_lev} Obras", use_container_width=True, type="primary"):
                            st.session_state.assign_step = 1; st.rerun()
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
                                if save_notas_to_db(df_update, acao_auditoria=f"Geo-Atribuição de {len(att)} notas para {lev_sel}"):
                                    st.success("Obras vinculadas!"); st.session_state.assign_step = 2; load_core_data.clear(); st.rerun()
                        if c_b.button("❌ Não", use_container_width=True): st.session_state.assign_step = 0; st.rerun()
                    elif st.session_state.assign_step == 2:
                        st.success("✅ Atribuição Concluída.")
                        if st.button("📋 Gerar Demanda (Excel/KML)", use_container_width=True, type="primary"):
                            st.session_state.show_demanda = True; st.session_state.assign_step = 0; st.rerun()
                else:
                    st.success("✅ Meta Atingida.")
                    if st.button("📋 Gerar Demanda (Excel/KML)", use_container_width=True, type="primary"): st.session_state.show_demanda = True
            else: 
                st.warning("🔒 Atribuição restrita à Coordenação.")
            
            st.button("🔍 Filtrar na Base (Governança)", on_click=filtrar_levantador_governanca, args=(lev_sel,), use_container_width=True)
            
    if st.session_state.get('show_demanda', False):
        st.markdown("---")
        st.markdown(f"#### 📋 Gerador de Demanda de Campo - {lev_sel}")
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
            
            st.info(f"⚡ **{len(df_exp)} obras validadas** prontas para exportação.")
            c_b1, c_b2, c_b3 = st.columns([2.5, 2.5, 4])
            hj = datetime.now().strftime('%d_%m_%Y')
            c_b1.download_button("📥 Planilha Oficial (Excel)", data=buf.getvalue(), file_name=f"Demanda_{lev_sel}_{hj}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            c_b2.download_button("🗺️ Pontos de Rota (KML)", data=kml.encode('utf-8'), file_name=f"Demanda_{lev_sel}_{hj}.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
            if c_b3.button("Fechar Ferramenta", use_container_width=True): st.session_state.show_demanda = False; st.rerun()
        else:
            st.warning("Não há obras ativas atribuídas a este técnico.")
            if st.button("Fechar Aba"): st.session_state.show_demanda = False; st.rerun()

    st.markdown("---")
    
    c_g1, c_g2 = st.columns(2)
    with c_g1:
        if not municipios_por_levantador.empty: 
            fig1 = px.bar(
                municipios_por_levantador.sort_values('Qtd_Municipios', ascending=False).head(15).sort_values('Qtd_Municipios'), 
                x='Qtd_Municipios', 
                y='Levantador', 
                orientation='h', 
                title="Top 15 Concentração por Município", 
                text='Qtd_Municipios',
                color_discrete_sequence=['#1A4F7C']
            )
            fig1.update_traces(textposition='outside', textfont=dict(size=13, color='black'))
            fig1.update_layout(margin=dict(l=150, r=20, t=40, b=20), xaxis_title=None, yaxis_title=None, xaxis=dict(showticklabels=False))
            st.plotly_chart(fig1, use_container_width=True)
            
    with c_g2:
        try:
            df_sla = calcular_sla_vetorizado(df_notas_db)
            df_sla = df_sla[df_sla['Status_SLA'].isin(['No Prazo', 'Vencimento Próximo', 'Vencida'])]
            if not df_sla.empty:
                df_g = df_sla.groupby(['REGIONAL', 'Status_SLA']).size().reset_index(name='Qtd')
                df_g['Status_SLA'] = pd.Categorical(df_g['Status_SLA'], categories=['No Prazo', 'Vencimento Próximo', 'Vencida'], ordered=True)
                
                fig2 = px.bar(
                    df_g.sort_values(['REGIONAL', 'Status_SLA']), 
                    x='REGIONAL', 
                    y='Qtd', 
                    color='Status_SLA', 
                    title="Monitoramento de SLA Regional", 
                    barmode='group', 
                    text='Qtd',
                    color_discrete_map={'No Prazo': '#10B981', 'Vencimento Próximo': '#F59E0B', 'Vencida': '#EF4444'}
                )
                fig2.update_traces(textposition='outside', textfont=dict(size=12))
                fig2.update_layout(
                    margin=dict(l=20, r=20, t=40, b=40),
                    xaxis=dict(tickangle=0, title=None, tickfont=dict(size=12)),
                    yaxis=dict(title=None, showticklabels=False),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5, title=None)
                )
                st.plotly_chart(fig2, use_container_width=True)
        except Exception: pass

    st.markdown("---")
    st.markdown("### 🗺️ Roteirização Geoespacial")
    
    with st.container(border=True):
        st.markdown("<p style='font-size: 14px; font-weight: 600; color: #555; margin-bottom: 5px;'>🔍 Controles de Topografia e Rota</p>", unsafe_allow_html=True)
        col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 1.5])
        
        op_map_lev = ["TODOS"] + sorted([str(x) for x in df_notas_db['LEVANTADOR'].unique()])
        op_map_reg = ["TODOS"] + sorted([str(x) for x in df_notas_db['REGIONAL'].unique()])
        op_map_mun = ["TODOS"] + sorted([str(x) for x in df_notas_db['MUNICIPIO'].unique()])

        f_lev = col_f1.selectbox("Técnico / Equipe", op_map_lev)
        f_reg = col_f2.selectbox("Regional", op_map_reg)
        f_mun = col_f3.selectbox("Município Alvo", op_map_mun)
        
        camada = col_f4.file_uploader("Sobrepor KML/KMZ", type=['kml', 'kmz'], label_visibility="visible")
        
    df_m = df_notas_db.copy()
    if f_lev != "TODOS": df_m = df_m[df_m['LEVANTADOR'].astype(str) == f_lev]
    if f_reg != "TODOS": df_m = df_m[df_m['REGIONAL'].astype(str) == f_reg]
    if f_mun != "TODOS": df_m = df_m[df_m['MUNICIPIO'].astype(str) == f_mun]
    
    st.caption(f"📍 Renderizando **{len(df_m)}** obras baseadas nos filtros selecionados.")
    
    camada_p = None
    if camada:
        ext = camada.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp: 
            tmp.write(camada.getvalue())
            camada_p = tmp.name

    df_e = df_equipes_db.copy()
    if f_lev != "TODOS": df_e = df_e[df_e['Levantador'].astype(str).str.upper() == f_lev]
    
    with st.spinner("Construindo renderização geográfica do terreno..."):
        render_mapa_otimizado(df_m, df_e, tuple(levantadores_criticos), camada_p, mapa_lat, mapa_lon)

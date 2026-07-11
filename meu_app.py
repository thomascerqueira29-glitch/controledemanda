import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster
import plotly.express as px
import numpy as np
import os
import io
import sqlite3
import pandera as pa
import streamlit_antd_components as sac
import math
import tempfile
import geopandas as gpd

# Habilita o suporte a KML no fiona/geopandas
try:
    import fiona
    fiona.drvsupport.supported_drivers['KML'] = 'rw'
except:
    pass

# Configuração de Layout e Identidade Visual Corporativa
st.set_page_config(page_title="Portal Corporativo NIP", layout="wide", page_icon="🏗️")

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES DE ESTADO, BANCO DE DADOS E NAVEGAÇÃO
# -----------------------------------------------------------------------------
DB_PATH = 'controle_torre_nip.db'

if 'db_initialized' not in st.session_state:
    st.session_state.db_initialized = False

if 'menu_idx' not in st.session_state:
    st.session_state.menu_idx = 0

STATUS_PRODUTIVIDADE = ["CORRECAO DE LEVANTAMENTO", "EM LEVANTAMENTO", "PRE ANALISE"]

if 'filtros_salvos' not in st.session_state:
    st.session_state.filtros_salvos = {
        'lev': 'TODOS', 'reg': 'TODOS', 'mun': 'TODOS',
        'lig': 'TODOS', 'sap': 'TODOS', 'list': [] 
    }

def filtrar_levantador_governanca(nome_lev):
    st.session_state.filtros_salvos['lev'] = nome_lev
    st.session_state.filtros_salvos['reg'] = 'TODOS'
    st.session_state.filtros_salvos['mun'] = 'TODOS'
    st.session_state.filtros_salvos['lig'] = 'TODOS'
    st.session_state.filtros_salvos['sap'] = 'TODOS'
    st.session_state.filtros_salvos['list'] = STATUS_PRODUTIVIDADE.copy() 
    st.session_state.menu_idx = 1
    st.toast(f"Buscando demandas de {nome_lev}...", icon="🔍")

# Função Matemática de Distância Segura
def safe_haversine(lat1, lon1, lat2, lon2):
    try:
        R = 6371.0 
        lat1_rad, lon1_rad = math.radians(float(lat1)), math.radians(float(lon1))
        lat2_rad, lon2_rad = math.radians(float(lat2)), math.radians(float(lon2))
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except:
        return 99999

# -----------------------------------------------------------------------------
# 1. ENGENHARIA DE DADOS E CONEXÃO SQLITE
# -----------------------------------------------------------------------------
def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notas';")
    
    colunas_template_oficial = [
        'ID SISCO', 'STATUS SISCO', 'TIPO LIGACAO SISCO', 'DESCRIÇÃO SERVIÇO SISCO', 
        'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 'DATA ENVIO A CAMPO - LIST', 
        'PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 
        'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 
        'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO', 'DATA DE VENCIMENTO'
    ]
    
    if not cursor.fetchone():
        if os.path.exists('NOTAS.xlsx'):
            df_legacy = pd.read_excel('NOTAS.xlsx')
            df_legacy = df_legacy.fillna("").astype(str).replace({"nan": "", "NaT": "", "None": "", "<NA>": ""})
            df_legacy.to_sql('notas', conn, if_exists='replace', index=False)
        else:
            df_empty = pd.DataFrame(columns=colunas_template_oficial)
            df_empty.to_sql('notas', conn, if_exists='replace', index=False)
            
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
    if not cursor.fetchone():
        if os.path.exists('EQUIPES.xlsx'):
            df_eq_legacy = pd.read_excel('EQUIPES.xlsx')
            df_eq_legacy.to_sql('equipes', conn, if_exists='replace', index=False)
        else:
            df_eq_empty = pd.DataFrame(columns=['Município', 'Estado', 'Levantador', 'Regional', 'Longitude', 'Latitude', 'Equipe'])
            df_eq_empty.to_sql('equipes', conn, if_exists='replace', index=False)
    conn.close()
    st.session_state.db_initialized = True

if not st.session_state.db_initialized:
    init_database()

def auto_assign_levantador(df_notas, df_equipes):
    df_notas = df_notas.copy()
    df_eq_clean = df_equipes.dropna(subset=['Município']).drop_duplicates(subset=['Município'])
    mapa_levantadores = df_eq_clean.set_index('Município')['Levantador'].to_dict()
    
    if 'MUNICIPIO' in df_notas.columns:
        df_notas['MUNICIPIO'] = df_notas['MUNICIPIO'].astype(str).str.upper().str.strip()
    
    if 'LEVANTADOR' not in df_notas.columns:
        df_notas['LEVANTADOR'] = 'SEM LEVANTADOR'
    else:
        df_notas['LEVANTADOR'] = df_notas['LEVANTADOR'].astype(str).str.upper().str.strip()
        
    mask_sem_levantador = (
        df_notas['LEVANTADOR'].isna() | (df_notas['LEVANTADOR'] == 'SEM LEVANTADOR') | 
        (df_notas['LEVANTADOR'] == '') | (df_notas['LEVANTADOR'] == 'NAN') | 
        (df_notas['LEVANTADOR'] == 'NONE') | (df_notas['LEVANTADOR'] == '0')
    )
    
    if 'MUNICIPIO' in df_notas.columns:
        df_notas.loc[mask_sem_levantador, 'LEVANTADOR'] = (
            df_notas.loc[mask_sem_levantador, 'MUNICIPIO'].map(mapa_levantadores).fillna('SEM LEVANTADOR')
        )
    
    for col in ['STATUS LIST', 'DATA ENVIO A CAMPO - LIST', 'STATUS SISCO', 'DATA CRIAÇAO SISCO', 'DATA DE VENCIMENTO']:
        if col not in df_notas.columns:
            df_notas[col] = ""
            
    df_notas['STATUS LIST'] = df_notas['STATUS LIST'].astype(str).str.upper().str.strip()
    return df_notas

@st.cache_data(show_spinner=False)
def get_processed_data():
    conn = get_db_connection()
    df_n = pd.read_sql("SELECT * FROM notas", conn)
    df_e = pd.read_sql("SELECT * FROM equipes", conn)
    conn.close()
    df_n = auto_assign_levantador(df_n, df_e)
    return df_n, df_e

def save_notas_to_db(df_notas_atualizado):
    try:
        df_notas_limpo = df_notas_atualizado.copy()
        df_notas_limpo = df_notas_limpo.fillna("")
        df_notas_limpo = df_notas_limpo.astype(str)
        df_notas_limpo = df_notas_limpo.replace({"nan": "", "NaT": "", "None": "", "<NA>": ""})
        
        conn = get_db_connection()
        df_notas_limpo.to_sql('notas', conn, if_exists='replace', index=False)
        conn.close()
        get_processed_data.clear()
        return True
    except Exception as e:
        st.error(f"Falha de gravação no banco de dados: {e}")
        return False

df_notas_db, df_equipes_db = get_processed_data()

# -----------------------------------------------------------------------------
# 2. PROCESSAMENTO E MÉTRICAS ANALÍTICAS
# -----------------------------------------------------------------------------
def process_analytical_data(df_notas_db, df_equipes_db):
    df_coords = df_equipes_db.dropna(subset=['Município', 'Latitude', 'Longitude']).drop_duplicates(subset=['Município'])
    mapa_lat = pd.to_numeric(df_coords.set_index('Município')['Latitude'], errors='coerce').to_dict()
    mapa_lon = pd.to_numeric(df_coords.set_index('Município')['Longitude'], errors='coerce').to_dict()

    df_notas_calc = df_notas_db.copy()
    df_notas_calc['Lat_Mapa'] = df_notas_calc['MUNICIPIO'].map(mapa_lat) if 'MUNICIPIO' in df_notas_calc else np.nan
    df_notas_calc['Lon_Mapa'] = df_notas_calc['MUNICIPIO'].map(mapa_lon) if 'MUNICIPIO' in df_notas_calc else np.nan

    mun_por_lev = df_equipes_db.groupby('Levantador')['Município'].nunique().reset_index()
    mun_por_lev.columns = ['Levantador', 'Qtd_Municipios']

    cond_list_real = df_notas_calc['STATUS LIST'].isin(STATUS_PRODUTIVIDADE)
    df_filtrado_status = df_notas_calc[cond_list_real]
    contagem_prod = df_filtrado_status['LEVANTADOR'].value_counts().reset_index()
    contagem_prod.columns = ['Levantador', 'Total_Obras_Real']

    todos_lev = [l for l in df_equipes_db['Levantador'].dropna().unique() if str(l).strip() not in ['SEM LEVANTADOR', 'NAN', '', 'None']]

    resumo_lev = pd.DataFrame({'Levantador': todos_lev})
    resumo_lev = pd.merge(resumo_lev, contagem_prod, on='Levantador', how='left').fillna(0)
    resumo_lev['Total_Obras_Real'] = resumo_lev['Total_Obras_Real'].astype(int)

    mapa_lev_equipe = df_equipes_db.dropna(subset=['Levantador', 'Equipe']).drop_duplicates(subset=['Levantador']).set_index('Levantador')['Equipe'].to_dict()
    resumo_lev['Equipe'] = resumo_lev['Levantador'].map(mapa_lev_equipe).fillna('SEM EQUIPE')

    lev_criticos = resumo_lev[resumo_lev['Total_Obras_Real'] < 45]['Levantador'].tolist()
    
    return df_notas_calc, resumo_lev, lev_criticos, mapa_lat, mapa_lon, mun_por_lev, todos_lev

df_notas_calc, resumo_levantadores, levantadores_criticos, mapa_lat, mapa_lon, municipios_por_levantador, todos_levantadores = process_analytical_data(df_notas_db, df_equipes_db)

# -----------------------------------------------------------------------------
# 3. INTERFACE DE NAVEGAÇÃO PREMIUM LATERAL
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 👤 Portal NIP")
    st.caption("Ecossistema de Governança")
    st.markdown("---")
    
    opcoes_menu = ['Painel Executivo', 'Busca e Governança', 'Carga de Lotes', 'Simulador de Alocação']
    
    menu_selecionado = sac.menu([
        sac.MenuItem(opcoes_menu[0], icon='pie-chart-fill'),
        sac.MenuItem(opcoes_menu[1], icon='sliders'),
        sac.MenuItem(opcoes_menu[2], icon='cloud-upload-fill'),
        sac.MenuItem(opcoes_menu[3], icon='calculator-fill'),
    ], index=st.session_state.menu_idx, format_func='title', size='md')
    
    if menu_selecionado in opcoes_menu:
        st.session_state.menu_idx = opcoes_menu.index(menu_selecionado)

# --- VISÃO 1: PAINEL EXECUTIVO E MAPAS ---
if menu_selecionado == 'Painel Executivo':
    st.markdown("### Monitoramento de Produtividade (Meta: Mínimo 45 obras reais)")
    
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("O banco de dados de notas está vazio. Realize uma carga em lote para ativar os indicadores.")
    else:
        for i in range(0, len(resumo_levantadores), 5):
            chunk = resumo_levantadores.iloc[i:i+5]
            cols = st.columns(5)
            for idx, (_, row) in enumerate(chunk.iterrows()):
                lev_nome = row['Levantador']
                qtd_obras_reais = row['Total_Obras_Real']
                eq_nome = row['Equipe']
                is_critico = lev_nome in levantadores_criticos
                
                cor_hex = "#D9534F" if is_critico else "#5CB85C"
                bg_hex = "rgba(217, 83, 79, 0.07)" if is_critico else "rgba(92, 184, 92, 0.07)"
                saldo_necessario = max(0, 45 - qtd_obras_reais)
                
                with cols[idx]:
                    st.markdown(
                        f"""
                        <div style='padding: 12px; border-radius: 6px; background-color: {bg_hex}; border-left: 6px solid {cor_hex}; margin-bottom: 5px; height: 135px; display: flex; flex-direction: column; justify-content: space-between;'>
                            <div>
                                <strong style='font-size: 14px; color: #111;'>{lev_nome}</strong><br>
                                <span style='font-size: 11px; color: #555;'>Equipe: {eq_nome}</span><br>
                            </div>
                            <div style='font-size: 11px; color: #333; margin-top: auto;'>
                                <i>Apenas Obras Reais Atribuídas:</i><br>
                                <span style='font-size: 18px; font-weight: bold; color: {cor_hex};'>{qtd_obras_reais}</span> <span style='font-size: 12px;'>/ 45</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True
                    )
                    
                    b1, b2 = st.columns([1.3, 1])
                    with b1:
                        if is_critico:
                            if st.button(f"⚡ +{saldo_necessario} Reais", key=f"btn_atrib_{lev_nome}"):
                                cond_livres_reais = (df_notas_db['LEVANTADOR'] == 'SEM LEVANTADOR') & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))
                                df_livres = df_notas_db[cond_livres_reais].copy()
                                
                                if len(df_livres) == 0:
                                    st.error("Sem demandas livres.")
                                else:
                                    with st.spinner(f"Processando roteamento para {lev_nome}..."):
                                        try:
                                            tech_coords = df_equipes_db[df_equipes_db['Levantador'] == lev_nome].iloc[0]
                                            tech_lat = tech_coords['Latitude']
                                            tech_lon = tech_coords['Longitude']
                                            
                                            df_livres['Lat_Mapa'] = df_livres['MUNICIPIO'].map(mapa_lat)
                                            df_livres['Lon_Mapa'] = df_livres['MUNICIPIO'].map(mapa_lon)
                                            
                                            df_livres['Distancia_KM'] = df_livres.apply(
                                                lambda r: safe_haversine(tech_lat, tech_lon, r['Lat_Mapa'], r['Lon_Mapa']), axis=1
                                            )
                                            df_livres = df_livres.sort_values('Distancia_KM')
                                        except Exception:
                                            pass

                                        qtd_atribuir = min(saldo_necessario, len(df_livres))
                                        indices_para_mudar = df_livres.head(qtd_atribuir).index
                                        df_notas_db.loc[indices_para_mudar, 'LEVANTADOR'] = lev_nome
                                        
                                        if save_notas_to_db(df_notas_db):
                                            st.success(f"{qtd_atribuir} obras MAIS PRÓXIMAS vinculadas a {lev_nome}.")
                                            st.rerun()
                        else:
                            st.button("✅ Bateu a Meta", key=f"btn_ok_{lev_nome}", disabled=True)
                            
                    with b2:
                        st.button("🔍 Obras", on_click=filtrar_levantador_governanca, args=(lev_nome,), key=f"btn_ver_{lev_nome}", use_container_width=True)

        st.markdown("### 📊 Estatísticas e Distribuição da Carga Geral")
        espaco_esq, col_g1, col_g2, espaco_dir = st.columns([0.5, 4, 4, 0.5])
        
        # BLINDAGEM DO PLOTLY PARA EVITAR ERROS DE MATRIZ VAZIA
        with col_g1:
            if not municipios_por_levantador.empty and municipios_por_levantador['Qtd_Municipios'].sum() > 0:
                try:
                    fig_rosca_mun = px.pie(municipios_por_levantador, names='Levantador', values='Qtd_Municipios', 
                                           title="Quantidade Total de Municípios por Levantador",
                                           hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
                    fig_rosca_mun.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5))
                    st.plotly_chart(fig_rosca_mun, use_container_width=True)
                except Exception:
                    st.info("Gráfico de municípios indisponível no momento.")
            
        with col_g2:
            df_sem_levantador = df_notas_calc[df_notas_calc['LEVANTADOR'] == 'SEM LEVANTADOR']
            df_sem_lev_reg = df_sem_levantador['REGIONAL'].value_counts().reset_index() if 'REGIONAL' in df_sem_levantador else pd.DataFrame()
            if not df_sem_lev_reg.empty:
                df_sem_lev_reg.columns = ['Regional', 'Quantidade_Sem_Atribuicao']
                if df_sem_lev_reg['Quantidade_Sem_Atribuicao'].sum() > 0:
                    try:
                        fig_rosca_sem_lev = px.pie(df_sem_lev_reg, names='Regional', values='Quantidade_Sem_Atribuicao',
                                                   title="Obras Sem Levantador Atribuído por Regional",
                                                   hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                        fig_rosca_sem_lev.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5))
                        st.plotly_chart(fig_rosca_sem_lev, use_container_width=True)
                    except Exception:
                        st.info("Gráfico de Regionais indisponível.")

        # -----------------------------------------------------------------------------
        # GRÁFICO DE SLA (COM BLINDAGEM DE ERROS)
        # -----------------------------------------------------------------------------
        st.markdown("---")
        st.markdown("### ⏳ Monitoramento de SLA por Regional (Regra de Negócio)")
        st.caption("Visão baseada na 'DATA CRIAÇAO SISCO' ou no cronograma manual, conforme o Tipo de Ligação.")
        
        df_sla = df_notas_calc.copy()
        
        def classificar_sla_seguro(row):
            tipo = str(row.get('TIPO LIGACAO', '')).strip().upper()
            
            g1 = ['ASC', 'UNI', 'UNO']
            g2 = ['SEG', 'SID', 'EUR', 'MGD', 'MTP', 'UNR', 'UNP'] 
            g_crono = ['LPT', 'REG', 'PMC', 'ERD', 'SEQ', 'BCP', 'BRE', 'BRT', 'DIG', 'DIS', 'DLD', 'INT', 'MEL', 'OCP', 'TRI', 'EQP', 'FIM', 'MBT', 'MMT']
            g_niv = ['NIV']
            
            hoje = pd.Timestamp.today().normalize()
            
            if tipo in g_crono:
                venc_str = str(row.get('DATA DE VENCIMENTO', '')).strip()
                if venc_str in ['nan', 'None', '', '<NA>', 'NaT']: return 'Sem Cronograma'
                try:
                    dt_venc = pd.to_datetime(venc_str, dayfirst=True)
                    dias = (dt_venc - hoje).days
                    if dias < 0: return 'Vencida'
                    elif 0 <= dias <= 3: return 'Vencimento Próximo'
                    else: return 'No Prazo'
                except:
                    return 'Data Inválida'
                    
            cria_str = str(row.get('DATA CRIAÇAO SISCO', '')).strip()
            if cria_str in ['nan', 'None', '', '<NA>', 'NaT']: return 'Sem Data de Criação'
                
            try:
                dt_cria = pd.to_datetime(cria_str, dayfirst=True)
                idade = (hoje - dt_cria).days
                
                if tipo in g1:
                    if idade <= 10: return 'No Prazo'
                    elif idade <= 15: return 'Vencimento Próximo'
                    else: return 'Vencida'
                elif tipo in g2:
                    if idade <= 16: return 'No Prazo'
                    elif idade <= 24: return 'Vencimento Próximo'
                    else: return 'Vencida'
                elif tipo in g_niv:
                    if idade <= 5: return 'No Prazo'
                    elif idade <= 8: return 'Vencimento Próximo'
                    else: return 'Vencida'
                else:
                    if idade <= 15: return 'No Prazo'
                    elif idade <= 20: return 'Vencimento Próximo'
                    else: return 'Vencida'
            except:
                return 'Data Inválida'

        df_sla['Status_SLA'] = df_sla.apply(classificar_sla_seguro, axis=1)
        df_sla['REGIONAL'] = df_sla['REGIONAL'].replace(['', 'nan', 'None', '<NA>'], 'NÃO INFORMADA')
        
        df_sla_chart = df_sla[df_sla['Status_SLA'].isin(['No Prazo', 'Vencimento Próximo', 'Vencida'])]
        
        if not df_sla_chart.empty:
            df_group = df_sla_chart.groupby(['REGIONAL', 'Status_SLA']).size().reset_index(name='Quantidade')
            if not df_group.empty:
                try:
                    ordem_cat = ['No Prazo', 'Vencimento Próximo', 'Vencida']
                    df_group['Status_SLA'] = pd.Categorical(df_group['Status_SLA'], categories=ordem_cat, ordered=True)
                    df_group = df_group.sort_values(['REGIONAL', 'Status_SLA'])
                    
                    fig_sla = px.bar(
                        df_group,
                        x='REGIONAL',
                        y='Quantidade',
                        color='Status_SLA',
                        title="Status Operacional de SLA por Regional",
                        text='Quantidade',
                        barmode='group',
                        color_discrete_map={
                            'No Prazo': '#5CB85C',
                            'Vencimento Próximo': '#F0AD4E',
                            'Vencida': '#D9534F'
                        }
                    )
                    fig_sla.update_traces(textposition='auto', textfont_size=14)
                    fig_sla.update_layout(xaxis_title="Regional", yaxis_title="Volume de Obras", legend_title="Legenda SLA")
                    st.plotly_chart(fig_sla, use_container_width=True)
                except Exception as e:
                    st.warning(f"O gráfico de SLA não pôde ser renderizado no momento.")
            else:
                 st.info("💡 Não há dados classificados com o SLA no momento (Verifique as Datas de Criação Sisco/Vencimento).")
        else:
            st.info("💡 Não há dados classificados com o SLA no momento (Verifique as Datas de Criação Sisco/Vencimento).")

        st.markdown("---")
        st.markdown("### 🗺️ Roteirização e Camadas Espaciais Georreferenciadas")
        
        camada_upload = st.file_uploader("Sobrepor Camada de Rede (Formatos suportados: .geojson, .kml)", type=['geojson', 'kml'])
        caminho_camada_temp = None
        
        if camada_upload is not None:
            extensao = camada_upload.name.split('.')[-1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{extensao}') as tmp:
                tmp.write(camada_upload.getvalue())
                caminho_camada_temp = tmp.name
        
        def construir_mapa(df_eq, df_nt, criticos_tuple, arquivo_espacial=None):
            mapa = folium.Map(location=[-5.2, -45.0], zoom_start=7)
            
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri', name='Visão de Satélite', overlay=False, control=True
            ).add_to(mapa)
            folium.TileLayer('OpenStreetMap', name='Mapa Padrão', overlay=False, control=True).add_to(mapa)
            
            if arquivo_espacial:
                try:
                    gdf = gpd.read_file(arquivo_espacial)
                    folium.GeoJson(
                        gdf,
                        name="Camada de Rede (Polígonos/Linhas)",
                        style_function=lambda feature: {
                            'color': '#ff9900', 
                            'weight': 3,
                            'fillOpacity': 0.2
                        }
                    ).add_to(mapa)
                except Exception:
                    pass

            fg_equipes = folium.FeatureGroup(name="📍 Bases dos Levantadores")
            fg_obras = folium.FeatureGroup(name="🏗️ Demandas Ativas (Clusters)")
            cluster_obras = MarkerCluster(name="Obras Agrupadas", disableClusteringAtZoom=13).add_to(fg_obras)
            
            records_equipes = df_eq.drop_duplicates(subset=['Município', 'Levantador']).to_dict('records')
            for row in records_equipes:
                try:
                    lat_val = float(row.get('Latitude', np.nan))
                    lon_val = float(row.get('Longitude', np.nan))
                    if not math.isnan(lat_val) and not math.isnan(lon_val):
                        lev = str(row['Levantador'])
                        if lev in todos_levantadores:
                            cor_pino = 'red' if lev in criticos_tuple else 'green'
                            folium.Marker(
                                location=[lat_val, lon_val],
                                icon=folium.Icon(color=cor_pino, icon='user', prefix='fa'),
                                tooltip=f"Levantador: {lev}"
                            ).add_to(fg_equipes)
                except (ValueError, TypeError):
                    pass 

            df_notas_mapa = df_nt.copy()
            df_notas_mapa['Lat_Mapa'] = pd.to_numeric(df_notas_mapa.get('Lat_Mapa'), errors='coerce')
            df_notas_mapa['Lon_Mapa'] = pd.to_numeric(df_notas_mapa.get('Lon_Mapa'), errors='coerce')
            df_notas_mapa = df_notas_mapa.dropna(subset=['Lat_Mapa', 'Lon_Mapa'])
            
            if not df_notas_mapa.empty:
                df_notas_mapa['lat_jitter'] = df_notas_mapa['Lat_Mapa'] + np.random.normal(0, 0.004, len(df_notas_mapa))
                df_notas_mapa['lon_jitter'] = df_notas_mapa['Lon_Mapa'] + np.random.normal(0, 0.004, len(df_notas_mapa))
                
                records_obras = df_notas_mapa.to_dict('records')
                for row in records_obras:
                    html_mini_card = f"""
                    <div style="font-family: Arial, sans-serif; font-size: 11px; width: 260px; line-height: 1.4; color: #222;">
                        <div style="background-color: #1A4F7C; color: white; padding: 5px; font-weight: bold; border-radius: 4px 4px 0 0; text-align: center;">INFORMAÇÕES DA OBRA</div>
                        <div style="padding: 7px; border: 1px solid #1A4F7C; border-top: none; background-color: #FFF; border-radius: 0 0 4px 4px;">
                            <b>PROTOCOLO:</b> {row.get('PROTOCOLO', '')}<br>
                            <b>MUNICIPIO:</b> {row.get('MUNICIPIO', '')}<br>
                            <b>LEVANTADOR:</b> {row.get('LEVANTADOR', '')}<br>
                        </div>
                    </div>
                    """
                    lev_obra = str(row.get('LEVANTADOR', 'SEM LEVANTADOR'))
                    cor_marcador = 'orange' if lev_obra == 'SEM LEVANTADOR' else ('red' if lev_obra in criticos_tuple else 'blue')
                    
                    folium.Marker(
                        location=[row['lat_jitter'], row['lon_jitter']], 
                        icon=folium.Icon(color=cor_marcador, icon='wrench', prefix='fa'),
                        popup=folium.Popup(html_mini_card, max_width=310)
                    ).add_to(cluster_obras)

            fg_equipes.add_to(mapa)
            fg_obras.add_to(mapa)
            folium.LayerControl().add_to(mapa)
            
            return mapa

        with st.spinner("Renderizando mapa espacial..."):
            mapa_pronto = construir_mapa(df_equipes_db, df_notas_calc, tuple(levantadores_criticos), caminho_camada_temp)
            st_folium(mapa_pronto, use_container_width=True, height=750, returned_objects=[])

# --- VISÃO 2: FILTROS E GOVERNANÇA ---
elif menu_selecionado == 'Busca e Governança':
    st.markdown("### 📝 Filtros e Governança Direta da Base")
    
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    
    op_lev = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('LEVANTADOR', pd.Series()).dropna().unique()])
    idx_lev = op_lev.index(st.session_state.filtros_salvos['lev']) if st.session_state.filtros_salvos['lev'] in op_lev else 0
    with col_f1:
        filtro_lev = st.selectbox("Filtrar por Levantador:", op_lev, index=idx_lev)
        st.session_state.filtros_salvos['lev'] = filtro_lev

    op_reg = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('REGIONAL', pd.Series()).dropna().unique()])
    idx_reg = op_reg.index(st.session_state.filtros_salvos['reg']) if st.session_state.filtros_salvos['reg'] in op_reg else 0
    with col_f2:
        filtro_reg = st.selectbox("Filtrar por Regional:", op_reg, index=idx_reg)
        st.session_state.filtros_salvos['reg'] = filtro_reg

    op_mun = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('MUNICIPIO', pd.Series()).dropna().unique()])
    idx_mun = op_mun.index(st.session_state.filtros_salvos['mun']) if st.session_state.filtros_salvos['mun'] in op_mun else 0
    with col_f3:
        filtro_mun = st.selectbox("Filtrar por Município:", op_mun, index=idx_mun)
        st.session_state.filtros_salvos['mun'] = filtro_mun

    op_lig = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('TIPO LIGACAO', pd.Series()).dropna().astype(str).unique()])
    idx_lig = op_lig.index(st.session_state.filtros_salvos['lig']) if st.session_state.filtros_salvos['lig'] in op_lig else 0
    with col_f4:
        filtro_lig = st.selectbox("Filtrar por Tipo Ligação:", op_lig, index=idx_lig)
        st.session_state.filtros_salvos['lig'] = filtro_lig

    col_f5, col_f6 = st.columns(2)
    
    op_sap = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('STATUS SAP', pd.Series()).dropna().unique()])
    idx_sap = op_sap.index(st.session_state.filtros_salvos['sap']) if st.session_state.filtros_salvos['sap'] in op_sap else 0
    with col_f5:
        filtro_sap = st.selectbox("Filtrar por Status SAP:", op_sap, index=idx_sap)
        st.session_state.filtros_salvos['sap'] = filtro_sap

    op_list = sorted([str(x) for x in df_notas_db.get('STATUS LIST', pd.Series()).dropna().unique() if str(x).strip() != ""])
    default_list = [x for x in st.session_state.filtros_salvos['list'] if x in op_list]
    with col_f6:
        filtro_list = st.multiselect("Filtrar por Status List (Vazio = TODOS):", options=op_list, default=default_list)
        st.session_state.filtros_salvos['list'] = filtro_list

    df_filtrado = df_notas_db.copy()
    if st.session_state.filtros_salvos['lev'] != "TODOS" and 'LEVANTADOR' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'] == st.session_state.filtros_salvos['lev']]
    if st.session_state.filtros_salvos['reg'] != "TODOS" and 'REGIONAL' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['REGIONAL'] == st.session_state.filtros_salvos['reg']]
    if st.session_state.filtros_salvos['mun'] != "TODOS" and 'MUNICIPIO' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'] == st.session_state.filtros_salvos['mun']]
    if st.session_state.filtros_salvos['lig'] != "TODOS" and 'TIPO LIGACAO' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['TIPO LIGACAO'].astype(str) == st.session_state.filtros_salvos['lig']]
    if st.session_state.filtros_salvos['sap'] != "TODOS" and 'STATUS SAP' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['STATUS SAP'] == st.session_state.filtros_salvos['sap']]
    if len(st.session_state.filtros_salvos['list']) > 0 and 'STATUS LIST' in df_filtrado: 
        df_filtrado = df_filtrado[df_filtrado['STATUS LIST'].isin(st.session_state.filtros_salvos['list'])]

    st.info(f"Obras localizadas sob os filtros aplicados: {len(df_filtrado)} registro(s).")
    
    if len(df_filtrado) > 0:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_filtrado.to_excel(writer, index=False, sheet_name='Filtrado')
        st.download_button(
            label="📥 Exportar Dados Filtrados para Excel", 
            data=buffer.getvalue(),
            file_name="relatorio_nip_filtrado.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    st.markdown("---")
    st.markdown("### 📊 Gestão e Edição em Lote")
    st.caption("Altere as células (incluindo DATA DE VENCIMENTO e DATA CRIAÇAO SISCO) diretamente na tabela abaixo e clique em Salvar Alterações.")
    
    df_editado = st.data_editor(
        df_filtrado, 
        use_container_width=True, 
        num_rows="dynamic",
        key="editor_notas"
    )

    col_btn1, col_btn2 = st.columns([8, 2])
    with col_btn1:
        if st.button("💾 Salvar Alterações na Base", type="primary"):
            with st.spinner("Persistindo informações..."):
                indices_originais = df_editado.index
                df_notas_db.loc[indices_originais] = df_editado
                if save_notas_to_db(df_notas_db):
                    st.success("Banco de Dados Atualizado com Sucesso!")
                    st.rerun()
                
    with col_btn2:
        with st.expander("⚠️ ÁREA DE PERIGO"):
            confirmacao_global = st.checkbox("Confirmo que desejo apagar TODAS as notas.")
            if st.button("🚨 APAGAR TUDO", type="primary", disabled=not confirmacao_global):
                df_empty = pd.DataFrame(columns=df_notas_db.columns)
                if save_notas_to_db(df_empty):
                    st.success("Banco de dados de obras totalmente limpo!")
                    st.rerun()

# --- VISÃO 3: CARGA DE LOTES ---
elif menu_selecionado == 'Carga de Lotes':
    st.markdown("### 📤 Módulo de Importação de Lotes com Validação Strict")
    st.caption("Arraste o arquivo original. O sistema destruirá automaticamente as linhas fantasmas e validará a estrutura.")
    
    schema_nip = pa.DataFrameSchema({
        "PROTOCOLO": pa.Column(pa.String, coerce=True, required=True),
        "REGIONAL": pa.Column(pa.String, coerce=True, required=True),
        "MUNICIPIO": pa.Column(pa.String, coerce=True, required=True),
        "DATA CRIAÇAO SISCO": pa.Column(pa.String, coerce=True, required=False, nullable=True),
        "TIPO LIGACAO": pa.Column(pa.String, coerce=True, required=False, nullable=True),
        "STATUS SAP": pa.Column(pa.String, coerce=True, required=False, nullable=True),
        "ID SISCO": pa.Column(pa.String, coerce=True, required=False, nullable=True)
    }, strict=False)

    arquivo_upload = st.file_uploader("Selecione o arquivo de demandas", type=["csv", "xlsx"])
    
    if arquivo_upload is not None:
        try:
            df_novos_dados = pd.read_csv(arquivo_upload) if arquivo_upload.name.endswith('.csv') else pd.read_excel(arquivo_upload)
            
            df_novos_dados = df_novos_dados.dropna(subset=['MUNICIPIO', 'PROTOCOLO'], how='any')
            df_novos_dados['PROTOCOLO'] = df_novos_dados['PROTOCOLO'].astype(str).str.replace(r'\.0$', '', regex=True)
            
            try:
                df_validado = schema_nip.validate(df_novos_dados)
                st.success("✅ Limpeza Concluída! Layout e Tipagem Homologados pelo Contrato de Dados.")
                
                df_validado['MUNICIPIO'] = df_validado['MUNICIPIO'].astype(str).str.upper().str.strip()
                if 'LEVANTADOR' not in df_validado.columns:
                    df_validado['LEVANTADOR'] = 'SEM LEVANTADOR'
                    
                df_temp_processado = auto_assign_levantador(df_validado, df_equipes_db)
                
                if st.button("⚡ Confirmar Importação e Gravar no Banco de Dados SQLite"):
                    with st.spinner("Injetando carga de lotes no banco..."):
                        df_final = pd.concat([df_notas_db, df_temp_processado], ignore_index=True)
                        if save_notas_to_db(df_final):
                            st.success(f"Sucesso! {len(df_temp_processado)} novas demandas validadas e injetadas.")
                            st.rerun()
                        
            except pa.errors.SchemaError as exc:
                st.error("🚨 Erro Crítico na Estrutura do Lote! A importação foi bloqueada.")
                st.markdown(f"**Detalhe da falha:** O dado na coluna `{exc.schema.name}` não respeita o contrato estabelecido. Esperado: `{exc.schema.dtype}`.")
                st.dataframe(exc.data, use_container_width=True)
                
        except Exception as e:
            st.error(f"Erro inesperado de leitura do arquivo físico: {e}")

# --- VISÃO 4: SIMULADOR DE ALOCAÇÃO ---
elif menu_selecionado == 'Simulador de Alocação':
    st.markdown("""
        <div style="background-color: #333; padding: 15px; border-radius: 5px; text-align: center; color: white; margin-bottom: 20px;">
            <h2 style="margin: 0; color: white;">Simulador de Alocação de Levantadores (MA)</h2>
        </div>
    """, unsafe_allow_html=True)

    df_eq_sim = df_equipes_db.copy()
    
    # Tratamento para evitar que regionais em branco quebrem agrupamentos
    df_eq_sim['Regional'] = df_eq_sim['Regional'].replace(['', 'nan', 'None', '<NA>'], 'NÃO INFORMADA')
    df_eq_sim['Regional'] = df_eq_sim['Regional'].astype(str).str.upper()
    df_eq_sim['Levantador'] = df_eq_sim['Levantador'].astype(str).str.upper()

    mun_total = df_eq_sim.groupby('Regional')['Município'].nunique().reset_index(name='Total Municípios')
    
    valid_lev_mask = (
        (df_eq_sim['Levantador'] != 'SEM LEVANTADOR') & 
        (df_eq_sim['Levantador'].notna()) &
        (df_eq_sim['Levantador'] != '') & 
        (df_eq_sim['Levantador'] != '0') & 
        (df_eq_sim['Levantador'] != 'NAN') &
        (df_eq_sim['Levantador'] != 'NONE')
    )
    mun_com = df_eq_sim[valid_lev_mask].groupby('Regional')['Município'].nunique().reset_index(name='Com Levantador')
    
    df_lev_validos = df_eq_sim[valid_lev_mask]
    lev_atuais = df_lev_validos.groupby('Regional')['Levantador'].nunique().reset_index(name='Levantadores Atuais')

    df_sim = mun_total.merge(mun_com, on='Regional', how='left').fillna(0)
    df_sim = df_sim.merge(lev_atuais, on='Regional', how='left').fillna(0)
    
    df_sim['Sem Levantador'] = df_sim['Total Municípios'] - df_sim['Com Levantador']
    df_sim['Levantadores Atuais'] = df_sim['Levantadores Atuais'].astype(int)
    
    df_sim['Capacidade Media'] = np.where(df_sim['Levantadores Atuais'] > 0, df_sim['Com Levantador'] / df_sim['Levantadores Atuais'], 0)

    total_mun = int(df_sim['Total Municípios'].sum())
    total_com = int(df_sim['Com Levantador'].sum())
    total_sem = int(df_sim['Sem Levantador'].sum())
    cob_atual = (total_com / total_mun * 100) if total_mun > 0 else 0
    total_lev_atuais = int(df_sim['Levantadores Atuais'].sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Total Municípios</b><br><span style='font-size:24px'>{total_mun}</span></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Municípios Cobertos</b><br><span style='font-size:24px'>{total_com}</span></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Municípios Sem Levantador</b><br><span style='font-size:24px'>{total_sem}</span></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div style='text-align: center; background: #eee; padding: 10px; border-radius: 5px;'><b>Cobertura Atual</b><br><span style='font-size:24px'>{cob_atual:.1f}%</span></div>", unsafe_allow_html=True)
    
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

    df_edited = st.data_editor(
        df_sim,
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
        key='editor_simulador'
    )

    df_edited['Municipios Ganhos'] = np.floor(df_edited['Novos Levantadores'] * df_edited['Capacidade Media']).astype(int)
    df_edited['Municipios Ganhos'] = df_edited[['Municipios Ganhos', 'Sem Levantador']].min(axis=1) 
    
    df_edited['Gap Restante'] = df_edited['Sem Levantador'] - df_edited['Municipios Ganhos']
    df_edited['Cobertura %'] = np.where(df_edited['Total Municípios'] > 0, ((df_edited['Com Levantador'] + df_edited['Municipios Ganhos']) / df_edited['Total Municípios']) * 100, 0)

    st.markdown("<h4 style='background-color: #4A4F7C; color: white; padding: 5px 10px; margin-top: 20px; border-radius: 5px;'>Projeção Atualizada e Representatividade</h4>", unsafe_allow_html=True)
    
    col_proj_tab, col_proj_chart = st.columns([2.5, 1.5])
    
    with col_proj_tab:
        df_proj = df_edited[['Regional', 'Total Municípios', 'Com Levantador', 'Sem Levantador', 'Levantadores Atuais', 'Novos Levantadores', 'Gap Restante', 'Cobertura %']].copy()
        
        total_mun_sum = df_proj['Total Municípios'].sum()
        total_com_sum = df_proj['Com Levantador'].sum()
        total_sem_sum = df_proj['Sem Levantador'].sum()
        total_lev_atuais_sum = df_proj['Levantadores Atuais'].sum()
        total_novos_sum = df_proj['Novos Levantadores'].sum()
        total_gap_sum = df_proj['Gap Restante'].sum()
        total_cob_sum = ((total_com_sum + df_edited['Municipios Ganhos'].sum()) / total_mun_sum * 100) if total_mun_sum > 0 else 0
        
        linha_total = pd.DataFrame([{
            'Regional': 'TOTAL ESTADO',
            'Total Municípios': total_mun_sum,
            'Com Levantador': total_com_sum,
            'Sem Levantador': total_sem_sum,
            'Levantadores Atuais': total_lev_atuais_sum,
            'Novos Levantadores': total_novos_sum,
            'Gap Restante': total_gap_sum,
            'Cobertura %': total_cob_sum
        }])
        
        df_proj = pd.concat([df_proj, linha_total], ignore_index=True)
        df_proj['Cobertura %'] = df_proj['Cobertura %'].apply(lambda x: f"{x:.1f}%")

        def colorir_cobertura(val):
            try:
                percentual = float(val.replace('%', ''))
                if percentual < 50.0: return 'background-color: #F8D7DA; color: #721C24; font-weight: bold;'
                elif percentual < 100.0: return 'background-color: #FFF3CD; color: #856404; font-weight: bold;'
                else: return 'background-color: #D4EDDA; color: #155724; font-weight: bold;'
            except:
                return ''
                
        try:
            styled_proj = df_proj.style.map(
                lambda v: 'color: #D9534F; font-weight: bold;' if (isinstance(v, (int, float)) and v > 0) else '', 
                subset=['Gap Restante']
            ).map(colorir_cobertura, subset=['Cobertura %'])
        except AttributeError:
            styled_proj = df_proj.style.applymap(
                lambda v: 'color: #D9534F; font-weight: bold;' if (isinstance(v, (int, float)) and v > 0) else '', 
                subset=['Gap Restante']
            ).applymap(colorir_cobertura, subset=['Cobertura %'])

        st.dataframe(styled_proj, use_container_width=True, hide_index=True)

    # BLINDAGEM DO GRÁFICO DO SIMULADOR DE ALOCAÇÃO
    with col_proj_chart:
        df_edited['Gap Restante'] = pd.to_numeric(df_edited['Gap Restante'], errors='coerce').fillna(0)
        df_chart = df_edited[df_edited['Gap Restante'] > 0]
        
        if not df_chart.empty and df_chart['Gap Restante'].sum() > 0:
            try:
                fig_rosca = px.pie(
                    df_chart, 
                    names='Regional', 
                    values='Gap Restante', 
                    hole=0.55,
                    title="Gap de Cobertura por Regional"
                )
                fig_rosca.update_traces(textinfo='percent', hoverinfo='label+value', marker=dict(line=dict(color='#000000', width=1)))
                fig_rosca.update_layout(margin=dict(t=40, b=0, l=0, r=0), legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5))
                st.plotly_chart(fig_rosca, use_container_width=True, config={'displayModeBar': False})
            except Exception:
                st.warning("O gráfico de Gap não pôde ser renderizado no momento.")
        else:
            st.success("✅ 100% de Cobertura Atingida! Nenhum município sem levantador nas projeções.")

    st.markdown("<h4 style='background-color: #4A4F7C; color: white; padding: 5px 10px; margin-top: 20px; border-radius: 5px;'>Resumo de Impacto</h4>", unsafe_allow_html=True)
    
    df_impacto = pd.DataFrame({
        "Métrica": ["Novos Levantadores", "Municípios Sem Levantador", "Cobertura Estadual"],
        "Atual": [total_lev_atuais_sum, total_sem_sum, f"{cob_atual:.1f}%"],
        "Após Contratações": [total_lev_atuais_sum + total_novos_sum, total_gap_sum, f"{total_cob_sum:.1f}%"],
        "Variação": [f"+{total_novos_sum}" if total_novos_sum > 0 else "0", 
                     total_gap_sum - total_sem_sum, 
                     f"+{(total_cob_sum - cob_atual):.1f}%" if (total_cob_sum - cob_atual) > 0 else "0.0%"]
    })
    
    def style_variacao(v):
        if isinstance(v, str):
            if v.startswith('+') or v == '0' or v == '0.0%': return 'color: #5CB85C; font-weight: bold;'
            elif v.startswith('-'): return 'color: #D9534F; font-weight: bold;'
        if isinstance(v, (int, float)):
            if v >= 0: return 'color: #5CB85C; font-weight: bold;'
            else: return 'color: #D9534F; font-weight: bold;'
        return ''

    try:
        styled_impacto = df_impacto.style.map(style_variacao, subset=['Variação'])
    except AttributeError:
        styled_impacto = df_impacto.style.applymap(style_variacao, subset=['Variação'])
        
    st.dataframe(styled_impacto, use_container_width=True, hide_index=True)

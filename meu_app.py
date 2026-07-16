import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.express as px
import numpy as np
import os
import io
import sqlite3
import pandera as pa
import streamlit_antd_components as sac
import tempfile
import geopandas as gpd
import zipfile
import logging
import hashlib
import shutil
import html
import re
from datetime import datetime, timedelta

# =============================================================================
# CONSTANTES E CONFIGURAÇÕES
# =============================================================================
DB_PATH = 'controle_torre_nip.db'
SEM_LEVANTADOR = 'SEM LEVANTADOR'
STATUS_PRODUTIVIDADE = ["CORRECAO DE LEVANTAMENTO", "EM LEVANTAMENTO", "PRE ANALISE"]

st.set_page_config(page_title="Portal Corporativo NIP", layout="wide", page_icon="🏗️", initial_sidebar_state="expanded")

try:
    import fiona
    fiona.drvsupport.supported_drivers['KML'] = 'rw'
    fiona.drvsupport.supported_drivers['LIBKML'] = 'rw'
except AttributeError:
    try:
        fiona.supported_drivers['KML'] = 'rw'
        fiona.supported_drivers['LIBKML'] = 'rw'
    except:
        logging.warning("Suporte KML Fiona pode estar limitado.")

# =============================================================================
# ENGINE 1: BANCO DE DADOS E SEGURANÇA (SQLITE / SHA-256 / INDEXES)
# =============================================================================
def hash_senha(senha):
    """Gera hash criptográfico para proteger as senhas no Banco de Dados."""
    return hashlib.sha256(str(senha).encode('utf-8')).hexdigest()

def init_databases():
    """Cria tabelas base, injeção do ADMIN e cria índices de alta performance."""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        # Segurança e Usuários
        conn.execute('''CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, role TEXT, last_active TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS auditoria_log (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, data_hora TEXT, acao TEXT, detalhes TEXT)''')
        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('THOMAS', ?, 'ADMIN')", (hash_senha('admin123'),))
        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('VISITANTE', ?, 'LEITURA')", (hash_senha('123'),))
        
        # Histórico KMZ
        os.makedirs("kmz_history", exist_ok=True)
        os.makedirs("kmz_extracted", exist_ok=True)
        conn.execute('''CREATE TABLE IF NOT EXISTS historico_kmz (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, data_upload TEXT, usuario TEXT, filepath TEXT)''')
        
        # Aceleração de Consultas
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lev ON notas (LEVANTADOR);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reg ON notas (REGIONAL);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mun ON notas (MUNICIPIO);")
        except Exception: pass
        conn.commit()

def sync_residencias_banco():
    """Garante estruturação de colunas e auto-preenche a base corporativa"""
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(equipes)")
                if 'Residencia' not in [col[1] for col in cursor.fetchall()]:
                    conn.execute("ALTER TABLE equipes ADD COLUMN Residencia TEXT")
                conn.commit()
                
            map_hardcoded = {
                "ARGELL CARLOS LOPES AZEVEDO": "SANTA INES", "EDELSON SOUSA GUIMARÃES": "CHAPADINHA",
                "FÁBIO ALTINO DE SOUZA JUNIOR": "IMPERATRIZ", "ISRAEL GARRAS VERAS": "SAO LUIS",
                "JEFFERSON COSTA JANSEM": "SITIO NOVO", "JEIAN CLAUDIO NAVA PEREIRA": "AÇAILANDIA",
                "JOSÉ ANTÔNIO LEITE ALVES": "PERI MIRIM", "LUÍS FERREIRA DE ARAUJO": "TIMON",
                "LUIZ ALESSANDRO OLIVEIRA CASTRO CONRADO DA SILVA": "BARRA DO CORDA", "MAILSON DA SILVA BARBOSA": "BERNARDO DO MEARIM",
                "MARCONE DE OLIVEIRA FERREIRA": "BACABAL", "MARCOS DA SILVA NEVES": "BARREIRINHAS",
                "OSVALDO RABELO DIAS JUNIOR": "APICUM-ACU", "RAIMUNDO JHONES ASSUNÇÃO DA LUZ": "COROATA"
            }
            for lev, res in map_hardcoded.items():
                conn.execute("UPDATE equipes SET Residencia = ? WHERE UPPER(TRIM(Levantador)) = ?", (res.upper(), lev.upper()))
            conn.commit()
    except Exception as e:
        logging.error(f"Erro de sincronização de banco: {e}")

def init_business_db():
    colunas_oficiais = ['ID SISCO', 'STATUS SISCO', 'TIPO LIGACAO SISCO', 'DESCRIÇÃO SERVIÇO SISCO', 'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO', 'DATA DE VENCIMENTO']
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notas';").fetchone():
                df_legacy = pd.read_excel('NOTAS.xlsx').fillna("").astype(str) if os.path.exists('NOTAS.xlsx') else pd.DataFrame(columns=colunas_oficiais)
                for col in colunas_oficiais:
                    if col not in df_legacy.columns: df_legacy[col] = ""
                df_legacy[colunas_oficiais].to_sql('notas', conn, if_exists='replace', index=False)
                    
            if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';").fetchone():
                if os.path.exists('base levantador.xlsx'): pd.read_excel('base levantador.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
                elif os.path.exists('EQUIPES.xlsx'): pd.read_excel('EQUIPES.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
                else: pd.DataFrame(columns=['Município', 'Estado', 'Levantador', 'Regional', 'Longitude', 'Latitude', 'Equipe', 'Residencia']).to_sql('equipes', conn, if_exists='replace', index=False)
    except Exception as e: pass

if 'db_initialized' not in st.session_state:
    init_databases()
    init_business_db()
    sync_residencias_banco()
    st.session_state.db_initialized = True

def registrar_auditoria(acao, detalhes):
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.execute("INSERT INTO auditoria_log (usuario, data_hora, acao, detalhes) VALUES (?, ?, ?, ?)",
                         (st.session_state.usuario_logado, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), acao, detalhes))
            conn.commit()
    except Exception: pass

# =============================================================================
# ENGINE 2: PROCESSAMENTO DE DADOS (VETORIZAÇÃO E CACHE)
# =============================================================================
def vectorized_haversine(lat1, lon1, lat2_series, lon2_series):
    """Calculo de raio curvo global otimizado em C++ via Numpy."""
    try:
        R = 6371.0 
        lat1_rad, lon1_rad = np.radians(float(str(lat1).replace(',','.'))), np.radians(float(str(lon1).replace(',','.')))
        lat2_rad = np.radians(pd.to_numeric(lat2_series.astype(str).str.replace(',', '.'), errors='coerce'))
        lon2_rad = np.radians(pd.to_numeric(lon2_series.astype(str).str.replace(',', '.'), errors='coerce'))
        dlat, dlon = lat2_rad - lat1_rad, lon2_rad - lon1_rad
        a = np.sin(dlat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2)**2
        return R * (2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))
    except Exception: return pd.Series(99999, index=lat2_series.index)

@st.cache_data(show_spinner=False)
def parse_kmz_advanced(file_path):
    import xml.etree.ElementTree as ET
    from shapely.geometry import Point, LineString
    gdf_lines, gdf_points = gpd.GeoDataFrame(columns=['Name', 'geometry'], geometry='geometry'), gpd.GeoDataFrame(columns=['Name', 'geometry'], geometry='geometry')
    try:
        ext_dir = os.path.join("kmz_extracted", hashlib.md5(file_path.encode()).hexdigest())
        os.makedirs(ext_dir, exist_ok=True)
        if file_path.lower().endswith('.kmz'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref: zip_ref.extractall(ext_dir)
            kml_file = next((os.path.join(root, f) for root, _, files in os.walk(ext_dir) for f in files if f.lower().endswith('.kml')), None)
        else: kml_file = file_path 
            
        if kml_file:
            with open(kml_file, 'rb') as f: kml_str = f.read().decode('utf-8', errors='ignore')
            kml_str = re.sub(r'<kml.*?>', '<kml>', re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', kml_str, flags=re.IGNORECASE), flags=re.IGNORECASE|re.DOTALL)
            root = ET.fromstring(kml_str)
            for elem in root.iter(): elem.tag = elem.tag.split('}', 1)[-1]
            pts, lns = [], []
            for pm in root.findall('.//Placemark'):
                name = pm.findtext('.//name', default="Sem Nome").strip()
                if (c := pm.findtext('.//Point/coordinates')):
                    coords = c.strip().split(',')
                    if len(coords) >= 2: pts.append({'Name': name, 'geometry': Point(float(coords[0]), float(coords[1]))})
                if (c := pm.findtext('.//LineString/coordinates')):
                    line_coords = [(float(p.split(',')[0]), float(p.split(',')[1])) for p in c.strip().split() if len(p.split(',')) >= 2]
                    if len(line_coords) >= 2: lns.append({'Name': name, 'geometry': LineString(line_coords)})
            if pts: gdf_points = gpd.GeoDataFrame(pts, geometry='geometry', crs="EPSG:4326")
            if lns: gdf_lines = gpd.GeoDataFrame(lns, geometry='geometry', crs="EPSG:4326")
        return gdf_lines, gdf_points, None
    except Exception: return gdf_lines, gdf_points, None

@st.cache_data(show_spinner=False)
def load_core_data():
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        df_notas = pd.read_sql("SELECT * FROM notas", conn)
        df_equipes = pd.read_sql("SELECT * FROM equipes", conn)
        
    df_eq_clean = df_equipes.dropna(subset=['Município']).drop_duplicates(subset=['Município'])
    map_levs = df_eq_clean.set_index('Município')['Levantador'].to_dict()
    
    if 'MUNICIPIO' in df_notas.columns: df_notas['MUNICIPIO'] = df_notas['MUNICIPIO'].astype(str).str.upper().str.strip()
    if 'LEVANTADOR' not in df_notas.columns: df_notas['LEVANTADOR'] = SEM_LEVANTADOR
    else: df_notas['LEVANTADOR'] = df_notas['LEVANTADOR'].astype(str).str.upper().str.strip()
        
    mask_vazio = df_notas['LEVANTADOR'].isin([SEM_LEVANTADOR, '', 'NAN', 'NONE', '0']) | df_notas['LEVANTADOR'].isna()
    if 'MUNICIPIO' in df_notas.columns:
        df_notas.loc[mask_vazio, 'LEVANTADOR'] = df_notas.loc[mask_vazio, 'MUNICIPIO'].map(map_levs).fillna(SEM_LEVANTADOR)
    
    df_notas['STATUS LIST'] = df_notas.get('STATUS LIST', pd.Series(['']*len(df_notas))).astype(str).str.upper().str.strip()
    
    mapa_lat = pd.to_numeric(df_eq_clean.set_index('Município').get('Latitude', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce').to_dict()
    mapa_lon = pd.to_numeric(df_eq_clean.set_index('Município').get('Longitude', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce').to_dict()
    df_notas['Lat_Mapa'] = df_notas.get('MUNICIPIO', pd.Series()).map(mapa_lat)
    df_notas['Lon_Mapa'] = df_notas.get('MUNICIPIO', pd.Series()).map(mapa_lon)

    mun_por_lev = df_equipes.groupby('Levantador')['Município'].nunique().reset_index().rename(columns={'Município': 'Qtd_Municipios'})
    contagem_prod = df_notas[df_notas['STATUS LIST'].isin(STATUS_PRODUTIVIDADE)]['LEVANTADOR'].value_counts().reset_index()
    contagem_prod.columns = ['Levantador', 'Total_Obras_Real']

    todos_lev = [l for l in df_equipes['Levantador'].dropna().unique() if str(l).strip() not in [SEM_LEVANTADOR, 'NAN', '', 'None']]
    resumo_lev = pd.merge(pd.DataFrame({'Levantador': todos_lev}), contagem_prod, on='Levantador', how='left').fillna(0)
    resumo_lev['Total_Obras_Real'] = resumo_lev['Total_Obras_Real'].astype(int)
    resumo_lev['Equipe'] = resumo_lev['Levantador'].map(df_equipes.dropna(subset=['Levantador', 'Equipe']).drop_duplicates(subset=['Levantador']).set_index('Levantador')['Equipe'].to_dict()).fillna('SEM EQUIPE')
    
    return df_notas, df_equipes, resumo_lev, resumo_lev[resumo_lev['Total_Obras_Real'] < 45]['Levantador'].tolist(), todos_lev, mapa_lat, mapa_lon, mun_por_lev

# =============================================================================
# ENGINE 3: RENDERIZADOR WEBGL (PYDECK - ALTA PERFORMANCE)
# =============================================================================
def render_pydeck_map(df_notas_mapa, df_eq_mapa_view, criticos_tuple, caminho_camada_temp):
    """Substitui o Folium por WebGL nativo. Renderiza 100k pontos sem travar."""
    layers = []
    
    # Camada 1: Cidades/Bases das Equipes (Verde)
    if not df_eq_mapa_view.empty:
        df_eq = df_eq_mapa_view.copy()
        df_eq['Lat'] = pd.to_numeric(df_eq['Latitude'].astype(str).str.replace(',', '.'), errors='coerce')
        df_eq['Lon'] = pd.to_numeric(df_eq['Longitude'].astype(str).str.replace(',', '.'), errors='coerce')
        df_eq = df_eq.dropna(subset=['Lat', 'Lon'])
        df_eq['Tooltip'] = "Base: " + df_eq['Levantador'].astype(str)
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=df_eq, get_position=["Lon", "Lat"],
            get_color=[0, 255, 0, 200], get_radius=3000, pickable=True
        ))

    # Camada 2: Obras na Fila e Ativas
    if not df_notas_mapa.empty:
        df_ob = df_notas_mapa.dropna(subset=['Lat_Mapa', 'Lon_Mapa']).copy()
        # Jitter para evitar sobreposição total
        df_ob['Lat_Mapa'] += np.random.normal(0, 0.003, len(df_ob))
        df_ob['Lon_Mapa'] += np.random.normal(0, 0.003, len(df_ob))
        df_ob['Tooltip'] = "Protocolo: " + df_ob['PROTOCOLO'].astype(str) + "\nLevantador: " + df_ob['LEVANTADOR'].astype(str)
        
        # Vetorização de cor rápida em lista
        df_ob['Color_RGBA'] = [
            [255, 165, 0, 200] if lev == SEM_LEVANTADOR else 
            ([255, 0, 0, 200] if lev in criticos_tuple else [0, 123, 255, 200])
            for lev in df_ob['LEVANTADOR']
        ]
        
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=df_ob, get_position=["Lon_Mapa", "Lat_Mapa"],
            get_color="Color_RGBA", get_radius=800, pickable=True
        ))

    # Camada 3: Geometria de Projetos KMZ/KML extraídos em alta velocidade
    if caminho_camada_temp:
        gdf_lines, gdf_points, _ = parse_kmz_advanced(caminho_camada_temp)
        if not gdf_lines.empty:
            layers.append(pdk.Layer("GeoJsonLayer", data=gdf_lines, get_line_color=[26, 79, 124, 255], get_line_width=3, pickable=False))
        if not gdf_points.empty:
            gdf_points['Tooltip'] = "Ponto Georreferenciado: " + gdf_points['Name']
            layers.append(pdk.Layer("GeoJsonLayer", data=gdf_points, get_fill_color=[220, 53, 69, 255], get_point_radius=100, pickable=True))

    r = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=-5.2, longitude=-45.0, zoom=6, pitch=0),
        tooltip={"text": "{Tooltip}"},
        map_style=pdk.map_styles.SATELLITE
    )
    st.pydeck_chart(r, use_container_width=True)

# =============================================================================
# MODULOS DA INTERFACE DE USUÁRIO (TELAS E ROTAS)
# =============================================================================
def check_login():
    if 'usuario_logado' not in st.session_state:
        st.session_state.usuario_logado = None
        st.session_state.perfil_usuario = None

    if st.session_state.usuario_logado is None:
        st.markdown("<h2 style='text-align: center; margin-top: 80px; color: #1A4F7C;'>🔐 Portal Corporativo NIP</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #666;'>Sistema de Governança de Redes de Distribuição</p>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            with st.form("login_form"):
                st.markdown("#### Acesso Restrito")
                username = st.text_input("Usuário").strip().upper()
                password = st.text_input("Senha", type="password")
                if st.form_submit_button("Autenticar", type="primary", use_container_width=True):
                    with sqlite3.connect(DB_PATH, timeout=10) as conn:
                        result = conn.execute("SELECT password, role FROM usuarios WHERE username=?", (username,)).fetchone()
                        if result:
                            db_pwd, role = result
                            input_hash = hash_senha(password)
                            if db_pwd == input_hash or db_pwd == password:
                                if db_pwd == password: conn.execute("UPDATE usuarios SET password=? WHERE username=?", (input_hash, username))
                                st.session_state.usuario_logado = username
                                st.session_state.perfil_usuario = role
                                conn.execute("UPDATE usuarios SET last_active = ? WHERE username = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username))
                                conn.commit()
                                st.rerun()
                            else: st.error("Credenciais inválidas.")
                        else: st.error("Acesso revogado ou inexistente.")
            st.info("💡 **Aviso:** Insira suas credenciais corporativas.")
        st.stop()
        
    if st.session_state.get('perfil_usuario') != 'ADMIN':
        st.markdown("""<style>#MainMenu {visibility: hidden;} header {visibility: hidden;}</style>""", unsafe_allow_html=True)
        
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.execute("UPDATE usuarios SET last_active = ? WHERE username = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.usuario_logado))
            conn.commit()
    except: pass

def kpi_card(title, value, subtitle="", border_color="#1A4F7C"):
    return f"""
    <div style="background-color: #f8f9fa; border-radius: 8px; padding: 15px; border-left: 5px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.05); height: 100%;">
        <p style="margin:0; font-size: 14px; color: #555; text-transform: uppercase; letter-spacing: 0.5px;">{title}</p>
        <h2 style="margin: 5px 0 0 0; color: #333; font-size: 32px;">{value}</h2>
        {f'<p style="margin: 5px 0 0 0; font-size: 12px; color: #777;">{subtitle}</p>' if subtitle else ''}
    </div>
    """

def render_filtros_governanca(df_notas):
    col_f1, col_f2, col_f3 = st.columns(3)
    col_f4, col_f5, col_f6 = st.columns(3)
    
    op_lev = ["TODOS"] + sorted([str(x) for x in df_notas.get('LEVANTADOR', pd.Series()).dropna().unique()])
    if 'ui_lev' not in st.session_state or st.session_state.ui_lev not in op_lev: st.session_state.ui_lev = 'TODOS'
    with col_f1: filtro_lev = st.selectbox("Filtrar por Levantador:", op_lev, key='ui_lev')

    op_reg = ["TODOS"] + sorted([str(x) for x in df_notas.get('REGIONAL', pd.Series()).dropna().unique()])
    if 'ui_reg' not in st.session_state or st.session_state.ui_reg not in op_reg: st.session_state.ui_reg = 'TODOS'
    with col_f2: filtro_reg = st.selectbox("Filtrar por Regional:", op_reg, key='ui_reg')

    op_mun = ["TODOS"] + sorted([str(x) for x in df_notas.get('MUNICIPIO', pd.Series()).dropna().unique()])
    if 'ui_mun' not in st.session_state or st.session_state.ui_mun not in op_mun: st.session_state.ui_mun = 'TODOS'
    with col_f3: filtro_mun = st.selectbox("Filtrar por Município:", op_mun, key='ui_mun')

    op_lig = ["TODOS"] + sorted([str(x) for x in df_notas.get('TIPO LIGACAO', pd.Series()).dropna().astype(str).unique()])
    if 'ui_lig' not in st.session_state or st.session_state.ui_lig not in op_lig: st.session_state.ui_lig = 'TODOS'
    with col_f4: filtro_lig = st.selectbox("Filtrar por Tipo Ligação:", op_lig, key='ui_lig')

    op_sap = ["TODOS"] + sorted([str(x) for x in df_notas.get('STATUS SAP', pd.Series()).dropna().unique()])
    if 'ui_sap' not in st.session_state or st.session_state.ui_sap not in op_sap: st.session_state.ui_sap = 'TODOS'
    with col_f5: filtro_sap = st.selectbox("Filtrar por Status SAP:", op_sap, key='ui_sap')

    op_list = sorted([str(x) for x in df_notas.get('STATUS LIST', pd.Series()).dropna().unique() if str(x).strip() != ""])
    if 'ui_list' not in st.session_state: st.session_state.ui_list = []
    st.session_state.ui_list = [x for x in st.session_state.ui_list if x in op_list]
    with col_f6: filtro_list = st.multiselect("Filtrar por Status List (Vazio = TODOS):", options=op_list, key='ui_list')

    df_filtrado = df_notas.copy()
    if filtro_lev != "TODOS": df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'] == filtro_lev]
    if filtro_reg != "TODOS": df_filtrado = df_filtrado[df_filtrado['REGIONAL'] == filtro_reg]
    if filtro_mun != "TODOS": df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'] == filtro_mun]
    if filtro_lig != "TODOS": df_filtrado = df_filtrado[df_filtrado['TIPO LIGACAO'].astype(str) == filtro_lig]
    if filtro_sap != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS SAP'] == filtro_sap]
    if len(filtro_list) > 0: df_filtrado = df_filtrado[df_filtrado['STATUS LIST'].isin(filtro_list)]
    
    return df_filtrado, filtro_list, op_sap, op_list

def filtrar_levantador_governanca(nome_lev):
    st.session_state.ui_lev = nome_lev
    st.session_state.ui_reg = 'TODOS'
    st.session_state.ui_mun = 'TODOS'
    st.session_state.ui_lig = 'TODOS'
    st.session_state.ui_sap = 'TODOS'
    st.session_state.ui_list = STATUS_PRODUTIVIDADE.copy() 
    st.session_state.menu_idx = 1
    st.toast(f"Filtrando demandas operacionais de {nome_lev}...", icon="🔍")

# --- ABA 1: PAINEL EXECUTIVO ---
def view_painel_executivo():
    df_notas_db, df_equipes_db, resumo_levantadores, levantadores_criticos, todos_levantadores, mapa_lat, mapa_lon, municipios_por_levantador = load_core_data()
    
    st.markdown("### 📈 Visão Global de Produtividade")
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("O banco de dados está vazio. Realize uma carga em lote.")
        return
        
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi_card("Obras Reais Atribuídas", int(resumo_levantadores['Total_Obras_Real'].sum()), "Volume em operação", "#4A4F7C"), unsafe_allow_html=True)
    k2.markdown(kpi_card("Equipes/Levantadores", len(resumo_levantadores), "Ativos em campo", "#5CB85C"), unsafe_allow_html=True)
    k3.markdown(kpi_card("Obras Livres (Fila)", len(df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db.get('STATUS LIST', pd.Series()).isin(STATUS_PRODUTIVIDADE))]), "Sem atribuição", "#F0AD4E"), unsafe_allow_html=True)
    k4.markdown(kpi_card("Levantadores Críticos", len(levantadores_criticos), "Abaixo de 45 obras", "#D9534F" if len(levantadores_criticos) > 0 else "#5CB85C"), unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    col_t1, col_t2 = st.columns([2.5, 1.5])
    with col_t1:
        st.markdown("#### 📋 Desempenho e Alocação das Equipes")
        st.dataframe(resumo_levantadores[['Levantador', 'Equipe', 'Total_Obras_Real']].sort_values('Total_Obras_Real', ascending=False), 
                     use_container_width=True, hide_index=True, height=320, 
                     column_config={"Levantador": "Técnico", "Equipe": "SAP", "Total_Obras_Real": st.column_config.ProgressColumn("Obras (Meta: 45)", format="%d", min_value=0, max_value=45)})
        
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
                            df_livres = df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db.get('STATUS LIST', pd.Series()).isin(STATUS_PRODUTIVIDADE))].copy()
                            if len(df_livres) == 0: st.error("Fila Vazia!"); st.session_state.assign_step = 0
                            else:
                                tr = df_equipes_db[df_equipes_db['Levantador'] == lev_sel]
                                r_lat = mapa_lat.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Latitude']).replace(',','.'))
                                r_lon = mapa_lon.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Longitude']).replace(',','.'))
                                
                                df_livres['L_Lat'] = pd.to_numeric(df_livres.get('MUNICIPIO').map(mapa_lat), errors='coerce')
                                df_livres['L_Lon'] = pd.to_numeric(df_livres.get('MUNICIPIO').map(mapa_lon), errors='coerce')
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
            
            st.button("🔍 Ver Base", on_click=filtrar_levantador_governanca, args=(lev_sel,), use_container_width=True)
            
    # Geração de Demanda Otimizada (Painel Interativo)
    if st.session_state.get('show_demanda', False):
        st.markdown("---")
        st.markdown(f"#### 📋 Gerador de Demanda - {lev_sel}")
        df_demanda = df_notas_db[(df_notas_db['LEVANTADOR'] == lev_sel) & (df_notas_db.get('STATUS LIST', pd.Series()).isin(STATUS_PRODUTIVIDADE))].copy()
        
        if len(df_demanda) > 0:
            tr = df_equipes_db[df_equipes_db['Levantador'] == lev_sel]
            r_lat = mapa_lat.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Latitude']).replace(',','.'))
            r_lon = mapa_lon.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Longitude']).replace(',','.'))
            
            df_demanda['D_KM'] = vectorized_haversine(r_lat, r_lon, pd.to_numeric(df_demanda.get('MUNICIPIO').map(mapa_lat), errors='coerce'), pd.to_numeric(df_demanda.get('MUNICIPIO').map(mapa_lon), errors='coerce'))
            df_demanda = df_demanda.sort_values('D_KM')
            
            # Exportação Cega Estrita
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
            
    # Gráficos SLA
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

    # PyDeck Map (Performance Extrema WebGL)
    st.markdown("---")
    st.markdown("### 🗺️ Roteirização Geoespacial (WebGL GPU)")
    col_f1, col_f2, col_f3 = st.columns(3)
    
    op_map_lev = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('LEVANTADOR', pd.Series()).dropna().unique()])
    op_map_reg = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('REGIONAL', pd.Series()).dropna().unique()])
    op_map_mun = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('MUNICIPIO', pd.Series()).dropna().unique()])

    f_lev = col_f1.selectbox("Filtro Levantador:", op_map_lev)
    f_reg = col_f2.selectbox("Filtro Regional:", op_map_reg)
    f_mun = col_f3.selectbox("Filtro Município:", op_map_mun)
    
    df_m = df_notas_db.copy()
    if f_lev != "TODOS": df_m = df_m[df_m['LEVANTADOR'].astype(str).str.upper() == f_lev]
    if f_reg != "TODOS": df_m = df_m[df_m['REGIONAL'].astype(str).str.upper() == f_reg]
    if f_mun != "TODOS": df_m = df_m[df_m['MUNICIPIO'].astype(str).str.upper() == f_mun]
    
    st.info(f"📍 Renderizando {len(df_m)} obras via PyDeck Hardware Acceleration.")
    camada = st.file_uploader("Sobrepor KML/KMZ Rápido", type=['kml', 'kmz'], label_visibility="collapsed")
    camada_p = None
    if camada:
        ext = camada.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp: tmp.write(camada.getvalue()); camada_p = tmp.name

    df_e = df_equipes_db.copy()
    if f_lev != "TODOS": df_e = df_e[df_e['Levantador'].astype(str).str.upper() == f_lev]
    render_pydeck_map(df_m, df_e, tuple(levantadores_criticos), camada_p)

# --- ABA 2: GOVERNANÇA E FILTROS ---
def view_governanca():
    st.markdown("### 📝 Governança Direta")
    df = get_processed_data()[0]
    df_f, l1, l2, l3 = render_filtros_governanca(df)
    st.info(f"Localizadas: {len(df_f)} notas.")
    
    c_btn1, c_btn2, c_btn3 = st.columns([2, 2, 6])
    if not df_f.empty:
        buf = io.BytesIO()
        df_f.to_excel(buf, index=False)
        c_btn1.download_button("📥 Excel", data=buf.getvalue(), file_name="gov_filtro.xlsx", use_container_width=True)
        
    admin = st.session_state.perfil_usuario == "ADMIN"
    btn_save = c_btn2.button("💾 Salvar DB", type="primary", use_container_width=True) if admin else c_btn2.button("🔒 Restrito", disabled=True, use_container_width=True)
    if admin:
        with c_btn3.expander("⚠️ ÁREA DE PERIGO"):
            if st.button("🚨 APAGAR TUDO", type="primary", disabled=not st.checkbox("Confirmo")):
                save_notas_to_db(pd.DataFrame(columns=df.columns), backup=True); st.rerun()
                
    df_edit = st.data_editor(df_f.fillna(""), use_container_width=True, num_rows="dynamic", disabled=not admin,
                             column_config={"ID SISCO": st.column_config.TextColumn(disabled=True), "STATUS SAP": st.column_config.SelectboxColumn(options=l2), "STATUS LIST": st.column_config.SelectboxColumn(options=l3)})
    if btn_save:
        df_up = df.copy(); df_up.loc[df_edit.index] = df_edit
        if save_notas_to_db(df_up, acao_auditoria="Edição Governança"): st.toast("Salvo!"); load_core_data.clear(); st.rerun()

# --- ABA 3: CARGA DE LOTES ---
def view_carga():
    if st.session_state.perfil_usuario != "ADMIN": st.error("Restrito."); return
    st.markdown("### 📤 Importação Strict")
    s_nip = pa.DataFrameSchema({"PROTOCOLO": pa.Column(pa.String, coerce=True, required=True), "MUNICIPIO": pa.Column(pa.String, coerce=True, required=True)}, strict=False)
    upl = st.file_uploader("Lote de Demandas", type=["csv", "xlsx"])
    if upl:
        df_n = pd.read_csv(upl) if upl.name.endswith('.csv') else pd.read_excel(upl)
        df_n = df_n.dropna(subset=['MUNICIPIO', 'PROTOCOLO']).copy()
        df_n['PROTOCOLO'] = df_n['PROTOCOLO'].astype(str).str.replace(r'\.0$', '', regex=True)
        try:
            df_v = s_nip.validate(df_n)
            st.success("Homologado!")
            df_proc = auto_assign_levantador(df_v, get_processed_data()[1])
            if st.button("⚡ Gravar DB"):
                if save_notas_to_db(pd.concat([get_processed_data()[0], df_proc], ignore_index=True), backup=True): st.rerun()
        except Exception as e: st.error(f"Erro no Lote: {e}")

# --- ABA 4: LEVANTADORES ---
def view_levantadores():
    if st.session_state.perfil_usuario != "ADMIN": st.error("Restrito."); return
    st.markdown("### 👷 Gestão Residencial")
    
    with sqlite3.connect(DB_PATH, timeout=10) as conn: df_eq = pd.read_sql("SELECT * FROM equipes", conn)
    df_levs = df_eq[['Levantador', 'Equipe', 'Residencia']].drop_duplicates(subset=['Levantador']).copy()
    op_mun = [""] + sorted([str(x).upper() for x in df_eq['Município'].dropna().unique() if str(x).strip() != ''])
    
    df_ed = st.data_editor(df_levs, column_config={"Levantador": st.column_config.TextColumn(disabled=True), "Equipe": st.column_config.TextColumn(disabled=True), "Residencia": st.column_config.SelectboxColumn(options=op_mun)}, hide_index=True, use_container_width=True)
    if st.button("💾 Atualizar", type="primary"):
        df_eq['Residencia'] = df_eq['Levantador'].map(df_ed.set_index('Levantador')['Residencia'].to_dict())
        with sqlite3.connect(DB_PATH, timeout=10) as conn: df_eq.to_sql('equipes', conn, if_exists='replace', index=False)
        load_core_data.clear(); st.rerun()

    st.markdown("#### ➕ Novo Membro")
    with st.form("new_lev"):
        c1, c2, c3 = st.columns(3)
        nome, eq, res = c1.text_input("Nome"), c2.text_input("Equipe"), c3.selectbox("Residência", op_mun)
        if st.form_submit_button("Cadastrar", type="primary"):
            if nome and eq and res:
                with sqlite3.connect(DB_PATH) as conn: conn.execute("INSERT INTO equipes (Levantador, Equipe, Residencia) VALUES (?, ?, ?)", (nome.upper(), eq.upper(), res))
                load_core_data.clear(); st.rerun()

# --- ABA 5: GERENCIAMENTO DE ACESSOS ---
def view_acessos():
    if st.session_state.perfil_usuario != "ADMIN": st.error("Restrito."); return
    st.markdown("### 🔐 Controle de Acesso (SHA-256)")
    with sqlite3.connect(DB_PATH, timeout=10) as conn: df_usr = pd.read_sql("SELECT username, role FROM usuarios", conn)
    df_usr['Apagar'] = False
    
    ed_usr = st.data_editor(df_usr, hide_index=True, use_container_width=True, column_config={"username": st.column_config.TextColumn(disabled=True), "role": st.column_config.SelectboxColumn(options=["ADMIN", "LEITURA"])})
    if st.button("Salvar Permissões", type="primary"):
        with sqlite3.connect(DB_PATH) as conn:
            for _, r in ed_usr.iterrows():
                if r['Apagar'] and r['username'] != st.session_state.usuario_logado: conn.execute("DELETE FROM usuarios WHERE username=?", (r['username'],))
                elif not r['Apagar']: conn.execute("UPDATE usuarios SET role=? WHERE username=?", (r['role'], r['username']))
        st.rerun()
        
    st.markdown("#### ➕ Nova Conta")
    with st.form("n_usr"):
        c1, c2, c3 = st.columns(3)
        u, p, rol = c1.text_input("Usuário").upper(), c2.text_input("Senha", type="password"), c3.selectbox("Perfil", ["LEITURA", "ADMIN"])
        if st.form_submit_button("Criar"):
            try:
                with sqlite3.connect(DB_PATH) as conn: conn.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", (u, hash_senha(p), rol))
                st.rerun()
            except: st.error("Usuário já existe.")

# --- ABA 6: SIMULADOR ---
def view_simulador():
    st.markdown("<h2 style='text-align: center; color: #1A4F7C;'>Simulador de Alocação de Levantadores</h2>", unsafe_allow_html=True)
    df_e = get_processed_data()[1].copy()
    mun_t = df_e.groupby('Regional')['Município'].nunique().reset_index(name='Total')
    vm = df_e['Levantador'].notna() & (~df_e['Levantador'].isin([SEM_LEVANTADOR, 'NAN', '']))
    mun_c = df_e[vm].groupby('Regional')['Município'].nunique().reset_index(name='Cobertos')
    lev_a = df_e[vm].groupby('Regional')['Levantador'].nunique().reset_index(name='Levantadores')
    
    df_s = mun_t.merge(mun_c, on='Regional', how='left').merge(lev_a, on='Regional', how='left').fillna(0)
    df_s['Gap'] = df_s['Total'] - df_s['Cobertos']
    df_s['CapMedia'] = np.where(df_s['Levantadores']>0, df_s['Cobertos']/df_s['Levantadores'], 0)
    df_s['Novos'] = 0
    
    st.data_editor(df_s, disabled=['Regional', 'Total', 'Cobertos', 'Gap', 'Levantadores', 'CapMedia'], use_container_width=True)

# -----------------------------------------------------------------------------
# ROTEAMENTO GLOBAL (LAZY EXECUTION)
# -----------------------------------------------------------------------------
check_login()

if menu_selecionado == 'Painel Executivo': view_painel_executivo()
elif menu_selecionado == 'Busca e Governança': view_governanca()
elif menu_selecionado == 'Carga de Lotes': view_carga()
elif menu_selecionado == 'Levantadores': view_levantadores()
elif menu_selecionado == 'Gerenciamento de Acessos': view_acessos()
elif menu_selecionado == 'Simulador de Alocação': view_simulador()

# HEARTBEAT OTIMIZADO
if st.session_state.usuario_logado:
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            ativos = pd.read_sql(f"SELECT username, role FROM usuarios WHERE last_active >= '{ (datetime.now() - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S') }'", conn)
        if not ativos.empty:
            st.markdown("---")
            st.markdown("#### 🟢 Usuários Online")
            st.markdown("".join([f"<span style='background-color: #d4edda; color: #155724; padding: 4px 10px; border-radius: 12px; margin-right: 8px; font-size: 13px; font-weight: bold; border: 1px solid #c3e6cb;'>👤 {r['username']} ({r['role']})</span>" for _, r in ativos.iterrows()]), unsafe_allow_html=True)
    except: pass

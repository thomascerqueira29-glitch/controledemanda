import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster, FastMarkerCluster, MeasureControl, Draw
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
import shutil
import html
import re
import hashlib
from datetime import datetime, timedelta
from PIL import Image

# -----------------------------------------------------------------------------
# CONSTANTES GLOBAIS E CONFIGURAÇÕES INICIAIS
# -----------------------------------------------------------------------------
DB_PATH = 'controle_torre_nip.db'
SEM_LEVANTADOR = 'SEM LEVANTADOR'
STATUS_PRODUTIVIDADE = ["CORRECAO DE LEVANTAMENTO", "EM LEVANTAMENTO", "PRE ANALISE"]

st.set_page_config(page_title="Portal Corporativo NIP", layout="wide", page_icon="🏗️", initial_sidebar_state="expanded")

try:
    import fiona
    try:
        fiona.drvsupport.supported_drivers['KML'] = 'rw'
        fiona.drvsupport.supported_drivers['LIBKML'] = 'rw'
    except AttributeError:
        fiona.supported_drivers['KML'] = 'rw'
        fiona.supported_drivers['LIBKML'] = 'rw'
except ImportError:
    logging.warning("Módulo fiona não instalado. Suporte a KML pode estar limitado.")

# -----------------------------------------------------------------------------
# 1. MOTOR DE IDENTIDADE E BANCOS DE DADOS
# -----------------------------------------------------------------------------
def init_iam():
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                        (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
        try:
            conn.execute("ALTER TABLE usuarios ADD COLUMN last_active TEXT")
        except sqlite3.OperationalError:
            pass
            
        conn.execute('''CREATE TABLE IF NOT EXISTS auditoria_log 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, 
                         data_hora TEXT, acao TEXT, detalhes TEXT)''')

        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('THOMAS', 'admin123', 'ADMIN')")
        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('VISITANTE', '123', 'LEITURA')")
        conn.commit()

def init_kmz_db():
    os.makedirs("kmz_history", exist_ok=True)
    os.makedirs("kmz_extracted", exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS historico_kmz 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                         nome TEXT, 
                         data_upload TEXT, 
                         usuario TEXT, 
                         filepath TEXT)''')
        conn.commit()

# Inicialização movida para setup_application() com st.cache_resource

def update_residencias_hardcoded():
    mapeamento_residencias = {
        "ARGELL CARLOS LOPES AZEVEDO": "SANTA INES",
        "EDELSON SOUSA GUIMARÃES": "CHAPADINHA",
        "FÁBIO ALTINO DE SOUZA JUNIOR": "IMPERATRIZ",
        "ISRAEL GARRAS VERAS": "SAO LUIS",
        "JEFFERSON COSTA JANSEM": "SITIO NOVO",
        "JEIAN CLAUDIO NAVA PEREIRA": "AÇAILANDIA",
        "JOSÉ ANTÔNIO LEITE ALVES": "PERI MIRIM",
        "LUÍS FERREIRA DE ARAUJO": "TIMON",
        "LUIZ ALESSANDRO OLIVEIRA CASTRO CONRADO DA SILVA": "BARRA DO CORDA",
        "MAILSON DA SILVA BARBOSA": "BERNARDO DO MEARIM",
        "MARCONE DE OLIVEIRA FERREIRA": "BACABAL",
        "MARCOS DA SILVA NEVES": "BARREIRINHAS",
        "OSVALDO RABELO DIAS JUNIOR": "APICUM-ACU",
        "RAIMUNDO JHONES ASSUNÇÃO DA LUZ": "COROATA"
    }
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            for lev, res in mapeamento_residencias.items():
                conn.execute("UPDATE equipes SET Residencia = ? WHERE UPPER(TRIM(Levantador)) = ?", (res.upper(), lev.upper()))
            conn.commit()
    except Exception:
        pass

def ensure_residencia_column():
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(equipes)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'Residencia' not in columns:
                    conn.execute("ALTER TABLE equipes ADD COLUMN Residencia TEXT")
                    if os.path.exists('base levantador.xlsx'):
                        df_base = pd.read_excel('base levantador.xlsx')
                        if 'Residencia' in df_base.columns:
                            map_res = df_base.set_index('Levantador')['Residencia'].dropna().to_dict()
                            for lev, res in map_res.items():
                                conn.execute("UPDATE equipes SET Residencia = ? WHERE Levantador = ?", (str(res).upper().strip(), lev))
                    conn.commit()
    except Exception:
        pass

def init_business_db():
    colunas_template_oficial = [
        'ID SISCO', 'STATUS SISCO', 'TIPO LIGACAO SISCO', 'DESCRIÇÃO SERVIÇO SISCO', 
        'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 'DATA ENVIO A CAMPO - LIST', 
        'DATA DE LEVANTAMENTO LIST', 'PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 
        'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 
        'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO', 'DATA DE VENCIMENTO'
    ]
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notas';")
            if not cursor.fetchone():
                if os.path.exists('NOTAS.xlsx'):
                    df_legacy = pd.read_excel('NOTAS.xlsx').fillna("").astype(str).replace({"nan": "", "NaT": "", "None": "", "<NA>": ""})
                    for col in colunas_template_oficial:
                        if col not in df_legacy.columns: df_legacy[col] = ""
                    df_legacy = df_legacy[colunas_template_oficial]
                    df_legacy.to_sql('notas', conn, if_exists='replace', index=False)
                else:
                    pd.DataFrame(columns=colunas_template_oficial).to_sql('notas', conn, if_exists='replace', index=False)
                    
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
            if not cursor.fetchone():
                if os.path.exists('base levantador.xlsx'):
                    pd.read_excel('base levantador.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
                elif os.path.exists('EQUIPES.xlsx'):
                    pd.read_excel('EQUIPES.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
                else:
                    pd.DataFrame(columns=['Município', 'Estado', 'Levantador', 'Regional', 'Longitude', 'Latitude', 'Equipe', 'Residencia']).to_sql('equipes', conn, if_exists='replace', index=False)
        st.session_state.db_initialized = True
    except Exception:
        pass

@st.cache_resource
def setup_application():
    init_iam()
    init_kmz_db()
    init_business_db()
    ensure_residencia_column()
    update_residencias_hardcoded()
    return True

if 'app_ready' not in st.session_state:
    setup_application()
    st.session_state.app_ready = True

# -----------------------------------------------------------------------------
# 3. MÓDULO DE SEGURANÇA E AUTENTICAÇÃO (LOGIN)
# -----------------------------------------------------------------------------
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
            submit = st.form_submit_button("Autenticar", type="primary", use_container_width=True)
            
            if submit:
                with sqlite3.connect(DB_PATH, timeout=10) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT role FROM usuarios WHERE username=? AND password=?", (username, password))
                    result = cursor.fetchone()
                    
                    if result:
                        st.session_state.usuario_logado = username
                        st.session_state.perfil_usuario = result[0]
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        conn.execute("UPDATE usuarios SET last_active = ? WHERE username = ?", (now_str, username))
                        conn.commit()
                        st.rerun()
                    else:
                        st.error("Credenciais inválidas ou acesso revogado.")
        
        st.info("💡 **Aviso:** Insira suas credenciais corporativas para acessar o sistema.")
    st.stop() 

if st.session_state.get('perfil_usuario') != 'ADMIN':
    st.markdown("""<style>#MainMenu {visibility: hidden;} header {visibility: hidden;}</style>""", unsafe_allow_html=True)

def atualizar_sessao():
    if st.session_state.usuario_logado:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with sqlite3.connect(DB_PATH, timeout=10) as conn:
                conn.execute("UPDATE usuarios SET last_active = ? WHERE username = ?", (now_str, st.session_state.usuario_logado))
                conn.commit()
        except sqlite3.OperationalError:
            pass 

atualizar_sessao()

if 'menu_idx' not in st.session_state:
    st.session_state.menu_idx = 0
if 'selected_ponto_gis' not in st.session_state:
    st.session_state.selected_ponto_gis = None

def filtrar_levantador_governanca(nome_lev):
    st.session_state.ui_lev = nome_lev
    st.session_state.ui_reg = 'TODOS'
    st.session_state.ui_mun = 'TODOS'
    st.session_state.ui_lig = 'TODOS'
    st.session_state.ui_sap = 'TODOS'
    st.session_state.ui_list = STATUS_PRODUTIVIDADE.copy() 
    st.session_state.menu_idx = 2
    st.toast(f"Filtrando demandas operacionais de {nome_lev}...", icon="🔍")

def kpi_card(title, value, subtitle="", border_color="#1A4F7C"):
    return f"""
    <div style="background-color: #f8f9fa; border-radius: 8px; padding: 15px; border-left: 5px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.05); height: 100%;">
        <p style="margin:0; font-size: 14px; color: #555; text-transform: uppercase; letter-spacing: 0.5px;">{title}</p>
        <h2 style="margin: 5px 0 0 0; color: #333; font-size: 32px;">{value}</h2>
        {f'<p style="margin: 5px 0 0 0; font-size: 12px; color: #777;">{subtitle}</p>' if subtitle else ''}
    </div>
    """

# -----------------------------------------------------------------------------
# MOTORES DE ALTA PERFORMANCE E GIS MAPPING
# -----------------------------------------------------------------------------
def registrar_auditoria(acao, detalhes):
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            usuario = st.session_state.usuario_logado
            conn.execute("INSERT INTO auditoria_log (usuario, data_hora, acao, detalhes) VALUES (?, ?, ?, ?)",
                         (usuario, agora, acao, detalhes))
            conn.commit()
    except Exception: pass

def auto_assign_levantador(df_notas, df_equipes):
    df_notas = df_notas.copy()
    df_eq_clean = df_equipes.dropna(subset=['Município']).drop_duplicates(subset=['Município'])
    mapa_levantadores = df_eq_clean.set_index('Município')['Levantador'].to_dict()
    
    if 'MUNICIPIO' in df_notas.columns: df_notas['MUNICIPIO'] = df_notas['MUNICIPIO'].astype(str).str.upper().str.strip()
    if 'LEVANTADOR' not in df_notas.columns: df_notas['LEVANTADOR'] = SEM_LEVANTADOR
    else: df_notas['LEVANTADOR'] = df_notas['LEVANTADOR'].astype(str).str.upper().str.strip()
        
    mask_sem_levantador = (
        df_notas['LEVANTADOR'].isna() | (df_notas['LEVANTADOR'] == SEM_LEVANTADOR) | 
        (df_notas['LEVANTADOR'] == '') | (df_notas['LEVANTADOR'] == 'NAN') | 
        (df_notas['LEVANTADOR'] == 'NONE') | (df_notas['LEVANTADOR'] == '0')
    )
    
    if 'MUNICIPIO' in df_notas.columns:
        df_notas.loc[mask_sem_levantador, 'LEVANTADOR'] = df_notas.loc[mask_sem_levantador, 'MUNICIPIO'].map(mapa_levantadores).fillna(SEM_LEVANTADOR)
    
    for col in ['STATUS LIST', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'STATUS SISCO', 'DATA CRIAÇAO SISCO', 'DATA DE VENCIMENTO']:
        if col not in df_notas.columns: df_notas[col] = ""
            
    df_notas['STATUS LIST'] = df_notas['STATUS LIST'].astype(str).str.upper().str.strip()
    return df_notas

@st.cache_data(show_spinner=False)
def get_processed_data():
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        df_n = pd.read_sql("SELECT * FROM notas", conn)
        df_e = pd.read_sql("SELECT * FROM equipes", conn)
    return auto_assign_levantador(df_n, df_e), df_e

def save_notas_to_db(df_notas_atualizado, backup=False, acao_auditoria="Operação no Banco de Dados"):
    try:
        df_notas_limpo = df_notas_atualizado.copy().fillna("").astype(str).replace({"nan": "", "NaT": "", "None": "", "<NA>": ""})
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            df_notas_limpo.to_sql('notas_temp', conn, if_exists='replace', index=False)
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DROP TABLE IF EXISTS notas;")
            conn.execute("ALTER TABLE notas_temp RENAME TO notas;")
            conn.commit()
            
        registrar_auditoria(acao_auditoria, f"Tabela NOTAS atualizada. Volume final: {len(df_notas_limpo)} registros.")
        get_processed_data.clear()
        process_analytical_data.clear()
        return True
    except sqlite3.Error as e:
        st.error(f"Falha Crítica no Banco de Dados: {e}")
        return False

df_notas_db, df_equipes_db = get_processed_data()

def vectorized_haversine(lat1, lon1, lat2_series, lon2_series):
    try:
        R = 6371.0 
        lat1_rad, lon1_rad = np.radians(float(lat1)), np.radians(float(lon1))
        lat2_rad, lon2_rad = np.radians(lat2_series.astype(float)), np.radians(lon2_series.astype(float))
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        a = np.sin(dlat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return R * c
    except (ValueError, TypeError):
        return pd.Series(99999, index=lat2_series.index)

@st.cache_data(show_spinner=False)
def parse_kmz_advanced(file_path):
    import defusedxml.ElementTree as ET
    from shapely.geometry import Point, LineString
    
    gdf_lines = gpd.GeoDataFrame(columns=['Name', 'Description', 'geometry'], geometry='geometry')
    gdf_points = gpd.GeoDataFrame(columns=['Name', 'Description', 'geometry'], geometry='geometry')
    bounds = None
    
    hash_name = hashlib.sha256(file_path.encode()).hexdigest()
    ext_dir = os.path.join("kmz_extracted", hash_name)
    os.makedirs(ext_dir, exist_ok=True)
    
    kml_file = None
    try:
        if file_path.lower().endswith('.kmz'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(ext_dir)
            for root, dirs, files in os.walk(ext_dir):
                for f in files:
                    if f.lower().endswith('.kml'):
                        kml_file = os.path.join(root, f)
                        break
                if kml_file: break
        else:
            kml_file = file_path 
            
        if kml_file:
            with open(kml_file, 'rb') as f:
                kml_bytes = f.read()
            
            kml_str = kml_bytes.decode('utf-8', errors='ignore')
            kml_str = re.sub(r'\sxmlns="[^"]+"', '', kml_str, count=1)
            kml_str = re.sub(r'\sxmlns:\w+="[^"]+"', '', kml_str)
            kml_str = re.sub(r'<kml.*?>', '<kml>', kml_str, flags=re.IGNORECASE|re.DOTALL)
            
            try:
                root = ET.fromstring(kml_str)
            except ET.ParseError:
                kml_str = re.sub(r'&(?!(?:apos|quot|amp|lt|gt);)', '&amp;', kml_str)
                root = ET.fromstring(kml_str)
                
            for elem in root.iter():
                if '}' in elem.tag:
                    elem.tag = elem.tag.split('}', 1)[1]
                    
            points_list = []
            lines_list = []
            
            for pm in root.findall('.//Placemark'):
                name_node = pm.find('.//name')
                pm_name = name_node.text.strip() if name_node is not None and name_node.text else "Ponto Sem Nome"
                
                desc_node = pm.find('.//description')
                pm_desc = desc_node.text.strip() if desc_node is not None and desc_node.text else ""
                
                if not pm_desc:
                    ext_data = pm.find('.//ExtendedData')
                    if ext_data is not None:
                        for data in ext_data.findall('.//Data'):
                            d_name = data.get('name', '')
                            v_node = data.find('value')
                            d_val = v_node.text if v_node is not None and v_node.text else ''
                            pm_desc += f"<b>{d_name}:</b> {d_val}<br>"

                pt_node = pm.find('.//Point/coordinates')
                if pt_node is not None and pt_node.text:
                    coords = pt_node.text.strip().split(',')
                    if len(coords) >= 2:
                        try:
                            points_list.append({
                                'Name': pm_name,
                                'Description': pm_desc,
                                'geometry': Point(float(coords[0]), float(coords[1]))
                            })
                        except: pass
                    continue
                    
                ls_node = pm.find('.//LineString/coordinates')
                if ls_node is not None and ls_node.text:
                    coords_str = ls_node.text.strip().split()
                    line_coords = []
                    for c in coords_str:
                        parts = c.split(',')
                        if len(parts) >= 2:
                            try: line_coords.append((float(parts[0]), float(parts[1])))
                            except: pass
                    if len(line_coords) >= 2:
                        lines_list.append({
                            'Name': pm_name,
                            'Description': pm_desc,
                            'geometry': LineString(line_coords)
                        })
                        
            if points_list:
                gdf_points = gpd.GeoDataFrame(points_list, geometry='geometry')
                gdf_points.crs = "EPSG:4326"
            if lines_list:
                gdf_lines = gpd.GeoDataFrame(lines_list, geometry='geometry')
                gdf_lines.crs = "EPSG:4326"
                
            if not gdf_points.empty or not gdf_lines.empty:
                all_geoms = pd.concat([gdf_points['geometry'] if not gdf_points.empty else pd.Series(dtype=object), 
                                       gdf_lines['geometry'] if not gdf_lines.empty else pd.Series(dtype=object)])
                bounds = gpd.GeoSeries(all_geoms).total_bounds
                
        return gdf_lines, gdf_points, bounds, ext_dir
    except Exception as e:
        logging.error(f"Erro no parse KMZ avançado: {e}")
        return gdf_lines, gdf_points, None, ext_dir

def get_images_from_desc(desc, extract_dir):
    """Busca robusta de imagens na pasta extraida. Faz match do nome na description com o arquivo fisico"""
    valid_imgs = []
    
    if not os.path.exists(extract_dir): return valid_imgs
    
    # Pega todos os arquivos jpg/png que existem fisicamente na pasta descompactada
    arquivos_fisicos = []
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                arquivos_fisicos.append(os.path.join(root, f))
                
    if not desc or pd.isna(desc): return arquivos_fisicos[:5] # Se não tem descrição, mostra algumas perdidas
    
    desc_str = str(desc)
    
    # Tenta achar os nomes literais dos arquivos fisicos dentro do HTML da descricao
    for img_path in arquivos_fisicos:
        filename = os.path.basename(img_path)
        if filename in desc_str:
            valid_imgs.append(img_path)
            
    # Fallback: Se não achou por nome literal, varre tags src/href
    if not valid_imgs:
        imgs_tags = re.findall(r'src=["\']?(.*?\.(?:jpg|jpeg|png))["\']?', desc_str, re.IGNORECASE)
        if not imgs_tags:
            imgs_tags = re.findall(r'href=["\']?(.*?\.(?:jpg|jpeg|png))["\']?', desc_str, re.IGNORECASE)
            
        for img in imgs_tags:
            if str(img).startswith('http'):
                if img not in valid_imgs: valid_imgs.append(img)
            else:
                img_clean = img.replace('\\', '/')
                img_path = os.path.join(extract_dir, img_clean)
                if os.path.exists(img_path) and img_path not in valid_imgs:
                    valid_imgs.append(img_path)
                    
    return valid_imgs

@st.cache_data(show_spinner=False)
def processar_camada_espacial(arquivo_espacial):
    """Leitura cega para o mapa do Painel Executivo"""
    gdf_lines = gpd.GeoDataFrame()
    gdf_points = gpd.GeoDataFrame()
    bounds = None
    if not arquivo_espacial: return gdf_lines, gdf_points, bounds
    import fiona
    try:
        camadas = fiona.listlayers(arquivo_espacial)
        gdfs = []
        for camada in camadas:
            try:
                gdf_temp = gpd.read_file(arquivo_espacial, driver='KML', layer=camada)
                if not gdf_temp.empty:
                    gdf_temp['Layer_Name'] = camada
                    gdfs.append(gdf_temp)
            except Exception: continue
                
        if gdfs:
            gdf_final = pd.concat(gdfs, ignore_index=True)
            gdf_final['geometry'] = gdf_final['geometry'].simplify(tolerance=0.0001, preserve_topology=True)
            
            for col in gdf_final.columns:
                if col != 'geometry':
                    gdf_final[col] = gdf_final[col].astype(str).replace({'nan': '', '<NA>': '', 'None': '', 'NaT': ''})
                    
            gdf_lines = gdf_final[gdf_final.geometry.type.isin(['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon'])]
            gdf_points = gdf_final[gdf_final.geometry.type == 'Point']
            bounds = gdf_final.total_bounds
    except Exception: pass
    return gdf_lines, gdf_points, bounds

@st.cache_data(show_spinner=False)
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

    todos_lev = [l for l in df_equipes_db['Levantador'].dropna().unique() if str(l).strip() not in [SEM_LEVANTADOR, 'NAN', '', 'None']]
    resumo_lev = pd.DataFrame({'Levantador': todos_lev})
    resumo_lev = pd.merge(resumo_lev, contagem_prod, on='Levantador', how='left').fillna(0)
    resumo_lev['Total_Obras_Real'] = resumo_lev['Total_Obras_Real'].astype(int)

    mapa_lev_equipe = df_equipes_db.dropna(subset=['Levantador', 'Equipe']).drop_duplicates(subset=['Levantador']).set_index('Levantador')['Equipe'].to_dict()
    resumo_lev['Equipe'] = resumo_lev['Levantador'].map(mapa_lev_equipe).fillna('SEM EQUIPE')

    lev_criticos = resumo_lev[resumo_lev['Total_Obras_Real'] < 45]['Levantador'].tolist()
    return df_notas_calc, resumo_lev, lev_criticos, mapa_lat, mapa_lon, mun_por_lev, todos_lev

df_notas_calc, resumo_levantadores, levantadores_criticos, mapa_lat, mapa_lon, municipios_por_levantador, todos_levantadores = process_analytical_data(df_notas_db, df_equipes_db)

# -----------------------------------------------------------------------------
# INTERFACE DE NAVEGAÇÃO LATERAL
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 👤 Portal NIP")
    st.caption(f"Usuário: **{st.session_state.usuario_logado}**")
    st.caption(f"Perfil: **{st.session_state.perfil_usuario}**")
    
    if st.button("🚪 Sair / Deslogar", use_container_width=True):
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.execute("UPDATE usuarios SET last_active = NULL WHERE username = ?", (st.session_state.usuario_logado,))
            conn.commit()
        st.session_state.usuario_logado = None
        st.session_state.perfil_usuario = None
        st.rerun()

    st.markdown("---")
    
    opcoes_menu = ['Painel Executivo', 'Leitor KMZ', 'Busca e Governança', 'Simulador de Alocação']
    icones_menu = ['pie-chart-fill', 'map-fill', 'sliders', 'calculator-fill']
    
    if st.session_state.perfil_usuario == "ADMIN":
        opcoes_menu.insert(4, 'Carga de Lotes')
        icones_menu.insert(4, 'cloud-upload-fill')
        opcoes_menu.insert(5, 'Levantadores')
        icones_menu.insert(5, 'person-vcard-fill')
        opcoes_menu.insert(6, 'Gerenciamento de Acessos')
        icones_menu.insert(6, 'shield-lock-fill')
        
    menu_items = [sac.MenuItem(opcoes_menu[i], icon=icones_menu[i]) for i in range(len(opcoes_menu))]
    
    if st.session_state.menu_idx >= len(opcoes_menu):
        st.session_state.menu_idx = 0
        
    menu_selecionado = sac.menu(menu_items, index=st.session_state.menu_idx, format_func='title', size='md')
    
    if menu_selecionado in opcoes_menu:
        st.session_state.menu_idx = opcoes_menu.index(menu_selecionado)

# -----------------------------------------------------------------------------
# VISÃO 1: PAINEL EXECUTIVO
# -----------------------------------------------------------------------------
if menu_selecionado == 'Painel Executivo':
    st.markdown("### 📈 Visão Global de Produtividade")
    
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("O banco de dados de notas está vazio. Realize uma carga em lote para ativar os indicadores.")
    else:
        total_obras = int(resumo_levantadores['Total_Obras_Real'].sum())
        total_ativos = len(resumo_levantadores)
        total_criticos = len(levantadores_criticos)
        obras_livres = len(df_notas_db[(df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))])
        
        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(kpi_card("Obras Reais Atribuídas", total_obras, "Volume em operação", "#4A4F7C"), unsafe_allow_html=True)
        k2.markdown(kpi_card("Equipes/Levantadores", total_ativos, "Ativos em campo", "#5CB85C"), unsafe_allow_html=True)
        k3.markdown(kpi_card("Obras Livres (Fila)", obras_livres, "Sem atribuição", "#F0AD4E"), unsafe_allow_html=True)
        k4.markdown(kpi_card("Levantadores Críticos", total_criticos, "Abaixo de 45 obras", "#D9534F" if total_criticos > 0 else "#5CB85C"), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        col_t1, col_t2 = st.columns([2.5, 1.5])
        with col_t1:
            st.markdown("#### 📋 Desempenho e Alocação das Equipes")
            df_resumo_view = resumo_levantadores[['Levantador', 'Equipe', 'Total_Obras_Real']].copy()
            df_resumo_view = df_resumo_view.sort_values('Total_Obras_Real', ascending=False)
            
            st.dataframe(
                df_resumo_view, use_container_width=True, hide_index=True, height=320,
                column_config={
                    "Levantador": st.column_config.TextColumn("Levantador / Técnico"),
                    "Equipe": st.column_config.TextColumn("Equipe SAP"),
                    "Total_Obras_Real": st.column_config.ProgressColumn("Obras Reais (Meta: 45)", format="%d", min_value=0, max_value=45)
                }
            )
            
        with col_t2:
            st.markdown("#### ⚡ Painel de Ações Rápidas")
            st.caption("Selecione um levantador para tomar decisões.")
            _, central_col, _ = st.columns([0.2, 9, 0.2])
            with central_col:
                st.markdown("<div style='padding: 20px; border: 1px solid #EAEAEA; border-radius: 8px; background: #FAFAFA;'>", unsafe_allow_html=True)
                lev_selecionado = st.selectbox("Levantador:", todos_levantadores, label_visibility="collapsed")
                
                if st.session_state.get('last_lev_selecionado') != lev_selecionado:
                    st.session_state.assign_step = 0
                    st.session_state.show_demanda = False
                    st.session_state.last_lev_selecionado = lev_selecionado
                
                obras_do_lev = int(resumo_levantadores[resumo_levantadores['Levantador'] == lev_selecionado]['Total_Obras_Real'].iloc[0])
                saldo_necessario = max(0, 45 - obras_do_lev)
                
                st.info(f"Obras Vinculadas Atualmente: **{obras_do_lev}**")
                
                if st.session_state.perfil_usuario == "ADMIN":
                    if obras_do_lev < 45:
                        if st.session_state.get('assign_step', 0) == 0:
                            if st.button(f"⚡ Atribuir +{saldo_necessario} Obras Próximas", use_container_width=True, type="primary"):
                                st.session_state.assign_step = 1
                                st.rerun()
                                
                        elif st.session_state.assign_step == 1:
                            st.warning(f"Confirmar atribuição de +{saldo_necessario} obras para {lev_selecionado}?")
                            col_conf1, col_conf2 = st.columns(2)
                            if col_conf1.button("✅ Confirmar Ação", use_container_width=True, type="primary"):
                                cond_livres_reais = (df_notas_db['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))
                                df_livres = df_notas_db[cond_livres_reais].copy()
                                
                                if len(df_livres) == 0: 
                                    st.error("Fila vazia! Sem demandas livres no momento.")
                                    st.session_state.assign_step = 0
                                else:
                                    with st.spinner(f"Calculando rotas otimizadas para {lev_selecionado}..."):
                                        tech_rows = df_equipes_db[df_equipes_db['Levantador'] == lev_selecionado]
                                        tech_residencia = tech_rows['Residencia'].iloc[0] if 'Residencia' in tech_rows.columns else None
                                        
                                        res_lat, res_lon = np.nan, np.nan
                                        if pd.notna(tech_residencia) and str(tech_residencia).strip() != "":
                                            res_lat = mapa_lat.get(str(tech_residencia).strip().upper())
                                            res_lon = mapa_lon.get(str(tech_residencia).strip().upper())
                                            
                                        if pd.isna(res_lat) or pd.isna(res_lon):
                                            res_lat = tech_rows.iloc[0]['Latitude']
                                            res_lon = tech_rows.iloc[0]['Longitude']
                                            
                                        df_livres['Lat_Mapa'] = pd.to_numeric(df_livres['MUNICIPIO'].map(mapa_lat), errors='coerce')
                                        df_livres['Lon_Mapa'] = pd.to_numeric(df_livres['MUNICIPIO'].map(mapa_lon), errors='coerce')
                                        df_livres['Distancia_KM'] = vectorized_haversine(res_lat, res_lon, df_livres['Lat_Mapa'], df_livres['Lon_Mapa'])
                                        df_livres = df_livres.sort_values('Distancia_KM')

                                        df_notas_update = df_notas_db.copy()
                                        qtd_atribuir = min(saldo_necessario, len(df_livres))
                                        indices_para_mudar = df_livres.head(qtd_atribuir).index
                                        
                                        df_notas_update.loc[indices_para_mudar, 'LEVANTADOR'] = lev_selecionado
                                        
                                        if save_notas_to_db(df_notas_update, acao_auditoria=f"Atribuição Geo-otimizada: {qtd_atribuir} obras para {lev_selecionado}"):
                                            st.toast("Rotas designadas com sucesso!", icon="✅")
                                            st.success(f"{qtd_atribuir} obras vinculadas a {lev_selecionado}.")
                                            st.session_state.assign_step = 2
                                            st.rerun()
                                            
                            if col_conf2.button("❌ Cancelar", use_container_width=True):
                                st.session_state.assign_step = 0
                                st.rerun()
                                
                        elif st.session_state.assign_step == 2:
                            st.success("✅ Atribuição confirmada.")
                            if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"):
                                st.session_state.show_demanda = True
                                st.session_state.assign_step = 0
                                st.rerun()
                    else: 
                        st.success("✅ Meta Atingida.")
                        if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"):
                            st.session_state.show_demanda = True
                            
                else:
                    st.warning("🔒 Acesso restrito. Módulo exclusivo para Coordenação.")
                    
                st.button("🔍 Ver Base de Obras", on_click=filtrar_levantador_governanca, args=(lev_selecionado,), use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
                
        # --- GERAÇÃO DE DEMANDA POR ROTEIRIZAÇÃO (CORES E EXPORTAÇÃO KML/EXCEL) ---
        if st.session_state.get('show_demanda', False):
            st.markdown("---")
            st.markdown(f"#### 📋 Gerador de Demanda Otimizado - {lev_selecionado}")
            st.caption("A distância é calculada em linha reta a partir da cidade-base de **Residência** cadastrada para o levantador.")
            
            cond_demanda = (df_notas_calc['LEVANTADOR'] == lev_selecionado) & (df_notas_calc['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))
            df_demanda = df_notas_calc[cond_demanda].copy()
            
            if len(df_demanda) > 0:
                tech_rows = df_equipes_db[df_equipes_db['Levantador'] == lev_selecionado]
                tech_residencia = tech_rows['Residencia'].iloc[0] if 'Residencia' in tech_rows.columns else None
                
                res_lat, res_lon = np.nan, np.nan
                if pd.notna(tech_residencia) and str(tech_residencia).strip() != "":
                    res_lat = mapa_lat.get(str(tech_residencia).strip().upper())
                    res_lon = mapa_lon.get(str(tech_residencia).strip().upper())
                    
                if pd.isna(res_lat) or pd.isna(res_lon):
                    res_lat = tech_rows.iloc[0]['Latitude']
                    res_lon = tech_rows.iloc[0]['Longitude']
                    
                df_demanda['Distancia_KM'] = vectorized_haversine(res_lat, res_lon, df_demanda['Lat_Mapa'], df_demanda['Lon_Mapa'])
                
                cols_view = ['PROTOCOLO', 'MUNICIPIO', 'ENDEREÇO', 'STATUS LIST', 'TIPO LIGACAO', 'Distancia_KM']
                for c in cols_view:
                    if c not in df_demanda.columns:
                        df_demanda[c] = ""
                        
                df_demanda_view = df_demanda[cols_view].copy()
                df_demanda_view = df_demanda_view.sort_values('Distancia_KM')
                
                dist_series = df_demanda_view['Distancia_KM'].copy() 
                
                df_demanda_view['Distancia_KM'] = df_demanda_view['Distancia_KM'].apply(
                    lambda x: f"{x:.1f}".replace('.', ',') if pd.notnull(x) and x != "" else ""
                )
                
                def color_rules(row):
                    dist = dist_series.loc[row.name]
                    if pd.isna(dist) or dist == "": color = ''
                    elif float(dist) <= 50: color = 'background-color: #00B050; color: white;' 
                    elif float(dist) <= 100: color = 'background-color: #FFFF00; color: black;' 
                    else: color = 'background-color: #FF0000; color: white;' 
                    return [color] * len(row)
                    
                st.dataframe(df_demanda_view.style.apply(color_rules, axis=1), use_container_width=True, hide_index=True)
                
                def is_valid_export(row):
                    t = str(row.get('TIPO LIGACAO', '')).strip().upper()
                    n = str(row.get('NOME DO SOLICITANTE', '')).strip().upper()
                    lat = str(row.get('LATITUDE', '')).strip().upper()
                    lon = str(row.get('LONGITUDE', '')).strip().upper()
                    
                    valid_t = t not in ['', 'NAN', 'NONE', '<NA>', '0', '0.0', '0,0']
                    valid_n = n not in ['', 'NAN', 'NONE', '<NA>']
                    valid_lat = lat not in ['', 'NAN', 'NONE', '<NA>', '0', '0.0', '0,0']
                    valid_lon = lon not in ['', 'NAN', 'NONE', '<NA>', '0', '0.0', '0,0']
                    return valid_t and valid_n and valid_lat and valid_lon

                valid_mask = df_demanda.apply(is_valid_export, axis=1)
                df_export_base = df_demanda[valid_mask].copy().sort_values('Distancia_KM')

                cols_export_oficial = ['PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 
                                       'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 
                                       'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO']
                
                df_export = df_export_base.copy()
                for c in cols_export_oficial:
                    if c not in df_export.columns:
                        df_export[c] = ""
                        
                df_export = df_export[cols_export_oficial]
                dist_export_series = df_export_base['Distancia_KM'] 
                
                def style_excel(row):
                    dist = dist_export_series.loc[row.name]
                    if pd.isna(dist) or dist == "": color = ''
                    elif float(dist) <= 50: color = 'background-color: #00B050; color: white;' 
                    elif float(dist) <= 100: color = 'background-color: #FFFF00; color: black;' 
                    else: color = 'background-color: #FF0000; color: white;' 
                    return [color] * len(row)
                
                styled_df_export = df_export.style.apply(style_excel, axis=1)

                buffer_excel = io.BytesIO()
                with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
                    styled_df_export.to_excel(writer, index=False, sheet_name='Demanda')
                
                def gerar_kml_demanda(df):
                    header = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
                    footer = '</Document>\n</kml>'
                    pms = []
                    for _, row in df.iterrows():
                        try:
                            lat = float(str(row.get('LATITUDE', '')).replace(',','.'))
                            lon = float(str(row.get('LONGITUDE', '')).replace(',','.'))
                            if not pd.isna(lat) and not pd.isna(lon):
                                pms.append(f'''<Placemark>
                                    <name>{html.escape(str(row.get('PROTOCOLO', '')))}</name>
                                    <description>{html.escape(str(row.get('ENDEREÇO', '')))}</description>
                                    <Point><coordinates>{lon},{lat},0</coordinates></Point>
                                </Placemark>\n''')
                        except ValueError:
                            pass
                    return (header + "".join(pms) + footer).encode('utf-8')
                
                kml_data = gerar_kml_demanda(df_export)

                st.markdown("<br>", unsafe_allow_html=True)
                st.info(f"⚡ **{len(df_export)} obras validadas** para exportação (Tipo Ligação, Coordenadas e Nome devidamente preenchidos na base).")
                
                hoje_str_file = datetime.now().strftime('%d_%m_%Y')
                col_btn1, col_btn2, col_btn3 = st.columns([2.5, 2.5, 4])
                
                col_btn1.download_button("📥 Planilha Oficial (Excel)", data=buffer_excel.getvalue(), file_name=f"Demanda_{lev_selecionado}_{hoje_str_file}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                col_btn2.download_button("🗺️ Pontos de Rota (KML)", data=kml_data, file_name=f"Demanda_{lev_selecionado}_{hoje_str_file}.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
                if col_btn3.button("Fechar Aba de Demanda", use_container_width=True):
                    st.session_state.show_demanda = False
                    st.rerun()
            else:
                st.warning("Nenhuma obra na fila de produtividade para este levantador. Utilize a Busca Governança para conferir o status.")
                if st.button("Fechar"):
                    st.session_state.show_demanda = False
                    st.rerun()

# -----------------------------------------------------------------------------
# VISÃO 2: LEITOR KMZ (GIS EARTH CLONE)
# -----------------------------------------------------------------------------
elif menu_selecionado == 'Leitor KMZ':
    # Oculta o Sidebar padrão para imersão GIS
    st.markdown("""
        <style>
        [data-testid="collapsedControl"] {display: none;}
        section[data-testid="stSidebar"] {display: none;}
        .block-container { padding-top: 1rem; padding-bottom: 0rem; padding-left: 1rem; padding-right: 1rem; max-width: 100%;}
        .gis-panel { background-color: #0b1120; color: #e2e8f0; padding: 15px; border-radius: 8px; border: 1px solid #1e293b; height: 85vh; overflow-y: auto;}
        .gis-header { font-size: 13px; font-weight: bold; color: #94a3b8; text-transform: uppercase; margin-bottom: 15px; border-bottom: 1px solid #1e293b; padding-bottom: 5px;}
        .gis-value { font-size: 13px; margin-bottom: 10px; color: #f8fafc; background-color: #1e293b; padding: 10px; border-radius: 4px; word-wrap: break-word;}
        .gis-title { color: #f8fafc; margin-bottom: 0px; padding-bottom: 10px; font-weight: 600;}
        </style>
    """, unsafe_allow_html=True)
    
    col_l, col_m, col_r = st.columns([2, 7, 3])
    
    with col_l:
        if st.button("⬅ Voltar ao Menu Inicial", use_container_width=True):
            st.session_state.menu_idx = 0
            st.rerun()
            
        st.markdown("<div class='gis-panel'>", unsafe_allow_html=True)
        st.markdown("<div class='gis-header'>📂 CARREGAR KML / KMZ</div>", unsafe_allow_html=True)
        
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            df_hist = pd.read_sql("SELECT * FROM historico_kmz ORDER BY id DESC", conn)
        
        opcoes_hist = ["-- Usar Novo Upload --"] + df_hist['nome'].tolist()
        hist_sel = st.selectbox("Histórico Salvo no Servidor:", opcoes_hist, label_visibility="collapsed")
        
        if st.session_state.perfil_usuario == "ADMIN" and hist_sel != "-- Usar Novo Upload --":
            if st.button("🗑️ Apagar Projeto", type="primary", use_container_width=True):
                row_h = df_hist[df_hist['nome'] == hist_sel].iloc[0]
                if os.path.exists(row_h['filepath']): os.remove(row_h['filepath'])
                with sqlite3.connect(DB_PATH, timeout=10) as conn:
                    conn.execute("DELETE FROM historico_kmz WHERE id=?", (int(row_h['id']),))
                    conn.commit()
                st.rerun()
        
        camada_gis = st.file_uploader("Upload de Arquivo Local", type=['kml', 'kmz'])
        
        caminho_ativo = None
        
        if hist_sel != "-- Usar Novo Upload --":
            caminho_ativo = df_hist[df_hist['nome'] == hist_sel].iloc[0]['filepath']
        elif camada_gis is not None:
            extensao = camada_gis.name.split('.')[-1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{extensao}') as tmp:
                tmp.write(camada_gis.getvalue())
                caminho_ativo = tmp.name
                
            nome_proj = st.text_input("Salvar novo Levantamento no Servidor:")
            if st.button("💾 Gravar Historico", use_container_width=True) and nome_proj:
                caminho_dest = f"kmz_history/{nome_proj}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extensao}"
                with open(caminho_dest, "wb") as f:
                    f.write(camada_gis.getvalue())
                with sqlite3.connect(DB_PATH, timeout=10) as conn:
                    conn.execute("INSERT INTO historico_kmz (nome, data_upload, usuario, filepath) VALUES (?, ?, ?, ?)",
                                 (nome_proj, datetime.now().strftime("%Y-%m-%d %H:%M"), st.session_state.usuario_logado, caminho_dest))
                    conn.commit()
                st.success("Salvo! Selecione o arquivo acima.")
                st.rerun()

        gdf_lines, gdf_points, bounds, temp_dir = gpd.GeoDataFrame(), gpd.GeoDataFrame(), None, None
        if caminho_ativo and os.path.exists(caminho_ativo):
            with st.spinner("Lendo metadados espaciais..."):
                gdf_lines, gdf_points, bounds, temp_dir = parse_kmz_advanced(caminho_ativo)
            
        st.markdown("<div class='gis-header' style='margin-top:20px;'>🔍 BUSCA DE PONTOS</div>", unsafe_allow_html=True)
        search_q = st.text_input("Nome do Cliente ou Coordenadas (Lat, Lng):", placeholder="Ex: -5.3, -45.1")
        
        lista_nomes = []
        if not gdf_points.empty:
            lista_nomes = gdf_points['Name'].tolist()
            if search_q:
                try:
                    partes = search_q.replace(';', ',').split(',')
                    if len(partes) >= 2:
                        lat_s, lon_s = float(partes[0].strip()), float(partes[1].strip())
                        gdf_points['dist_search'] = np.sqrt((gdf_points.geometry.y - lat_s)**2 + (gdf_points.geometry.x - lon_s)**2)
                        gdf_points = gdf_points.sort_values('dist_search')
                        lista_nomes = gdf_points['Name'].tolist()
                    else:
                        raise ValueError
                except:
                    gdf_points = gdf_points[gdf_points['Name'].str.contains(search_q, case=False, na=False)]
                    lista_nomes = gdf_points['Name'].tolist()
            
            idx_selecionado = 0
            if st.session_state.selected_ponto_gis in lista_nomes:
                idx_selecionado = lista_nomes.index(st.session_state.selected_ponto_gis) + 1
                
            escolha = st.selectbox("📌 Pontos Mapeados", ["-- Visualizar Todos --"] + lista_nomes, index=idx_selecionado)
            
            if escolha != "-- Visualizar Todos --":
                st.session_state.selected_ponto_gis = escolha
            else:
                st.session_state.selected_ponto_gis = None
        else:
            st.caption("Faça o upload do KMZ para carregar os pontos.")
            
        st.markdown("</div>", unsafe_allow_html=True)

    with col_m:
        mapa_gis = folium.Map(location=[-5.2, -45.0], zoom_start=7, tiles=None)
        
        # Padrão Esri Satélite Fixo
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
            attr='Esri', name='Satélite', overlay=False, control=False
        ).add_to(mapa_gis)
        
        # Ferramentas GIS Reais
        mapa_gis.add_child(MeasureControl(primary_length_unit='meters', primary_area_unit='sqmeters'))
        mapa_gis.add_child(Draw(export=True))
        
        ponto_foco = None
        
        if not gdf_lines.empty:
            folium.GeoJson(gdf_lines[['Name', 'geometry']], name="Linhas Desenhadas", style_function=lambda feature: {'color': '#FFD700', 'weight': 3, 'opacity': 0.8}).add_to(mapa_gis)

        if not gdf_points.empty:
            if st.session_state.selected_ponto_gis:
                match = gdf_points[gdf_points['Name'] == st.session_state.selected_ponto_gis]
                if not match.empty: ponto_foco = match.iloc[0]

            def get_point_style(feature):
                if ponto_foco is not None and feature['properties'].get('Name') == ponto_foco['Name']:
                    return {'fillColor': '#FF0000', 'color': '#FFFFFF', 'weight': 2, 'fillOpacity': 1, 'radius': 8.0}
                return {'fillColor': '#007BFF', 'color': '#FFFFFF', 'weight': 1, 'fillOpacity': 0.8, 'radius': 5.0}
            
            folium.GeoJson(
                gdf_points[['Name', 'geometry']], name="Marcadores do Levantamento", marker=folium.CircleMarker(), 
                style_function=get_point_style, tooltip=folium.GeoJsonTooltip(fields=['Name'], aliases=['Ponto: '])
            ).add_to(mapa_gis)
            
            if ponto_foco is not None:
                lat_foc, lon_foc = ponto_foco.geometry.y, ponto_foco.geometry.x
                mapa_gis.location = [lat_foc, lon_foc]
                mapa_gis.zoom_start = 18
            elif bounds is not None:
                mapa_gis.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
                
        map_data = st_folium(mapa_gis, use_container_width=True, height=800, returned_objects=['last_active_drawing'])
        
        if map_data and map_data.get('last_active_drawing'):
            clicado = map_data['last_active_drawing'].get('properties', {}).get('Name')
            if clicado and clicado != st.session_state.selected_ponto_gis:
                st.session_state.selected_ponto_gis = clicado
                st.rerun()

    with col_r:
        st.markdown("<div class='gis-panel'>", unsafe_allow_html=True)
        if st.session_state.selected_ponto_gis and not gdf_points.empty:
            match_pt = gdf_points[gdf_points['Name'] == st.session_state.selected_ponto_gis]
            if not match_pt.empty:
                pt_dados = match_pt.iloc[0]
                
                st.markdown("<div class='gis-header'>📍 PONTO SELECIONADO</div>", unsafe_allow_html=True)
                
                st.caption("CLIENTE / NOME DO MARCADOR")
                st.markdown(f"<div class='gis-value'><b>{pt_dados.get('Name', 'N/A')}</b></div>", unsafe_allow_html=True)
                
                st.caption("COORDENADAS DE REDE")
                lat_txt = f"{pt_dados.geometry.y:.6f}°"
                lon_txt = f"{pt_dados.geometry.x:.6f}°"
                st.markdown(f"<div class='gis-value'><b>Lat:</b> {lat_txt}<br><b>Lng:</b> {lon_txt}</div>", unsafe_allow_html=True)
                
                st.caption("DESCRIÇÃO TÉCNICA (HTML / OBS)")
                desc_html = pt_dados.get('Description', '')
                clean_desc = re.sub(r'<[^>]+>', ' ', str(desc_html)).strip()
                if not clean_desc: clean_desc = "Sem detalhes adicionais inseridos no arquivo."
                st.markdown(f"<div class='gis-value'>{clean_desc}</div>", unsafe_allow_html=True)
                
                st.markdown("<div class='gis-header' style='margin-top:20px;'>📸 FOTOS DO LEVANTAMENTO</div>", unsafe_allow_html=True)
                
                if temp_dir:
                    imagens_achadas = get_images_from_desc(desc_html, temp_dir)
                    if imagens_achadas:
                        st.caption(f"{len(imagens_achadas)} foto(s) anexada(s) à nota:")
                        for img_path in imagens_achadas:
                            try:
                                img_obj = Image.open(img_path)
                                st.image(img_obj, use_container_width=True)
                            except Exception: pass
                    else:
                        st.markdown("<div class='gis-value'>Este marcador não possui registro fotográfico atrelado.</div>", unsafe_allow_html=True)
                else:
                    st.caption("Para visualizar imagens, faça o upload de arquivos completos formato (.KMZ). Arquivos .KML não contêm a pasta interna de fotos.")
        else:
            st.markdown("<div class='gis-header'>📍 DADOS DO ELEMENTO</div>", unsafe_allow_html=True)
            st.caption("Clique diretamente em um marcador azul no mapa ou busque pelo nome/coordenada na lista à esquerda para carregar o banco de imagens e os detalhes técnicos.")
        st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# VISÃO 3: FILTROS E GOVERNANÇA (APENAS LEITURA PARA VISITANTES)
# -----------------------------------------------------------------------------
elif menu_selecionado == 'Busca e Governança':
    st.markdown("### 📝 Filtros e Governança Direta da Base")
    
    col_f1, col_f2, col_f3 = st.columns(3)
    col_f4, col_f5, col_f6 = st.columns(3)
    
    op_lev = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('LEVANTADOR', pd.Series()).dropna().unique()])
    if 'ui_lev' not in st.session_state or st.session_state.ui_lev not in op_lev: st.session_state.ui_lev = 'TODOS'
    with col_f1: st.selectbox("Filtrar por Levantador:", op_lev, key='ui_lev')

    op_reg = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('REGIONAL', pd.Series()).dropna().unique()])
    if 'ui_reg' not in st.session_state or st.session_state.ui_reg not in op_reg: st.session_state.ui_reg = 'TODOS'
    with col_f2: st.selectbox("Filtrar por Regional:", op_reg, key='ui_reg')

    op_mun = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('MUNICIPIO', pd.Series()).dropna().unique()])
    if 'ui_mun' not in st.session_state or st.session_state.ui_mun not in op_mun: st.session_state.ui_mun = 'TODOS'
    with col_f3: st.selectbox("Filtrar por Município:", op_mun, key='ui_mun')

    op_lig = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('TIPO LIGACAO', pd.Series()).dropna().astype(str).unique()])
    if 'ui_lig' not in st.session_state or st.session_state.ui_lig not in op_lig: st.session_state.ui_lig = 'TODOS'
    with col_f4: st.selectbox("Filtrar por Tipo Ligação:", op_lig, key='ui_lig')

    op_sap = ["TODOS"] + sorted([str(x) for x in df_notas_db.get('STATUS SAP', pd.Series()).dropna().unique()])
    if 'ui_sap' not in st.session_state or st.session_state.ui_sap not in op_sap: st.session_state.ui_sap = 'TODOS'
    with col_f5: st.selectbox("Filtrar por Status SAP:", op_sap, key='ui_sap')

    op_list = sorted([str(x) for x in df_notas_db.get('STATUS LIST', pd.Series()).dropna().unique() if str(x).strip() != ""])
    if 'ui_list' not in st.session_state: st.session_state.ui_list = []
    st.session_state.ui_list = [x for x in st.session_state.ui_list if x in op_list]
    with col_f6: st.multiselect("Filtrar por Status List (Vazio = TODOS):", options=op_list, key='ui_list')

    df_filtrado = df_notas_db.copy()
    if st.session_state.ui_lev != "TODOS" and 'LEVANTADOR' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'] == st.session_state.ui_lev]
    if st.session_state.ui_reg != "TODOS" and 'REGIONAL' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['REGIONAL'] == st.session_state.ui_reg]
    if st.session_state.ui_mun != "TODOS" and 'MUNICIPIO' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'] == st.session_state.ui_mun]
    if st.session_state.ui_lig != "TODOS" and 'TIPO LIGACAO' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['TIPO LIGACAO'].astype(str) == st.session_state.ui_lig]
    if st.session_state.ui_sap != "TODOS" and 'STATUS SAP' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['STATUS SAP'] == st.session_state.ui_sap]
    if len(st.session_state.ui_list) > 0 and 'STATUS LIST' in df_filtrado: df_filtrado = df_filtrado[df_filtrado['STATUS LIST'].isin(st.session_state.ui_list)]

    st.info(f"Obras localizadas sob os filtros aplicados: {len(df_filtrado)} registro(s).")
    df_filtrado_view = df_filtrado.replace({'None': '', 'nan': '', '0': '', '<NA>': '', 'NAN': ''}).fillna('')
    
    st.markdown("---")
    st.markdown("### 📊 Gestão e Edição em Lote")
    
    col_tool1, col_tool2, col_tool3 = st.columns([2, 2, 6])
    with col_tool1:
        if len(df_filtrado_view) > 0:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_filtrado_view.to_excel(writer, index=False, sheet_name='Filtrado')
            st.download_button(label="📥 Exportar para Excel", data=buffer.getvalue(), file_name="relatorio_nip_filtrado.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            
    with col_tool2:
        if st.session_state.perfil_usuario == "ADMIN":
            btn_salvar = st.button("💾 Salvar Alterações", type="primary", use_container_width=True)
        else:
            st.button("🔒 Edição Restrita", disabled=True, use_container_width=True)
            btn_salvar = False
        
    with col_tool3:
        if st.session_state.perfil_usuario == "ADMIN":
            with st.expander("⚠️ ÁREA DE PERIGO (O BACKUP SERÁ GERADO AUTOMATICAMENTE)"):
                confirmacao_global = st.checkbox("Confirmo que desejo apagar TODAS as notas.")
                if st.button("🚨 APAGAR TUDO", type="primary", disabled=not confirmacao_global):
                    if save_notas_to_db(pd.DataFrame(columns=df_notas_db.columns), backup=True, acao_auditoria="Limpeza de Banco de Dados (APAGAR TUDO)"):
                        st.success("Banco limpo. Backup preventivo gerado com sucesso!")
                        st.rerun()

    config_colunas = {
        "ID SISCO": st.column_config.TextColumn("ID SISCO", disabled=True),
        "PROTOCOLO": st.column_config.TextColumn("PROTOCOLO", disabled=True),
        "STATUS SAP": st.column_config.SelectboxColumn("STATUS SAP", options=op_sap[1:]), 
        "STATUS LIST": st.column_config.SelectboxColumn("STATUS LIST", options=op_list)
    }

    is_disabled = st.session_state.perfil_usuario != "ADMIN"
    df_editado = st.data_editor(df_filtrado_view, use_container_width=True, num_rows="dynamic", key="editor_notas", column_config=config_colunas, disabled=is_disabled)

    if btn_salvar:
        with st.spinner("Persistindo informações com swap atômico..."):
            indices_originais = df_editado.index
            df_notas_db.loc[indices_originais] = df_editado
            if save_notas_to_db(df_notas_db, backup=False, acao_auditoria="Edição em Lote via UI Governança"):
                st.success("Banco de Dados Atualizado com Sucesso!")
                st.toast("Dados salvos e painel atualizado!", icon="✅")
                st.rerun()

# -----------------------------------------------------------------------------
# VISÃO 4: CARGA DE LOTES (SOMENTE ADMIN)
# -----------------------------------------------------------------------------
elif menu_selecionado == 'Carga de Lotes':
    if st.session_state.perfil_usuario != "ADMIN":
        st.error("Acesso Negado. Módulo restrito à Coordenação.")
        st.stop()
        
    st.markdown("### 📤 Módulo de Importação de Lotes com Validação Strict")
    schema_nip = pa.DataFrameSchema({
        "PROTOCOLO": pa.Column(pa.String, coerce=True, required=True),
        "REGIONAL": pa.Column(pa.String, coerce=True, required=True),
        "MUNICIPIO": pa.Column(pa.String, coerce=True, required=True),
        "DATA CRIAÇAO SISCO": pa.Column(pa.String, coerce=True, required=False, nullable=True),
        "TIPO LIGACAO": pa.Column(pa.String, coerce=True, required=False, nullable=True),
        "STATUS SAP": pa.Column(pa.String, coerce=True, required=False, nullable=True),
        "ID SISCO": pa.Column(pa.String, coerce=True, required=False, nullable=True),
        "DATA DE LEVANTAMENTO LIST": pa.Column(pa.String, coerce=True, required=False, nullable=True) 
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
                if 'LEVANTADOR' not in df_validado.columns: df_validado['LEVANTADOR'] = SEM_LEVANTADOR
                    
                df_temp_processado = auto_assign_levantador(df_validado, df_equipes_db)
                
                if st.button("⚡ Confirmar Importação e Gravar no Banco de Dados SQLite"):
                    with st.spinner("Injetando carga de lotes no banco (Operação com Backup Automático)..."):
                        df_final = pd.concat([df_notas_db, df_temp_processado], ignore_index=True)
                        if save_notas_to_db(df_final, backup=True, acao_auditoria=f"Carga de Lote: {len(df_temp_processado)} novas demandas injetadas"):
                            st.toast("Lote processado e inserido!", icon="✅")
                            st.success(f"Sucesso! {len(df_temp_processado)} novas demandas validadas e injetadas.")
                            st.rerun()
                        
            except pa.errors.SchemaError as exc:
                st.error("🚨 Erro Crítico na Estrutura do Lote! A importação foi bloqueada.")
                st.dataframe(exc.data, use_container_width=True)
                
        except Exception as e:
            st.error(f"Erro inesperado de leitura do arquivo físico: {e}")

# -----------------------------------------------------------------------------
# VISÃO 5: LEVANTADORES (MUDANÇA DE RESIDÊNCIA E CRIAÇÃO)
# -----------------------------------------------------------------------------
elif menu_selecionado == 'Levantadores':
    if st.session_state.perfil_usuario != "ADMIN":
        st.error("Acesso Negado. Módulo restrito à Coordenação.")
        st.stop()
        
    st.markdown("### 👷 Gestão de Levantadores e Residências")
    st.caption("Defina a cidade de residência de cada levantador para otimizar a distribuição de obras e a roteirização pela função 'Gerar Demanda'.")
    
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        df_eq = pd.read_sql("SELECT * FROM equipes", conn)
        
    if 'Residencia' not in df_eq.columns:
        df_eq['Residencia'] = ""
        
    df_levs = df_eq[['Levantador', 'Equipe', 'Residencia']].drop_duplicates(subset=['Levantador']).copy()
    opcoes_mun = [""] + sorted([str(x).upper() for x in df_eq['Município'].dropna().unique() if str(x).strip() != ''])
    
    edited_levs = st.data_editor(
        df_levs,
        column_config={
            "Levantador": st.column_config.TextColumn("Levantador", disabled=True),
            "Equipe": st.column_config.TextColumn("Equipe", disabled=True),
            "Residencia": st.column_config.SelectboxColumn("Município-Base (Residência)", options=opcoes_mun)
        },
        hide_index=True,
        use_container_width=True,
        key="editor_levantadores"
    )
    
    if st.button("💾 Salvar Alterações de Residência", type="primary"):
        with st.spinner("Atualizando base de residências..."):
            map_residencia = edited_levs.set_index('Levantador')['Residencia'].to_dict()
            df_eq['Residencia'] = df_eq['Levantador'].map(map_residencia)
            
            with sqlite3.connect(DB_PATH, timeout=10) as conn:
                df_eq.to_sql('equipes', conn, if_exists='replace', index=False)
            
            get_processed_data.clear()
            st.cache_data.clear()
            st.success("Residências atualizadas com sucesso!")
            st.rerun()

    st.markdown("---")
    st.markdown("#### ➕ Cadastrar Novo Levantador")
    st.caption("Adicione novos membros à equipe de campo. Eles aparecerão no sistema para receberem novas atribuições de demandas.")
    
    with st.form("form_novo_levantador"):
        col_nl1, col_n2, col_n3 = st.columns(3)
        novo_nome = col_nl1.text_input("Nome do Levantador").strip().upper()
        nova_equipe = col_n2.text_input("Equipe (ex: EQUIPE 20)").strip().upper()
        nova_residencia = col_n3.selectbox("Município-Base (Residência)", options=opcoes_mun)
        
        submit_novo_lev = st.form_submit_button("Cadastrar Levantador", type="primary", use_container_width=True)
        
        if submit_novo_lev:
            if novo_nome and nova_equipe and nova_residencia:
                if novo_nome in df_levs['Levantador'].values:
                    st.error("🚨 Levantador já existe na base de dados!")
                else:
                    try:
                        with sqlite3.connect(DB_PATH, timeout=10) as conn:
                            conn.execute("""
                                INSERT INTO equipes (Levantador, Equipe, Residencia) 
                                VALUES (?, ?, ?)
                            """, (novo_nome, nova_equipe, nova_residencia))
                            conn.commit()
                        
                        get_processed_data.clear()
                        st.cache_data.clear()
                        st.success(f"✅ Levantador {novo_nome} cadastrado com sucesso e já está disponível!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao cadastrar levantador no Banco de Dados: {e}")
            else:
                st.warning("⚠️ Preencha todos os campos obrigatórios (Nome, Equipe e Residência).")

# -----------------------------------------------------------------------------
# VISÃO 6: GERENCIAMENTO DE ACESSOS (SOMENTE ADMIN)
# -----------------------------------------------------------------------------
elif menu_selecionado == 'Gerenciamento de Acessos':
    if st.session_state.perfil_usuario != "ADMIN":
        st.error("Acesso Negado. Módulo restrito à Coordenação.")
        st.stop()
        
    st.markdown("### 🔐 Gerenciamento de Acessos")
    
    st.markdown("#### Usuários do Sistema")
    
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        df_users = pd.read_sql("SELECT username, role FROM usuarios", conn)
    
    df_users['Remover'] = False
    
    edited_users = st.data_editor(
        df_users, 
        column_config={
            "username": st.column_config.TextColumn("Usuário", disabled=True),
            "role": st.column_config.SelectboxColumn("Perfil", options=["ADMIN", "LEITURA"], required=True),
            "Remover": st.column_config.CheckboxColumn("Apagar", default=False)
        },
        hide_index=True,
        key="user_editor",
        use_container_width=True
    )
    
    if st.button("Salvar Alterações de Acesso", type="primary"):
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            for _, row in edited_users.iterrows():
                user = row['username']
                new_role = row['role']
                to_delete = row['Remover']
                
                if to_delete:
                    if user != st.session_state.usuario_logado:
                        conn.execute("DELETE FROM usuarios WHERE username=?", (user,))
                        registrar_auditoria("Exclusão de Usuário", f"O Administrador removeu o usuário {user}.")
                    else:
                        st.warning("Você não pode apagar seu próprio usuário logado.")
                else:
                    conn.execute("UPDATE usuarios SET role=? WHERE username=?", (new_role, user))
            conn.commit()
        st.success("Configurações atualizadas com sucesso!")
        st.rerun()

    st.markdown("---")
    st.markdown("#### Criar Novo Usuário")
    with st.form("new_user_form"):
        col_n1, col_n2 = st.columns(2)
        new_user = col_n1.text_input("Novo Usuário").strip().upper()
        new_pass = col_n2.text_input("Senha", type="password")
        new_role = st.selectbox("Perfil de Acesso", ["LEITURA", "ADMIN"])
        
        if st.form_submit_button("Criar Conta", use_container_width=True):
            if new_user and new_pass:
                try:
                    with sqlite3.connect(DB_PATH, timeout=10) as conn:
                        conn.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", (new_user, new_pass, new_role))
                    st.success(f"Conta {new_user} criada!")
                    registrar_auditoria("Gerenciamento de Acesso", f"O Administrador adicionou o usuário {new_user} ({new_role}).")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Usuário já existe no banco de dados.")
            else:
                st.warning("Preencha todos os campos para continuar.")

# -----------------------------------------------------------------------------
# VISÃO 7: SIMULADOR DE ALOCAÇÃO
# -----------------------------------------------------------------------------
elif menu_selecionado == 'Simulador de Alocação':
    st.markdown("""
        <div style="background-color: #333; padding: 15px; border-radius: 5px; text-align: center; color: white; margin-bottom: 20px;">
            <h2 style="margin: 0; color: white;">Simulador de Alocação de Levantadores (MA)</h2>
        </div>
    """, unsafe_allow_html=True)

    df_eq_sim = df_equipes_db.copy()
    df_eq_sim['Regional'] = df_eq_sim['Regional'].replace(['', 'nan', 'None', '<NA>'], 'NÃO INFORMADA').astype(str).str.upper()
    df_eq_sim['Levantador'] = df_eq_sim['Levantador'].astype(str).str.upper()

    mun_total = df_eq_sim.groupby('Regional')['Município'].nunique().reset_index(name='Total Municípios')
    valid_lev_mask = ((df_eq_sim['Levantador'] != SEM_LEVANTADOR) & (df_eq_sim['Levantador'].notna()) & (~df_eq_sim['Levantador'].isin(['', '0', 'NAN', 'NONE'])))
    mun_com = df_eq_sim[valid_lev_mask].groupby('Regional')['Município'].nunique().reset_index(name='Com Levantador')
    lev_atuais = df_eq_sim[valid_lev_mask].groupby('Regional')['Levantador'].nunique().reset_index(name='Levantadores Atuais')

    df_sim = mun_total.merge(mun_com, on='Regional', how='left').fillna(0)
    df_sim = df_sim.merge(lev_atuais, on='Regional', how='left').fillna(0)
    df_sim['Sem Levantador'] = df_sim['Total Municípios'] - df_sim['Com Levantador']
    df_sim['Levantadores Atuais'] = df_sim['Levantadores Atuais'].astype(int)
    df_sim['Capacidade Media'] = np.where(df_sim['Levantadores Atuais'] > 0, df_sim['Com Levantador'] / df_sim['Levantadores Atuais'], 0)

    # Placeholders que serão alimentados pelos cálculos após a tabela
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

    st.markdown("<h4 style='background-color: #4A4F7C; color: white; padding: 5px 10px; margin-top: 20px; border-radius: 5px;'>Resumo de Impacto</h4>", unsafe_allow_html=True)
    
    total_mun_orig, total_com_orig = int(df_sim['Total Municípios'].sum()), int(df_sim['Com Levantador'].sum())
    cob_atual_orig = (total_com_orig / total_mun_orig * 100) if total_mun_orig > 0 else 0
    
    total_novos_sum, total_gap_sum, total_cob_sum = df_proj['Novos Levantadores'].sum(), df_proj['Gap Restante'].sum(), float(linha_total['Cobertura %'].iloc[0])
    
    df_impacto = pd.DataFrame({
        "Métrica": ["Novos Levantadores", "Municípios Sem Levantador", "Cobertura Estadual"],
        "Atual": [linha_total['Levantadores Atuais'].iloc[0], linha_total['Sem Levantador'].iloc[0], f"{cob_atual_orig:.1f}%"],
        "Após Contratações": [linha_total['Levantadores Atuais'].iloc[0] + total_novos_sum, total_gap_sum, f"{total_cob_sum:.1f}%"],
        "Variação": [f"+{total_novos_sum}" if total_novos_sum > 0 else "0", total_gap_sum - linha_total['Sem Levantador'].iloc[0], f"+{(total_cob_sum - cob_atual_orig):.1f}%" if (total_cob_sum - cob_atual_orig) > 0 else "0.0%"]
    })
    
    def style_variacao(v):
        if isinstance(v, str):
            if v.startswith('+') or v == '0' or v == '0.0%': return 'color: #5CB85C; font-weight: bold;'
            elif v.startswith('-'): return 'color: #D9534F; font-weight: bold;'
        return ''

    st.dataframe(df_impacto.style.map(style_variacao, subset=['Variação']), use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# RODAPÉ: USUÁRIOS ONLINE (HEARTBEAT)
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown("#### 🟢 Usuários Online Agora")

try:
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        limite_inatividade = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        ativos = pd.read_sql(
            "SELECT username, role FROM usuarios WHERE last_active >= ? ORDER BY username ASC",
            conn,
            params=(limite_inatividade,)
        )

    if not ativos.empty:
        html_pills = "".join([
            f"<span style='background-color: #d4edda; color: #155724; padding: 4px 10px; border-radius: 12px; margin-right: 8px; font-size: 13px; font-weight: bold; border: 1px solid #c3e6cb;'>👤 {row['username']} ({row['role']})</span>" 
            for _, row in ativos.iterrows()
        ])
        st.markdown(html_pills, unsafe_allow_html=True)
    else:
        st.caption("Nenhum usuário ativo detectado no momento.")
except Exception as e:
    st.caption("Status de usuários temporariamente indisponível.")
    logging.error(f"Erro ao ler heartbeat: {e}")

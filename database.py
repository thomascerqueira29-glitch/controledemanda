import streamlit as st
import pandas as pd
import numpy as np
import os
import sqlite3
import geopandas as gpd
import zipfile
import logging
import hashlib
import re
from datetime import datetime
import xml.etree.ElementTree as ET
from shapely.geometry import Point, LineString

# =============================================================================
# CONSTANTES GLOBAIS
# =============================================================================
DB_PATH = 'controle_torre_nip.db'
SEM_LEVANTADOR = 'SEM LEVANTADOR'
STATUS_PRODUTIVIDADE = ["CORRECAO DE LEVANTAMENTO", "EM LEVANTAMENTO", "PRE ANALISE"]

# =============================================================================
# CONFIGURAÇÃO DE SUPORTE GEOESPACIAL (KML)
# =============================================================================
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
# FUNÇÕES DE SEGURANÇA E INICIALIZAÇÃO DE BANCO DE DADOS
# =============================================================================
def hash_senha(senha):
    """Gera hash criptográfico para proteger as senhas no Banco de Dados."""
    return hashlib.sha256(str(senha).encode('utf-8')).hexdigest()

def init_databases():
    """Cria tabelas base, injeção do ADMIN e cria índices de alta performance."""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, role TEXT, last_active TEXT)''')
        try:
            conn.execute("ALTER TABLE usuarios ADD COLUMN last_active TEXT")
        except sqlite3.OperationalError:
            pass
            
        conn.execute('''CREATE TABLE IF NOT EXISTS auditoria_log (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, data_hora TEXT, acao TEXT, detalhes TEXT)''')
        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('THOMAS', ?, 'ADMIN')", (hash_senha('admin123'),))
        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('VISITANTE', ?, 'LEITURA')", (hash_senha('123'),))
        
        os.makedirs("kmz_history", exist_ok=True)
        os.makedirs("kmz_extracted", exist_ok=True)
        conn.execute('''CREATE TABLE IF NOT EXISTS historico_kmz (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, data_upload TEXT, usuario TEXT, filepath TEXT)''')
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lev ON notas (LEVANTADOR);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reg ON notas (REGIONAL);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mun ON notas (MUNICIPIO);")
        except Exception: pass
        conn.commit()

def sync_residencias_banco():
    """Garante estruturação de colunas de residência na equipe"""
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(equipes)")
                if 'Residencia' not in [col[1] for col in cursor.fetchall()]:
                    conn.execute("ALTER TABLE equipes ADD COLUMN Residencia TEXT")
                conn.commit()
    except Exception as e:
        logging.error(f"Erro de sincronização de banco: {e}")

def init_business_db():
    """Gera estrutura em branco da tabela de notas caso não exista e tenta importar Excel antigo"""
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
    except Exception: pass

def registrar_auditoria(acao, detalhes):
    try:
        usuario = st.session_state.get('usuario_logado', 'SISTEMA')
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.execute("INSERT INTO auditoria_log (usuario, data_hora, acao, detalhes) VALUES (?, ?, ?, ?)",
                         (usuario, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), acao, detalhes))
            conn.commit()
    except Exception: pass

# =============================================================================
# ENGINE 2: PROCESSAMENTO DE DADOS (CACHE E VETORIZAÇÃO)
# =============================================================================
@st.cache_data(show_spinner=False)
def load_core_data():
    """Motor Central de Leitura. Blindado contra qualquer ausência de coluna."""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        df_notas = pd.read_sql("SELECT * FROM notas", conn)
        df_equipes = pd.read_sql("SELECT * FROM equipes", conn)
        
    # --- BLINDAGEM DE COLUNAS ---
    colunas_eq = ['Município', 'Levantador', 'Latitude', 'Longitude', 'Equipe', 'Residencia', 'Regional']
    for col in colunas_eq:
        if col not in df_equipes.columns: df_equipes[col] = ""
        
    colunas_nt = ['PROTOCOLO', 'MUNICIPIO', 'LEVANTADOR', 'STATUS LIST', 'TIPO LIGACAO', 'REGIONAL', 'STATUS SAP', 'DATA CRIAÇAO SISCO', 'DATA DE VENCIMENTO', 'NOME DO SOLICITANTE', 'LATITUDE', 'LONGITUDE']
    for col in colunas_nt:
        if col not in df_notas.columns: df_notas[col] = ""
        
    # Limpeza Universal
    df_eq_clean = df_equipes.dropna(subset=['Município']).drop_duplicates(subset=['Município'])
    map_levs = df_eq_clean.set_index('Município')['Levantador'].to_dict()
    
    df_notas['MUNICIPIO'] = df_notas['MUNICIPIO'].astype(str).str.upper().str.strip()
    df_notas['LEVANTADOR'] = df_notas['LEVANTADOR'].astype(str).str.upper().str.strip()
    df_notas['STATUS LIST'] = df_notas['STATUS LIST'].astype(str).str.upper().str.strip()
        
    mask_vazio = df_notas['LEVANTADOR'].isin([SEM_LEVANTADOR, '', 'NAN', 'NONE', '0']) | df_notas['LEVANTADOR'].isna()
    df_notas.loc[mask_vazio, 'LEVANTADOR'] = df_notas.loc[mask_vazio, 'MUNICIPIO'].map(map_levs).fillna(SEM_LEVANTADOR)
    
    mapa_lat = pd.to_numeric(df_eq_clean.set_index('Município')['Latitude'].astype(str).str.replace(',', '.'), errors='coerce').to_dict()
    mapa_lon = pd.to_numeric(df_eq_clean.set_index('Município')['Longitude'].astype(str).str.replace(',', '.'), errors='coerce').to_dict()
    df_notas['Lat_Mapa'] = df_notas['MUNICIPIO'].map(mapa_lat)
    df_notas['Lon_Mapa'] = df_notas['MUNICIPIO'].map(mapa_lon)

    mun_por_lev = df_equipes.groupby('Levantador')['Município'].nunique().reset_index().rename(columns={'Município': 'Qtd_Municipios'})
    contagem_prod = df_notas[df_notas['STATUS LIST'].isin(STATUS_PRODUTIVIDADE)]['LEVANTADOR'].value_counts().reset_index()
    contagem_prod.columns = ['Levantador', 'Total_Obras_Real']

    todos_lev = [l for l in df_equipes['Levantador'].dropna().unique() if str(l).strip() not in [SEM_LEVANTADOR, 'NAN', '', 'None']]
    resumo_lev = pd.merge(pd.DataFrame({'Levantador': todos_lev}), contagem_prod, on='Levantador', how='left').fillna(0)
    resumo_lev['Total_Obras_Real'] = resumo_lev['Total_Obras_Real'].astype(int)
    resumo_lev['Equipe'] = resumo_lev['Levantador'].map(df_equipes.dropna(subset=['Levantador', 'Equipe']).drop_duplicates(subset=['Levantador']).set_index('Levantador')['Equipe'].to_dict()).fillna('SEM EQUIPE')
    
    lev_criticos = resumo_lev[resumo_lev['Total_Obras_Real'] < 45]['Levantador'].tolist()
    
    return df_notas, df_equipes, resumo_lev, lev_criticos, todos_lev, mapa_lat, mapa_lon, mun_por_lev

def save_notas_to_db(df_notas_atualizado, backup=False, acao_auditoria="Operação no Banco de Dados"):
    try:
        df_notas_limpo = df_notas_atualizado.copy().fillna("").astype(str).replace({"nan": "", "NaT": "", "None": "", "<NA>": ""})
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            df_notas_limpo.to_sql('notas_temp', conn, if_exists='replace', index=False)
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DROP TABLE IF EXISTS notas;")
            conn.execute("ALTER TABLE notas_temp RENAME TO notas;")
            conn.commit()
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_lev ON notas (LEVANTADOR);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_reg ON notas (REGIONAL);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mun ON notas (MUNICIPIO);")
            except: pass
            
        registrar_auditoria(acao_auditoria, f"Tabela NOTAS atualizada. Volume final: {len(df_notas_limpo)} registros.")
        load_core_data.clear()
        return True
    except sqlite3.Error as e:
        st.error(f"Falha Crítica no Banco de Dados: {e}")
        return False

def vectorized_haversine(lat1, lon1, lat2_series, lon2_series):
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
            
            all_geoms = pd.concat([gdf_points['geometry'] if not gdf_points.empty else pd.Series(dtype=object), gdf_lines['geometry'] if not gdf_lines.empty else pd.Series(dtype=object)])
            bounds = gpd.GeoSeries(all_geoms).total_bounds if not all_geoms.empty else None
            
        return gdf_lines, gdf_points, bounds
    except Exception: return gdf_lines, gdf_points, None

@st.cache_data(show_spinner=False)
def calcular_sla_vetorizado(df_notas_calc):
    df_sla = df_notas_calc.copy()
    tipo = df_sla.get('TIPO LIGACAO', pd.Series([''] * len(df_sla))).astype(str).str.strip().str.upper()
    g1, g2 = ['ASC', 'UNI', 'UNO'], ['SEG', 'SID', 'EUR', 'MGD', 'MTP', 'UNR', 'UNP']
    g_crono = ['LPT', 'REG', 'PMC', 'ERD', 'SEQ', 'BCP', 'BRE', 'BRT', 'DIG', 'DIS', 'DLD', 'INT', 'MEL', 'OCP', 'TRI', 'EQP', 'FIM', 'MBT', 'MMT']
    g_niv = ['NIV']
    hoje = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None).normalize()
    
    def blindar_datas(serie):
        s = serie.astype(str).str.strip().replace({'nan': '', 'None': '', 'NaT': '', '<NA>': '', '0': '', '': None})
        s = s.str.replace('.', '/', regex=False).str.replace('-', '/', regex=False).str.split(' ').str[0]
        return pd.to_datetime(s, errors='coerce', dayfirst=True).dt.tz_localize(None)

    df_sla['DATA DE VENCIMENTO_DT'] = blindar_datas(df_sla.get('DATA DE VENCIMENTO', pd.Series()))
    df_sla['DATA CRIAÇAO SISCO_DT'] = blindar_datas(df_sla.get('DATA CRIAÇAO SISCO', pd.Series()))
    
    dias_para_vencer = (df_sla['DATA DE VENCIMENTO_DT'] - hoje).dt.days
    idade_dias = (hoje - df_sla['DATA CRIAÇAO SISCO_DT']).dt.days

    cond_crono = tipo.isin(g_crono) & df_sla['DATA DE VENCIMENTO_DT'].notna()
    cond_crono_v = cond_crono & (dias_para_vencer < 0)
    cond_crono_p = cond_crono & (dias_para_vencer >= 0) & (dias_para_vencer <= 3)
    cond_crono_np = cond_crono & (dias_para_vencer > 3)
    
    cond_base_dt = df_sla['DATA CRIAÇAO SISCO_DT'].notna()
    
    df_sla['Status_SLA'] = np.select(
        [
            cond_crono_v | (tipo.isin(g1) & cond_base_dt & (idade_dias > 15)) | (tipo.isin(g2) & cond_base_dt & (idade_dias > 24)) | (tipo.isin(g_niv) & cond_base_dt & (idade_dias > 8)) | (~tipo.isin(g_crono + g1 + g2 + g_niv) & cond_base_dt & (idade_dias > 20)),
            cond_crono_p | (tipo.isin(g1) & cond_base_dt & (idade_dias > 10) & (idade_dias <= 15)) | (tipo.isin(g2) & cond_base_dt & (idade_dias > 16) & (idade_dias <= 24)) | (tipo.isin(g_niv) & cond_base_dt & (idade_dias > 5) & (idade_dias <= 8)) | (~tipo.isin(g_crono + g1 + g2 + g_niv) & cond_base_dt & (idade_dias > 15) & (idade_dias <= 20)),
            cond_crono_np | (tipo.isin(g1) & cond_base_dt & (idade_dias <= 10)) | (tipo.isin(g2) & cond_base_dt & (idade_dias <= 16)) | (tipo.isin(g_niv) & cond_base_dt & (idade_dias <= 5)) | (~tipo.isin(g_crono + g1 + g2 + g_niv) & cond_base_dt & (idade_dias <= 15))
        ],
        ['Vencida', 'Vencimento Próximo', 'No Prazo'], default='Sem Data/Inválida'
    )
    return df_sla

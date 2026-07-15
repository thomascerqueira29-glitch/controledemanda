import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster, FastMarkerCluster
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
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# CONSTANTES GLOBAIS E CONFIGURAÇÕES INICIAIS
# -----------------------------------------------------------------------------
DB_PATH = 'controle_torre_nip.db'
SEM_LEVANTADOR = 'SEM LEVANTADOR'
STATUS_PRODUTIVIDADE = ["CORRECAO DE LEVANTAMENTO", "EM LEVANTAMENTO", "PRE ANALISE"]

st.set_page_config(page_title="Portal Corporativo NIP", layout="wide", page_icon="🏗️")

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
# 1. MOTOR DE IDENTIDADE E COLUNAS CRÍTICAS DE NEGÓCIOS
# -----------------------------------------------------------------------------
def init_iam():
    """Garante que as tabelas de segurança existam, independentemente do estado do servidor Cloud"""
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

init_iam()

def ensure_residencia_column():
    """Garante que a coluna Residencia exista na tabela equipes para a lógica de 'Gerar Demanda'"""
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(equipes)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'Residencia' not in columns:
                    conn.execute("ALTER TABLE equipes ADD COLUMN Residencia TEXT")
                    
                    # Tenta extrair da planilha base levantador se ela existir no ambiente
                    if os.path.exists('base levantador.xlsx'):
                        df_base = pd.read_excel('base levantador.xlsx')
                        if 'Residencia' in df_base.columns:
                            map_res = df_base.set_index('Levantador')['Residencia'].dropna().to_dict()
                            for lev, res in map_res.items():
                                conn.execute("UPDATE equipes SET Residencia = ? WHERE Levantador = ?", (str(res).upper().strip(), lev))
                    conn.commit()
    except Exception as e:
        logging.error(f"Erro ao adicionar Residencia: {e}")

# -----------------------------------------------------------------------------
# 2. MOTOR DE NEGÓCIOS E CARGA DO LEGADO (NOTAS E EQUIPES)
# -----------------------------------------------------------------------------
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
            
            # Validação Tabela de Notas
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
                    
            # Validação Tabela de Equipes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
            if not cursor.fetchone():
                # Usa a base_levantador caso não encontre equipes genérica
                if os.path.exists('base levantador.xlsx'):
                    pd.read_excel('base levantador.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
                elif os.path.exists('EQUIPES.xlsx'):
                    pd.read_excel('EQUIPES.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
                else:
                    pd.DataFrame(columns=['Município', 'Estado', 'Levantador', 'Regional', 'Longitude', 'Latitude', 'Equipe', 'Residencia']).to_sql('equipes', conn, if_exists='replace', index=False)
                    
        st.session_state.db_initialized = True
    except Exception as e:
        logging.error(f"Erro ao inicializar tabelas de negócios: {e}")

if 'db_initialized' not in st.session_state or not st.session_state.db_initialized: 
    init_business_db()
    ensure_residencia_column()

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
    st.markdown("""
        <style>
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

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

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES DE ESTADO GERAIS E NAVEGAÇÃO
# -----------------------------------------------------------------------------
if 'menu_idx' not in st.session_state:
    st.session_state.menu_idx = 0

def filtrar_levantador_governanca(nome_lev):
    st.session_state.ui_lev = nome_lev
    st.session_state.ui_reg = 'TODOS'
    st.session_state.ui_mun = 'TODOS'
    st.session_state.ui_lig = 'TODOS'
    st.session_state.ui_sap = 'TODOS'
    st.session_state.ui_list = STATUS_PRODUTIVIDADE.copy() 
    st.session_state.menu_idx = 1
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
# TRILHA DE AUDITORIA E ENGENHARIA DE DADOS
# -----------------------------------------------------------------------------
def registrar_auditoria(acao, detalhes):
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            usuario = st.session_state.usuario_logado
            conn.execute("INSERT INTO auditoria_log (usuario, data_hora, acao, detalhes) VALUES (?, ?, ?, ?)",
                         (usuario, agora, acao, detalhes))
            conn.commit()
    except Exception as e:
        logging.error(f"Erro ao registrar auditoria: {e}")

def realizar_backup_db():
    os.makedirs("backups", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bkp_path = f"backups/controle_torre_nip_bkp_{timestamp}.db"
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, bkp_path)
        registrar_auditoria("BACKUP PREVENTIVO", f"Backup automático gerado em {bkp_path}")
    return bkp_path

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
    if backup: realizar_backup_db()
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
        calcular_sla_vetorizado.clear()
        return True
    except sqlite3.Error as e:
        st.error(f"Falha Crítica no Banco de Dados: {e}")
        return False

df_notas_db, df_equipes_db = get_processed_data()

# -----------------------------------------------------------------------------
# MOTORES DE ALTA PERFORMANCE (CACHE E VETORIZAÇÃO)
# -----------------------------------------------------------------------------
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
def processar_camada_espacial(arquivo_espacial):
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
            gdf_lines = gdf_final[gdf_final.geometry.type.isin(['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon'])]
            gdf_points = gdf_final[gdf_final.geometry.type == 'Point']
            bounds = gdf_final.total_bounds
    except Exception: pass
    return gdf_lines, gdf_points, bounds

@st.cache_data(show_spinner=False)
def calcular_sla_vetorizado(df_notas_calc):
    df_sla = df_notas_calc.copy()
    tipo = df_sla['TIPO LIGACAO'].astype(str).str.strip().str.upper()
    g1, g2 = ['ASC', 'UNI', 'UNO'], ['SEG', 'SID', 'EUR', 'MGD', 'MTP', 'UNR', 'UNP']
    g_crono = ['LPT', 'REG', 'PMC', 'ERD', 'SEQ', 'BCP', 'BRE', 'BRT', 'DIG', 'DIS', 'DLD', 'INT', 'MEL', 'OCP', 'TRI', 'EQP', 'FIM', 'MBT', 'MMT']
    g_niv = ['NIV']
    hoje = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None).normalize()
    
    def blindar_datas(serie):
        s = serie.astype(str).str.strip().replace({'nan': '', 'None': '', 'NaT': '', '<NA>': '', '0': '', '': None})
        s = s.str.replace('.', '/', regex=False).str.replace('-', '/', regex=False).str.split(' ').str[0]
        return pd.to_datetime(s, errors='coerce', dayfirst=True).dt.tz_localize(None)

    df_sla['DATA DE VENCIMENTO_DT'] = blindar_datas(df_sla['DATA DE VENCIMENTO'])
    df_sla['DATA CRIAÇAO SISCO_DT'] = blindar_datas(df_sla['DATA CRIAÇAO SISCO'])
    
    dias_para_vencer = (df_sla['DATA DE VENCIMENTO_DT'] - hoje).dt.days
    idade_dias = (hoje - df_sla['DATA CRIAÇAO SISCO_DT']).dt.days

    cond_crono = tipo.isin(g_crono) & df_sla['DATA DE VENCIMENTO_DT'].notna()
    cond_crono_v = cond_crono & (dias_para_vencer < 0)
    cond_crono_p = cond_crono & (dias_para_vencer >= 0) & (dias_para_vencer <= 3)
    cond_crono_np = cond_crono & (dias_para_vencer > 3)
    
    cond_base_dt = df_sla['DATA CRIAÇAO SISCO_DT'].notna()
    cond_g1 = tipo.isin(g1) & cond_base_dt
    cond_g1_np = cond_g1 & (idade_dias <= 10)
    cond_g1_p  = cond_g1 & (idade_dias > 10) & (idade_dias <= 15)
    cond_g1_v  = cond_g1 & (idade_dias > 15)
    
    cond_g2 = tipo.isin(g2) & cond_base_dt
    cond_g2_np = cond_g2 & (idade_dias <= 16)
    cond_g2_p  = cond_g2 & (idade_dias > 16) & (idade_dias <= 24)
    cond_g2_v  = cond_g2 & (idade_dias > 24)
    
    cond_niv = tipo.isin(g_niv) & cond_base_dt
    cond_niv_np = cond_niv & (idade_dias <= 5)
    cond_niv_p  = cond_niv & (idade_dias > 5) & (idade_dias <= 8)
    cond_niv_v  = cond_niv & (idade_dias > 8)
    
    cond_default = ~tipo.isin(g_crono + g1 + g2 + g_niv) & cond_base_dt
    cond_def_np = cond_default & (idade_dias <= 15)
    cond_def_p  = cond_default & (idade_dias > 15) & (idade_dias <= 20)
    cond_def_v  = cond_default & (idade_dias > 20)

    df_sla['Status_SLA'] = np.select(
        [
            cond_crono_v | cond_g1_v | cond_g2_v | cond_niv_v | cond_def_v,
            cond_crono_p | cond_g1_p | cond_g2_p | cond_niv_p | cond_def_p,
            cond_crono_np | cond_g1_np | cond_g2_np | cond_niv_np | cond_def_np
        ],
        ['Vencida', 'Vencimento Próximo', 'No Prazo'], default='Sem Data/Inválida'
    )
    df_sla['REGIONAL'] = df_sla['REGIONAL'].replace(['', 'nan', 'None', '<NA>'], 'NÃO INFORMADA')
    return df_sla

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
# INTERFACE DE NAVEGAÇÃO LATERAL COM IAM
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
    
    opcoes_menu = ['Painel Executivo', 'Busca e Governança', 'Simulador de Alocação']
    icones_menu = ['pie-chart-fill', 'sliders', 'calculator-fill']
    
    if st.session_state.perfil_usuario == "ADMIN":
        opcoes_menu.insert(2, 'Carga de Lotes')
        icones_menu.insert(2, 'cloud-upload-fill')
        opcoes_menu.insert(3, 'Levantadores')
        icones_menu.insert(3, 'person-vcard-fill')
        opcoes_menu.insert(4, 'Gerenciamento de Acessos')
        icones_menu.insert(4, 'shield-lock-fill')
        
    menu_items = [sac.MenuItem(opcoes_menu[i], icon=icones_menu[i]) for i in range(len(opcoes_menu))]
    
    if st.session_state.menu_idx >= len(opcoes_menu):
        st.session_state.menu_idx = 0
        
    menu_selecionado = sac.menu(menu_items, index=st.session_state.menu_idx, format_func='title', size='md')
    
    if menu_selecionado in opcoes_menu:
        st.session_state.menu_idx = opcoes_menu.index(menu_selecionado)

# -----------------------------------------------------------------------------
# VISÃO 1: PAINEL EXECUTIVO E MAPAS
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
                
                # Zera a etapa de confirmação se mudarmos o levantador selecionado
                if st.session_state.get('last_lev_selecionado') != lev_selecionado:
                    st.session_state.assign_step = 0
                    st.session_state.show_demanda = False
                    st.session_state.last_lev_selecionado = lev_selecionado
                
                obras_do_lev = int(resumo_levantadores[resumo_levantadores['Levantador'] == lev_selecionado]['Total_Obras_Real'].iloc[0])
                saldo_necessario = max(0, 45 - obras_do_lev)
                
                st.info(f"Obras Vinculadas Atualmente: **{obras_do_lev}**")
                
                if st.session_state.perfil_usuario == "ADMIN":
                    if obras_do_lev < 45:
                        # Etapa 0: Exibe o botão principal de Atribuir
                        if st.session_state.get('assign_step', 0) == 0:
                            if st.button(f"⚡ Atribuir +{saldo_necessario} Obras Próximas", use_container_width=True, type="primary"):
                                st.session_state.assign_step = 1
                                st.rerun()
                                
                        # Etapa 1: Aguardando a Confirmação de Segurança
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
                                
                        # Etapa 2: Exibe o botão de Gerar Demanda (Roteirização/Cor) após a confirmação
                        elif st.session_state.assign_step == 2:
                            st.success("✅ Atribuição confirmada.")
                            if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"):
                                st.session_state.show_demanda = True
                                st.session_state.assign_step = 0
                                st.rerun()
                    else: 
                        st.success("✅ Meta Atingida.")
                        # Se já tem as metas, o botão de gerar demanda pode ser acessado livremente
                        if st.button("📋 Gerar Demanda", use_container_width=True, type="primary"):
                            st.session_state.show_demanda = True
                            
                else:
                    st.warning("🔒 Acesso restrito. Módulo de atribuição exclusivo para Coordenação.")
                    
                st.button("🔍 Ver Base de Obras", on_click=filtrar_levantador_governanca, args=(lev_selecionado,), use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
                
        # --- NOVO PAINEL: GERAÇÃO DE DEMANDA POR ROTEIRIZAÇÃO (CORES) ---
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
                
                df_demanda_view = df_demanda[['PROTOCOLO', 'MUNICIPIO', 'ENDEREÇO', 'STATUS LIST', 'TIPO LIGACAO', 'Distancia_KM']].copy()
                df_demanda_view = df_demanda_view.sort_values('Distancia_KM')
                df_demanda_view['Distancia_KM'] = df_demanda_view['Distancia_KM'].round(1)
                
                # Regras de Coloração Baseada na Planilha
                def color_rules(row):
                    dist = row['Distancia_KM']
                    if pd.isna(dist):
                        color = ''
                    elif dist <= 50:
                        color = 'background-color: #d4edda; color: #155724;' # Verde (Até 50km)
                    elif dist <= 100:
                        color = 'background-color: #fff3cd; color: #856404;' # Amarelo (Até 100km)
                    else:
                        color = 'background-color: #f8d7da; color: #721C24;' # Vermelho (150 a 250km+)
                    return [color] * len(row)
                    
                st.dataframe(df_demanda_view.style.apply(color_rules, axis=1), use_container_width=True, hide_index=True)
                
                if st.button("Fechar Aba de Demanda"):
                    st.session_state.show_demanda = False
                    st.rerun()
            else:
                st.warning("Nenhuma obra na fila de produtividade para este levantador. Utilize a Busca Governança para conferir o status.")
                if st.button("Fechar"):
                    st.session_state.show_demanda = False
                    st.rerun()

        st.markdown("---")
        st.markdown("#### 🏆 Obras em Levantamento Concluído")
        
        col_c1, col_c2 = st.columns([1, 3])
        with col_c1:
            data_filtro_conclusao = st.date_input("Filtrar por Data de Conclusão", value=datetime.today())
            
        with col_c2:
            st.caption("Filtra e contabiliza as obras baseando-se EXCLUSIVAMENTE no preenchimento da coluna **DATA DE LEVANTAMENTO LIST** correspondente à data selecionada.")
            
        df_concluidas = df_notas_calc.copy()
        
        def safe_date_parse(serie):
            s = serie.astype(str).str.strip().replace({'nan': '', 'None': '', 'NaT': '', '<NA>': '', '0': '', '': None})
            s = s.str.replace('.', '/', regex=False).str.replace('-', '/', regex=False).str.split(' ').str[0]
            return pd.to_datetime(s, errors='coerce', dayfirst=True).dt.date
            
        if 'DATA DE LEVANTAMENTO LIST' in df_concluidas.columns:
            df_concluidas['DATA_REF'] = safe_date_parse(df_concluidas['DATA DE LEVANTAMENTO LIST'])
        else:
            df_concluidas['DATA_REF'] = pd.NaT
            
        df_concluidas_dia = df_concluidas[df_concluidas['DATA_REF'] == data_filtro_conclusao]
        
        contagem_concluidas = df_concluidas_dia['LEVANTADOR'].value_counts().reset_index()
        contagem_concluidas.columns = ['Levantador', 'Obras_Concluidas']
        
        resumo_concluidas = pd.DataFrame({'Levantador': todos_levantadores})
        resumo_concluidas = pd.merge(resumo_concluidas, contagem_concluidas, on='Levantador', how='left').fillna(0)
        resumo_concluidas['Obras_Concluidas'] = resumo_concluidas['Obras_Concluidas'].astype(int)
        
        mapa_lev_equipe = df_equipes_db.dropna(subset=['Levantador', 'Equipe']).drop_duplicates(subset=['Levantador']).set_index('Levantador')['Equipe'].to_dict()
        resumo_concluidas['Equipe'] = resumo_concluidas['Levantador'].map(mapa_lev_equipe).fillna('SEM EQUIPE')
        resumo_concluidas = resumo_concluidas.sort_values('Obras_Concluidas', ascending=False)
        
        st.dataframe(
            resumo_concluidas[['Levantador', 'Equipe', 'Obras_Concluidas']], 
            use_container_width=True, hide_index=True, height=320,
            column_config={
                "Levantador": st.column_config.TextColumn("Levantador / Técnico"),
                "Equipe": st.column_config.TextColumn("Equipe SAP"),
                "Obras_Concluidas": st.column_config.ProgressColumn("Concluídas no Dia", format="%d", min_value=0, max_value=int(resumo_concluidas['Obras_Concluidas'].max() if not resumo_concluidas.empty and resumo_concluidas['Obras_Concluidas'].max() > 0 else 10))
            }
        )

        st.markdown("---")
        st.markdown("### 📊 Estatísticas e Distribuição da Carga Geral")
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            if not municipios_por_levantador.empty and municipios_por_levantador['Qtd_Municipios'].sum() > 0:
                df_mun_sorted = municipios_por_levantador.sort_values('Qtd_Municipios', ascending=False).head(15).sort_values('Qtd_Municipios', ascending=True)
                fig_bar_mun = px.bar(df_mun_sorted, x='Qtd_Municipios', y='Levantador', orientation='h', title="Top 15 - Municípios por Levantador", color_discrete_sequence=['#4A4F7C'])
                fig_bar_mun.update_layout(xaxis_title="Qtd. Municípios", yaxis_title="")
                st.plotly_chart(fig_bar_mun, use_container_width=True)
            
        with col_g2:
            df_sem_levantador = df_notas_calc[df_notas_calc['LEVANTADOR'] == SEM_LEVANTADOR]
            df_sem_lev_reg = df_sem_levantador['REGIONAL'].value_counts().reset_index() if 'REGIONAL' in df_sem_levantador else pd.DataFrame()
            if not df_sem_lev_reg.empty:
                df_sem_lev_reg.columns = ['Regional', 'Quantidade_Sem_Atribuicao']
                df_sem_lev_reg = df_sem_lev_reg.sort_values('Quantidade_Sem_Atribuicao', ascending=False).head(15).sort_values('Quantidade_Sem_Atribuicao', ascending=True)
                fig_bar_sem_lev = px.bar(df_sem_lev_reg, x='Quantidade_Sem_Atribuicao', y='Regional', orientation='h', title="Top 15 - Obras Sem Levantador Atribuído por Regional", color_discrete_sequence=['#D9534F'])
                fig_bar_sem_lev.update_layout(xaxis_title="Volume Pendente", yaxis_title="")
                st.plotly_chart(fig_bar_sem_lev, use_container_width=True)

        df_sla_chart = calcular_sla_vetorizado(df_notas_calc)
        df_sla_chart = df_sla_chart[df_sla_chart['Status_SLA'].isin(['No Prazo', 'Vencimento Próximo', 'Vencida'])]
        
        if not df_sla_chart.empty:
            st.markdown("---")
            st.markdown("### ⏳ Monitoramento de SLA por Regional")
            df_group = df_sla_chart.groupby(['REGIONAL', 'Status_SLA']).size().reset_index(name='Quantidade')
            if not df_group.empty and df_group['Quantidade'].sum() > 0:
                ordem_cat = ['No Prazo', 'Vencimento Próximo', 'Vencida']
                df_group['Status_SLA'] = pd.Categorical(df_group['Status_SLA'], categories=ordem_cat, ordered=True)
                df_group = df_group.sort_values(['REGIONAL', 'Status_SLA'])
                
                fig_sla = px.bar(df_group, x='REGIONAL', y='Quantidade', color='Status_SLA',
                                 title="Status Operacional de SLA por Regional", text='Quantidade', barmode='group',
                                 color_discrete_map={'No Prazo': '#5CB85C', 'Vencimento Próximo': '#F0AD4E', 'Vencida': '#D9534F'})
                fig_sla.update_traces(textposition='auto', textfont_size=14)
                st.plotly_chart(fig_sla, use_container_width=True)

        st.markdown("---")
        
        st.markdown("### 🗺️ Roteirização e Camadas Espaciais Georreferenciadas")
        
        op_map_lev = ["TODOS"] + sorted([str(x) for x in df_notas_calc.get('LEVANTADOR', pd.Series()).dropna().unique()])
        op_map_reg = ["TODOS"] + sorted([str(x) for x in df_notas_calc.get('REGIONAL', pd.Series()).dropna().unique()])
        op_map_mun = ["TODOS"] + sorted([str(x) for x in df_notas_calc.get('MUNICIPIO', pd.Series()).dropna().unique()])
        op_map_sap = ["TODOS"] + sorted([str(x) for x in df_notas_calc.get('STATUS SAP', pd.Series()).dropna().unique()])
        op_map_list = sorted([str(x) for x in df_notas_calc.get('STATUS LIST', pd.Series()).dropna().unique() if str(x).strip() != ""])
        
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1: filtro_map_lev = st.selectbox("Filtro Mapa Levantador:", op_map_lev, key='map_lev')
        with col_f2: filtro_map_reg = st.selectbox("Filtro Mapa Regional:", op_map_reg, key='map_reg')
        with col_f3: filtro_map_mun = st.selectbox("Filtro Mapa Município:", op_map_mun, key='map_mun')
        
        col_f4, col_f5, col_f6 = st.columns(3)
        with col_f4: filtro_map_sap = st.selectbox("Filtro Mapa Status SAP:", op_map_sap, key='map_sap')
        with col_f5: filtro_map_list = st.multiselect("Filtro Mapa Status List (Vazio = Mostrar Todos):", options=op_map_list, key='map_list')
        
        df_notas_mapa_view = df_notas_calc.copy()
        if filtro_map_lev != "TODOS" and 'LEVANTADOR' in df_notas_mapa_view: df_notas_mapa_view = df_notas_mapa_view[df_notas_mapa_view['LEVANTADOR'] == filtro_map_lev]
        if filtro_map_reg != "TODOS" and 'REGIONAL' in df_notas_mapa_view: df_notas_mapa_view = df_notas_mapa_view[df_notas_mapa_view['REGIONAL'] == filtro_map_reg]
        if filtro_map_mun != "TODOS" and 'MUNICIPIO' in df_notas_mapa_view: df_notas_mapa_view = df_notas_mapa_view[df_notas_mapa_view['MUNICIPIO'] == filtro_map_mun]
        if filtro_map_sap != "TODOS" and 'STATUS SAP' in df_notas_mapa_view: df_notas_mapa_view = df_notas_mapa_view[df_notas_mapa_view['STATUS SAP'] == filtro_map_sap]
        if len(filtro_map_list) > 0 and 'STATUS LIST' in df_notas_mapa_view: df_notas_mapa_view = df_notas_mapa_view[df_notas_mapa_view['STATUS LIST'].isin(filtro_map_list)]

        col_m1, col_m2 = st.columns([8, 2])
        col_m1.info(f"📍 **Obras localizadas no mapa:** {len(df_notas_mapa_view)}")
        
        camada_upload = col_m2.file_uploader("Sobrepor Camada (KML/KMZ)", type=['geojson', 'kml', 'kmz'], label_visibility="collapsed")
            
        caminho_camada_temp = None
        if camada_upload is not None:
            extensao = camada_upload.name.split('.')[-1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{extensao}') as tmp:
                tmp.write(camada_upload.getvalue())
                caminho_camada_temp = tmp.name
            if extensao == 'kmz':
                try:
                    with zipfile.ZipFile(caminho_camada_temp, 'r') as kmz:
                        kml_files = [name for name in kmz.namelist() if name.lower().endswith('.kml')]
                        if kml_files: 
                            kml_filename = os.path.basename(kml_files[0])
                            safe_extract_path = os.path.join(tempfile.gettempdir(), kml_filename)
                            with open(safe_extract_path, 'wb') as out_file:
                                out_file.write(kmz.read(kml_files[0]))
                            caminho_camada_temp = safe_extract_path
                except Exception: pass
        
        df_eq_mapa_view = df_equipes_db.copy()
        if filtro_map_lev != "TODOS" and 'Levantador' in df_eq_mapa_view: df_eq_mapa_view = df_eq_mapa_view[df_eq_mapa_view['Levantador'].astype(str).str.upper() == filtro_map_lev.upper()]
        if filtro_map_reg != "TODOS" and 'Regional' in df_eq_mapa_view: df_eq_mapa_view = df_eq_mapa_view[df_eq_mapa_view['Regional'].astype(str).str.upper() == filtro_map_reg.upper()]
        if filtro_map_mun != "TODOS" and 'Município' in df_eq_mapa_view: df_eq_mapa_view = df_eq_mapa_view[df_eq_mapa_view['Município'].astype(str).str.upper() == filtro_map_mun.upper()]

        def construir_mapa(df_eq, df_nt, criticos_tuple, arquivo_espacial=None):
            mapa = folium.Map(location=[-5.2, -45.0], zoom_start=7)
            folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Visão de Satélite', overlay=False, control=True).add_to(mapa)
            folium.TileLayer('OpenStreetMap', name='Mapa Padrão', overlay=False, control=True).add_to(mapa)
            
            if arquivo_espacial:
                gdf_lines, gdf_points, bounds = processar_camada_espacial(arquivo_espacial)
                if not gdf_lines.empty:
                    folium.GeoJson(gdf_lines, name="Rede Elétrica (Linhas)", style_function=lambda feature: {'color': '#1A4F7C', 'weight': 2.5, 'fillOpacity': 0.2}).add_to(mapa)
                if not gdf_points.empty:
                    for col in ['Name', 'Description', 'Layer_Name']:
                        if col not in gdf_points.columns: gdf_points[col] = ''
                    def get_point_style(feature):
                        props = feature.get('properties', {})
                        busca = (str(props.get('Name', '')) + " " + str(props.get('Description', '')) + " " + str(props.get('Layer_Name', ''))).lower()
                        if 'poste' in busca: cor, raio = '#808080', 2.5
                        elif any(k in busca for k in ['transformador', 'trafo', 'subestação', 'subestacao']): cor, raio = '#28a745', 5.0
                        elif any(k in busca for k in ['chave', 'seccionador', 'fusivel']): cor, raio = '#ffc107', 4.0
                        elif any(k in busca for k in ['medidor', 'consumidor', 'cliente']): cor, raio = '#17a2b8', 2.5
                        else: cor, raio = '#dc3545', 2.5
                        return {'fillColor': cor, 'color': cor, 'weight': 1, 'fillOpacity': 0.9, 'radius': raio}
                    folium.GeoJson(
                        gdf_points, name="Equipamentos (Pontos)", marker=folium.CircleMarker(), 
                        style_function=get_point_style, popup=folium.GeoJsonPopup(fields=['Layer_Name', 'Name', 'Description'], aliases=['Camada:', 'Nome:', 'Detalhes:'])
                    ).add_to(mapa)
                if bounds is not None: mapa.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

            fg_equipes = folium.FeatureGroup(name="📍 Bases dos Levantadores")
            records_equipes = df_eq.drop_duplicates(subset=['Município', 'Levantador']).to_dict('records')
            for row in records_equipes:
                try:
                    lat_val, lon_val = float(row.get('Latitude', np.nan)), float(row.get('Longitude', np.nan))
                    if pd.notna(lat_val) and pd.notna(lon_val):
                        lev = str(row['Levantador'])
                        if lev in todos_levantadores:
                            folium.Marker(location=[lat_val, lon_val], icon=folium.Icon(color='red' if lev in criticos_tuple else 'green', icon='user', prefix='fa'), tooltip=f"Levantador: {html.escape(lev)}").add_to(fg_equipes)
                except (ValueError, TypeError): pass 

            df_notas_mapa = df_nt.copy()
            df_notas_mapa['Lat_Mapa'] = pd.to_numeric(df_notas_mapa.get('Lat_Mapa'), errors='coerce')
            df_notas_mapa['Lon_Mapa'] = pd.to_numeric(df_notas_mapa.get('Lon_Mapa'), errors='coerce')
            df_notas_mapa = df_notas_mapa.dropna(subset=['Lat_Mapa', 'Lon_Mapa'])
            
            if not df_notas_mapa.empty:
                df_notas_mapa['lat_jitter'] = df_notas_mapa['Lat_Mapa'] + np.random.normal(0, 0.004, len(df_notas_mapa))
                df_notas_mapa['lon_jitter'] = df_notas_mapa['Lon_Mapa'] + np.random.normal(0, 0.004, len(df_notas_mapa))
                
                if len(df_notas_mapa) > 500:
                    obras_coords = df_notas_mapa[['lat_jitter', 'lon_jitter']].values.tolist()
                    FastMarkerCluster(data=obras_coords, name="🏗️ Demandas Ativas (Fast Cluster)").add_to(mapa)
                else:
                    fg_obras = folium.FeatureGroup(name="🏗️ Demandas Ativas (Clusters)")
                    cluster_obras = MarkerCluster(name="Obras Agrupadas", disableClusteringAtZoom=13).add_to(fg_obras)
                    for row in df_notas_mapa.to_dict('records'):
                        safe_protocolo = html.escape(str(row.get('PROTOCOLO', '')))
                        safe_municipio = html.escape(str(row.get('MUNICIPIO', '')))
                        safe_levantador = html.escape(str(row.get('LEVANTADOR', '')))
                        
                        html_mini_card = f"""
                        <div style="font-family: Arial, sans-serif; font-size: 11px; width: 260px; line-height: 1.4; color: #222;">
                            <div style="background-color: #1A4F7C; color: white; padding: 5px; font-weight: bold; border-radius: 4px 4px 0 0; text-align: center;">INFORMAÇÕES DA OBRA</div>
                            <div style="padding: 7px; border: 1px solid #1A4F7C; border-top: none; background-color: #FFF; border-radius: 0 0 4px 4px;">
                                <b>PROTOCOLO:</b> {safe_protocolo}<br>
                                <b>MUNICIPIO:</b> {safe_municipio}<br>
                                <b>LEVANTADOR:</b> {safe_levantador}<br>
                            </div>
                        </div>
                        """
                        lev_obra = str(row.get('LEVANTADOR', SEM_LEVANTADOR))
                        cor_marcador = 'orange' if lev_obra == SEM_LEVANTADOR else ('red' if lev_obra in criticos_tuple else 'blue')
                        folium.Marker(location=[row['lat_jitter'], row['lon_jitter']], icon=folium.Icon(color=cor_marcador, icon='wrench', prefix='fa'), popup=folium.Popup(html_mini_card, max_width=310)).add_to(cluster_obras)
                    fg_obras.add_to(mapa)

            fg_equipes.add_to(mapa)
            folium.LayerControl().add_to(mapa)
            return mapa

        with st.spinner("Decodificando geometrias e renderizando mapa de alta performance..."):
            mapa_pronto = construir_mapa(df_eq_mapa_view, df_notas_mapa_view, tuple(levantadores_criticos), caminho_camada_temp)
            st_folium(mapa_pronto, use_container_width=True, height=850, returned_objects=[])

# -----------------------------------------------------------------------------
# VISÃO 2: FILTROS E GOVERNANÇA (APENAS LEITURA PARA VISITANTES)
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
# VISÃO 3: CARGA DE LOTES (SOMENTE ADMIN)
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
# VISÃO 4: LEVANTADORES (NOVA ABA - MUDANÇA DE RESIDÊNCIA)
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
    opcoes_mun = [""] + sorted([str(x).upper() for x in df_eq['Município'].dropna().unique()])
    
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
            process_analytical_data.clear()
            st.success("Residências atualizadas com sucesso!")
            st.rerun()

# -----------------------------------------------------------------------------
# VISÃO 5: GERENCIAMENTO DE ACESSOS (SOMENTE ADMIN)
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
# VISÃO 6: SIMULADOR DE ALOCAÇÃO
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
        ativos = pd.read_sql(f"""
            SELECT username, role 
            FROM usuarios 
            WHERE last_active >= '{limite_inatividade}'
            ORDER BY username ASC
        """, conn)

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

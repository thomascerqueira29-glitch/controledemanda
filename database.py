import streamlit as st
import pandas as pd
import sqlite3
import os
import hashlib
import numpy as np

# =============================================================================
# CONSTANTES GLOBAIS
# =============================================================================
DB_PATH = 'controle_torre_nip.db'
SEM_LEVANTADOR = "SEM LEVANTADOR"
# Atualizado para garantir que as rotinas de fila também reconheçam o status
STATUS_PRODUTIVIDADE = ["PENDENTE", "EM ANDAMENTO", "AGUARDANDO", "EM LEVANTAMENTO", "Em levantamento"]

# =============================================================================
# FUNÇÕES DE BANCO DE DADOS E AUTENTICAÇÃO
# =============================================================================
def hash_senha(senha):
    """Criptografa senhas"""
    return hashlib.sha256(str(senha).encode('utf-8')).hexdigest()

def init_databases():
    """Cria tabela de usuários se não existir"""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                        (username TEXT PRIMARY KEY, password TEXT, role TEXT, last_active TEXT)''')
        if not conn.execute("SELECT * FROM usuarios WHERE username='THOMAS'").fetchone():
            conn.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", 
                         ('THOMAS', hash_senha('admin123'), 'ADMIN'))
        conn.commit()

def init_business_db():
    """Garante que a estrutura base exista no SQLite"""
    colunas_oficiais = ['ID SISCO', 'STATUS SISCO', 'TIPO LIGACAO SISCO', 'DESCRIÇÃO SERVIÇO SISCO', 'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO', 'DATA DE VENCIMENTO']
    if os.path.exists(DB_PATH): 
        return
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            df_legacy = pd.read_excel('NOTAS.xlsx').fillna("").astype(str) if os.path.exists('NOTAS.xlsx') else pd.DataFrame(columns=colunas_oficiais)
            for col in colunas_oficiais:
                if col not in df_legacy.columns: df_legacy[col] = ""
            df_legacy[colunas_oficiais].to_sql('notas', conn, if_exists='replace', index=False)
                
            if os.path.exists('base levantador.xlsx'): 
                pd.read_excel('base levantador.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
            elif os.path.exists('EQUIPES.xlsx'): 
                pd.read_excel('EQUIPES.xlsx').to_sql('equipes', conn, if_exists='replace', index=False)
            else: 
                pd.DataFrame(columns=['Município', 'Estado', 'Levantador', 'Regional', 'Longitude', 'Latitude', 'Equipe', 'Residencia']).to_sql('equipes', conn, if_exists='replace', index=False)
    except Exception: pass

def sync_residencias_banco():
    pass

@st.cache_data(show_spinner=False)
def load_core_data():
    """MOTOR RECONSTRUÍDO: Carrega os dados e recalcula métricas para o Painel Executivo"""
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            df_notas = pd.read_sql("SELECT * FROM notas", conn)
            df_equipes = pd.read_sql("SELECT * FROM equipes", conn)
    except Exception:
        df_notas = pd.DataFrame()
        df_equipes = pd.DataFrame()

    # 1. Tratamento de Datas
    colunas_data = ['DATA CRIAÇAO SISCO', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'DATA DE VENCIMENTO']
    for col in colunas_data:
        if col in df_notas.columns:
            df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce', dayfirst=True)

    # 2. Tratamento de Coordenadas para o Mapa
    if not df_notas.empty:
        if 'LATITUDE' in df_notas.columns and 'LONGITUDE' in df_notas.columns:
            df_notas['Lat_Mapa'] = pd.to_numeric(df_notas['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
            df_notas['Lon_Mapa'] = pd.to_numeric(df_notas['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        else:
            df_notas['Lat_Mapa'] = np.nan
            df_notas['Lon_Mapa'] = np.nan
            
    if not df_equipes.empty:
        col_lat = 'Latitude' if 'Latitude' in df_equipes.columns else 'LATITUDE' if 'LATITUDE' in df_equipes.columns else None
        col_lon = 'Longitude' if 'Longitude' in df_equipes.columns else 'LONGITUDE' if 'LONGITUDE' in df_equipes.columns else None
        
        if col_lat and col_lon:
            df_equipes['Lat_Mapa'] = pd.to_numeric(df_equipes[col_lat].astype(str).str.replace(',', '.'), errors='coerce')
            df_equipes['Lon_Mapa'] = pd.to_numeric(df_equipes[col_lon].astype(str).str.replace(',', '.'), errors='coerce')
        else:
            df_equipes['Lat_Mapa'] = np.nan
            df_equipes['Lon_Mapa'] = np.nan

    # 3. A PONTE DE COMUNICAÇÃO: Cálculo de produtividade por Levantador (NOVA REGRA APLICADA)
    resumo_lev = pd.DataFrame(columns=['Levantador', 'Equipe', 'Total_Obras_Real'])
    criticos = []
    todos_levs = []

    # Carrega primeiro as equipes oficiais
    if not df_equipes.empty and 'Levantador' in df_equipes.columns:
        if 'Equipe' in df_equipes.columns:
            resumo_lev = df_equipes[['Levantador', 'Equipe']].drop_duplicates()
        else:
            resumo_lev = df_equipes[['Levantador']].drop_duplicates()
            resumo_lev['Equipe'] = 'Sem Equipe'
            
    if not df_notas.empty and 'LEVANTADOR' in df_notas.columns and 'STATUS LIST' in df_notas.columns:
        
        # REGRA 1: Filtra apenas obras que estão com STATUS LIST igual a 'Em levantamento'
        mask_em_levantamento = df_notas['STATUS LIST'].astype(str).str.strip().str.upper() == 'EM LEVANTAMENTO'
        df_em_levantamento = df_notas[mask_em_levantamento].copy()
        
        # Conta as obras válidas agrupando por Levantador
        contagem = df_em_levantamento.groupby('LEVANTADOR').size()
        
        # REGRA 2: Identifica Levantadores Provisórios (nomes que estão na base, mas não na lista oficial de equipes)
        levs_com_obras = set(contagem.index) - {SEM_LEVANTADOR, 'nan', 'NAN', '', 'None'}
        levs_oficiais = set(resumo_lev['Levantador']) if not resumo_lev.empty else set()
        levs_provisorios = list(levs_com_obras - levs_oficiais)
        
        # Adiciona os Provisórios na tabela de resumo usando o próprio nome na coluna 'Equipe'
        if levs_provisorios:
            df_provisorios = pd.DataFrame({
                'Levantador': levs_provisorios,
                'Equipe': levs_provisorios
            })
            resumo_lev = pd.concat([resumo_lev, df_provisorios], ignore_index=True)
            
        # Aplica a contagem em todos (Oficiais + Provisórios)
        if not resumo_lev.empty:
            resumo_lev['Total_Obras_Real'] = resumo_lev['Levantador'].map(contagem).fillna(0).astype(int)
    else:
        if not resumo_lev.empty:
            resumo_lev['Total_Obras_Real'] = 0
            
    # Identifica Levantadores Críticos (< 45 obras) e extrai lista limpa
    if not resumo_lev.empty:
        criticos = resumo_lev[resumo_lev['Total_Obras_Real'] < 45]['Levantador'].tolist()
        todos_levs = sorted([str(l) for l in resumo_lev['Levantador'].unique() if pd.notna(l) and str(l).strip() != ''])

    return df_notas, df_equipes, resumo_lev, criticos, todos_levs, {}, {}, pd.DataFrame()

def save_notas_to_db(df, acao="Atualização", backup=False):
    """Salva a base atualizada e força a limpeza de memória do Streamlit"""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        df.to_sql('notas', conn, if_exists='replace', index=False)
    load_core_data.clear()
    return True

# =============================================================================
# FUNÇÕES AUXILIARES E MATEMÁTICAS
# =============================================================================
def vectorized_haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371 * c

def parse_kmz_advanced(caminho):
    return pd.DataFrame(), pd.DataFrame(), None

def calcular_sla_vetorizado(df):
    if df.empty: return df
    df_copy = df.copy()
    if 'Status_SLA' not in df_copy.columns:
        df_copy['Status_SLA'] = 'No Prazo'
    return df_copy

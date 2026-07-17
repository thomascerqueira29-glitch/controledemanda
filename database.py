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
STATUS_PRODUTIVIDADE = ["PENDENTE", "EM ANDAMENTO", "AGUARDANDO"]

# =============================================================================
# FUNÇÕES DE BANCO DE DADOS E AUTENTICAÇÃO (SQLITE NATIVO)
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
    """Inicia tabelas de negócio e barra o loop de reset"""
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
    """Carrega dados para o pandas sem causar conflitos de engine"""
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            df_notas = pd.read_sql("SELECT * FROM notas", conn)
            df_equipes = pd.read_sql("SELECT * FROM equipes", conn)
    except Exception:
        df_notas = pd.DataFrame()
        df_equipes = pd.DataFrame()
    return df_notas, df_equipes, pd.DataFrame(), [], [], {}, {}, pd.DataFrame()

def save_notas_to_db(df, acao="Atualização"):
    """Salva os dados de volta no banco de dados"""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        df.to_sql('notas', conn, if_exists='replace', index=False)
    load_core_data.clear()
    return True

# =============================================================================
# FUNÇÕES AUXILIARES E MATEMÁTICAS (NECESSÁRIAS PARA O PAINEL.PY)
# =============================================================================
def vectorized_haversine(lat1, lon1, lat2, lon2):
    """Cálculo de distância em KM entre coordenadas (Fórmula de Haversine)"""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371 * c

def parse_kmz_advanced(caminho):
    """Placeholder para leitura avançada de KMZ"""
    return pd.DataFrame(), pd.DataFrame(), None

def calcular_sla_vetorizado(df):
    """Cálculo de SLA (Service Level Agreement) para o Painel"""
    if df.empty:
        return df
    
    df_copy = df.copy()
    if 'Status_SLA' not in df_copy.columns:
        df_copy['Status_SLA'] = 'No Prazo'
    return df_copy

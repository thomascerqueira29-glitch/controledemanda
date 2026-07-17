import streamlit as st
import pandas as pd
import sqlite3
import os
import hashlib
import numpy as np

# Constantes globais
DB_PATH = 'controle_torre_nip.db'
SEM_LEVANTADOR = "SEM LEVANTADOR"
STATUS_PRODUTIVIDADE = ["PENDENTE", "EM ANDAMENTO", "AGUARDANDO"]

def hash_senha(senha):
    return hashlib.sha256(str(senha).encode('utf-8')).hexdigest()

def init_databases():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                        (username TEXT PRIMARY KEY, password TEXT, role TEXT, last_active TEXT)''')
        # Cria usuário admin se não existir
        if not conn.execute("SELECT * FROM usuarios WHERE username='THOMAS'").fetchone():
            conn.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", 
                         ('THOMAS', hash_senha('admin123'), 'ADMIN'))
        conn.commit()

def init_business_db():
    # Estrutura base de tabelas
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS notas 
                        ("PROTOCOLO" TEXT, "MUNICIPIO" TEXT, "LEVANTADOR" TEXT, "STATUS LIST" TEXT, 
                         "REGIONAL" TEXT, "TIPO LIGACAO" TEXT, "STATUS SAP" TEXT, "ENDEREÇO" TEXT, 
                         "LONGITUDE" REAL, "LATITUDE" REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS equipes 
                        ("Levantador" TEXT, "Equipe" TEXT, "Residencia" TEXT, "Município" TEXT, 
                         "Latitude" REAL, "Longitude" REAL, "Regional" TEXT)''')
        conn.commit()

def sync_residencias_banco():
    pass

@st.cache_data(show_spinner=False)
def load_core_data():
    with sqlite3.connect(DB_PATH) as conn:
        df_notas = pd.read_sql("SELECT * FROM notas", conn)
        df_equipes = pd.read_sql("SELECT * FROM equipes", conn)
    
    # Prepara dados para o painel
    resumo_lev = df_equipes[['Levantador', 'Equipe']].drop_duplicates()
    resumo_lev['Total_Obras_Real'] = resumo_lev['Levantador'].map(df_notas.groupby('LEVANTADOR').size()).fillna(0)
    
    criticos = resumo_lev[resumo_lev['Total_Obras_Real'] < 45]['Levantador'].tolist()
    todos_levs = sorted(df_equipes['Levantador'].unique().tolist())
    
    return df_notas, df_equipes, resumo_lev, criticos, todos_levs, {}, {}, pd.DataFrame()

def save_notas_to_db(df, acao_auditoria="Edição"):
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql('notas', conn, if_exists='replace', index=False)
    load_core_data.clear()
    return True

# Funções auxiliares mantidas para compatibilidade
def vectorized_haversine(lat1, lon1, lat2, lon2):
    return 0 # Placeholder simples

def parse_kmz_advanced(caminho):
    return pd.DataFrame(), pd.DataFrame(), None

def calcular_sla_vetorizado(df):
    return pd.DataFrame(columns=['REGIONAL', 'Status_SLA'])

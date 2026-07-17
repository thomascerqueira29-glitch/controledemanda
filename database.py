import streamlit as st
import pandas as pd
import os
import sqlite3
import hashlib
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Configuração de Banco
DB_PATH = 'controle_torre_nip.db'
DB_URL = f'sqlite:///{DB_PATH}'

# Tenta criar a engine, se falhar, o sistema cai aqui e nos avisa
try:
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine)
    Base = declarative_base()
except Exception as e:
    st.error(f"Erro Crítico de Engine: {e}")

# Importações de Modelos adiadas para evitar erros de importação circulares
def init_databases():
    # Carregamento simples apenas para garantir que as tabelas existam
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                        (username TEXT PRIMARY KEY, password TEXT, role TEXT, last_active TEXT)''')
        # ... (Manter aqui a criação de outras tabelas se necessário)
        conn.commit()

def get_session():
    return SessionLocal()

def hash_senha(senha):
    return hashlib.sha256(str(senha).encode('utf-8')).hexdigest()

def init_business_db():
    pass

@st.cache_data(show_spinner=False)
def load_core_data():
    """Usa Pandas para ler direto do arquivo, evitando conflitos de Engine"""
    with sqlite3.connect(DB_PATH) as conn:
        df_notas = pd.read_sql("SELECT * FROM notas", conn)
        df_equipes = pd.read_sql("SELECT * FROM equipes", conn)
    return df_notas, df_equipes, pd.DataFrame(), [], [], {}, {}, pd.DataFrame()

def save_notas_to_db(df, acao="Atualização"):
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql('notas', conn, if_exists='replace', index=False)
    return True

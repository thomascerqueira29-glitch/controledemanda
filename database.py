import streamlit as st
import pandas as pd
import os
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import hashlib

DB_URL = 'sqlite:///controle_torre_nip.db'
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# --- MODELOS ---
class Usuario(Base):
    __tablename__ = 'usuarios'
    username = Column(String, primary_key=True)
    password = Column(String)
    role = Column(String)
    last_active = Column(String)

# --- FUNÇÕES CORE ---
def get_session():
    return SessionLocal()

def hash_senha(senha):
    return hashlib.sha256(str(senha).encode('utf-8')).hexdigest()

def init_databases():
    Base.metadata.create_all(engine)
    session = get_session()
    if not session.query(Usuario).filter_by(username='THOMAS').first():
        session.add(Usuario(username='THOMAS', password=hash_senha('admin123'), role='ADMIN'))
        session.commit()
    session.close()

def init_business_db():
    if not os.path.exists('controle_torre_nip.db'):
        # Só importa o Excel se o banco for criado agora (Primeira vez)
        pass 

@st.cache_data(show_spinner=False)
def load_core_data():
    """Lê dados para análise via Pandas (Alta Performance)"""
    df_notas = pd.read_sql("SELECT * FROM notas", engine)
    df_equipes = pd.read_sql("SELECT * FROM equipes", engine)
    return df_notas, df_equipes, pd.DataFrame(), [], [], {}, {}, pd.DataFrame()

def save_notas_to_db(df, acao="Atualização"):
    df.to_sql('notas', engine, if_exists='replace', index=False)
    return True

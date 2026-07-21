import sqlite3
import bcrypt
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv('DB_PATH', 'portal_nip.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed_password):
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabela de Usuários
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    
    # Tabela de Auditoria
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            acao TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Cria usuário ADMIN padrão se não existir (senha: admin123)
    cursor.execute("SELECT * FROM usuarios WHERE username = 'ADMIN'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", 
                       ("ADMIN", hash_password("admin123"), "ADMIN"))
                       
    conn.commit()
    conn.close()

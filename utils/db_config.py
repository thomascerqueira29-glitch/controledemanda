import sqlite3
import os
import hashlib

def hash_password(password):
    """Criptografa a senha usando SHA-256 para não ser salva em texto puro."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_path():
    """Localiza ou define o nome correto do banco de dados"""
    if os.path.exists("controle_torre_nip.db"):
        return "controle_torre_nip.db"
    elif os.path.exists("nip_database.db"):
        return "nip_database.db"
    else:
        return "database.db"

def get_connection():
    """Cria a conexão centralizada com o banco de dados SQLite"""
    return sqlite3.connect(get_db_path(), check_same_thread=False)

def init_db():
    """
    Inicializa as tabelas obrigatórias no início do app.
    Garante que o DB exista antes das telas carregarem.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Cria a tabela de usuários com a coluna de senha
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    # Verifica se existem usuários. Se não, cria o admin padrão.
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        # Insere a senha já criptografada!
        senha_padrao_criptografada = hash_password("123456")
        cursor.execute(
            "INSERT INTO usuarios (username, role, password) VALUES (?, ?, ?)",
            ('THOMAS', 'ADMIN', senha_padrao_criptografada)
        )
        
    conn.commit()
    conn.close()

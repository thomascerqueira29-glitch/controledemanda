import pandas as pd
from utils.db_config import get_connection

# ==========================================
# QUERIES DA TELA DE ACESSOS
# ==========================================
def get_all_users():
    """Busca todos os usuários (sem a senha) para exibir na tabela."""
    conn = get_connection()
    df = pd.read_sql("SELECT id, username, role FROM usuarios", conn)
    conn.close()
    return df

def insert_user(username, role, password_hash):
    """Insere um novo usuário no banco de dados."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO usuarios (username, role, password) VALUES (?, ?, ?)",
        (username, role, password_hash)
    )
    conn.commit()
    conn.close()

# ==========================================
# QUERIES DO PAINEL EXECUTIVO E CROQUIS
# ==========================================
def get_dados_painel():
    """
    Busca os dados principais para o Painel.
    (Aqui estou criando dados de exemplo focados na sua regra de negócios de Croquis, SLAs e Territórios. 
    Depois você pode substituir pelo "SELECT * FROM sua_tabela_real" caso já tenha uma.)
    """
    dados_exemplo = {
        'ID_Ordem': ['ORD-001', 'ORD-002', 'ORD-003', 'ORD-004', 'ORD-005', 'ORD-006'],
        'Status': ['Gerado', 'Pendente', 'Gerado', 'Em Andamento', 'Pendente', 'Gerado'],
        'Territorio': ['Norte', 'Sul', 'Norte', 'Leste', 'Oeste', 'Sul'],
        'SLA_Dias': [2, 5, 1, 3, 6, 2],
        'Levantador': ['THOMAS', 'MARIA', 'PEDRO', 'ANA', 'THOMAS', 'LUCAS']
    }
    return pd.DataFrame(dados_exemplo)

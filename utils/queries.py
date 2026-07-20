import pandas as pd
from utils.db_config import get_connection

def get_all_users():
    conn = get_connection()
    df = pd.read_sql("SELECT id, username, role FROM usuarios", conn)
    conn.close()
    return df

def insert_user(username, role, password_hash):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO usuarios (username, role, password) VALUES (?, ?, ?)",
        (username, role, password_hash)
    )
    conn.commit()
    conn.close()

def get_dados_painel():
    """
    Simulação de dados REAIS com Coordenadas, Alocação e SLA.
    Quando você conectar na sua tabela verdadeira, basta garantir que ela tenha essas colunas.
    """
    dados_exemplo = {
        'ID_Ordem': ['ORD-001', 'ORD-002', 'ORD-003', 'ORD-004', 'ORD-005', 'ORD-006', 'ORD-007', 'ORD-008'],
        'Status': ['Gerado', 'Pendente', 'Gerado', 'Em Andamento', 'Pendente', 'Gerado', 'Em Andamento', 'Gerado'],
        'Territorio': ['São Luís', 'Imperatriz', 'São Luís', 'Timon', 'Caxias', 'Imperatriz', 'São Luís', 'Timon'],
        'SLA_Dias': [2, 5, 1, 3, 6, 2, 4, 1],
        'Levantador': ['THOMAS', 'MARIA', 'PEDRO', 'ANA', 'THOMAS', 'LUCAS', 'MARIA', 'PEDRO'],
        'Equipe_Alocada': ['Equipe Alpha', 'Aguardando', 'Equipe Beta', 'Equipe Alpha', 'Aguardando', 'Equipe Gama', 'Equipe Beta', 'Equipe Gama'],
        'LAT': [-2.5391, -5.5265, -2.5450, -5.0931, -4.8584, -5.5300, -2.5200, -5.0900], # Latitudes MA
        'LON': [-44.2829, -47.4761, -44.2900, -42.8276, -43.3592, -47.4800, -44.2700, -42.8200]  # Longitudes MA
    }
    return pd.DataFrame(dados_exemplo)

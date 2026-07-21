import pandas as pd
from utils.db_config import get_connection

# ==========================================
# TRILHA DE AUDITORIA
# ==========================================
def insert_audit_log(username, acao):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO audit_logs (username, acao) VALUES (?, ?)", (username, acao))
    conn.commit()
    conn.close()

# ==========================================
# QUERIES DE USUÁRIOS
# ==========================================
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

# ==========================================
# QUERIES DO PAINEL EXECUTIVO (COM RLS)
# ==========================================
def get_dados_painel(perfil_usuario, username):
    """
    Simulação de dados. 
    Aplica filtro automático se o usuário for LEVANTADOR.
    """
    dados_exemplo = {
        'ID_Ordem': ['ORD-001', 'ORD-002', 'ORD-003', 'ORD-004', 'ORD-005', 'ORD-006', 'ORD-007', 'ORD-008', 'ORD-009'],
        'Status': ['Gerado', 'Pendente', 'Gerado', 'Em Andamento', 'Pendente', 'Gerado', 'Em Andamento', 'Gerado', 'Gerado'],
        'Territorio': ['São Luís', 'Imperatriz', 'São Luís', 'Timon', 'Caxias', 'Imperatriz', 'São Luís', 'Timon', 'São Luís'],
        'SLA_Dias': [2, 5, 1, 3, 6, 2, 4, 1, 0],
        'Levantador': ['THOMAS', 'MARIA', 'PEDRO', 'ANA', 'THOMAS', 'LUCAS', 'MARIA', 'PEDRO', 'THOMAS'],
        'Equipe_Alocada': ['Equipe Alpha', 'Aguardando', 'Equipe Beta', 'Equipe Alpha', 'Aguardando', 'Equipe Gama', 'Equipe Beta', 'Equipe Gama', 'Aguardando'],
        'LAT': [-2.5391, -5.5265, -2.5450, -5.0931, -4.8584, -5.5300, -2.5200, -5.0900, None], # ORD-009 sem LAT
        'LON': [-44.2829, -47.4761, -44.2900, -42.8276, -43.3592, -47.4800, -44.2700, -42.8200, None]  # ORD-009 sem LON
    }
    
    df = pd.DataFrame(dados_exemplo)
    
    # SEGURANÇA EM NÍVEL DE LINHA (RLS)
    if perfil_usuario == "LEVANTADOR":
        df = df[df['Levantador'].str.strip().str.upper() == username.strip().upper()]
        
    return df

# ==========================================
# CARGA DE LOTES
# ==========================================
def save_notas_to_db(df):
    conn = get_connection()
    try:
        # Substitua 'tabela_obras_oficial' pelo nome real da sua tabela
        df.to_sql('tabela_obras_oficial', conn, if_exists='append', index=False)
    except Exception as e:
        raise e
    finally:
        conn.close()

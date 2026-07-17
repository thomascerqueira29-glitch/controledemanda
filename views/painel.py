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

    # 1. Tratamento de Datas (Essencial para os cálculos do Painel)
    colunas_data = ['DATA CRIAÇAO SISCO', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'DATA DE VENCIMENTO']
    for col in colunas_data:
        if col in df_notas.columns:
            df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce', dayfirst=True)

    # 2. Tratamento de Coordenadas para o Mapa (CORREÇÃO AQUI)
    if not df_notas.empty:
        if 'LATITUDE' in df_notas.columns and 'LONGITUDE' in df_notas.columns:
            # Substitui vírgulas por pontos (se houver) e converte para número
            df_notas['Lat_Mapa'] = pd.to_numeric(df_notas['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
            df_notas['Lon_Mapa'] = pd.to_numeric(df_notas['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        else:
            df_notas['Lat_Mapa'] = np.nan
            df_notas['Lon_Mapa'] = np.nan
            
    if not df_equipes.empty:
        # Busca colunas de Lat/Lon nas equipes, ignorando maiúsculas e minúsculas
        col_lat = 'Latitude' if 'Latitude' in df_equipes.columns else 'LATITUDE' if 'LATITUDE' in df_equipes.columns else None
        col_lon = 'Longitude' if 'Longitude' in df_equipes.columns else 'LONGITUDE' if 'LONGITUDE' in df_equipes.columns else None
        
        if col_lat and col_lon:
            df_equipes['Lat_Mapa'] = pd.to_numeric(df_equipes[col_lat].astype(str).str.replace(',', '.'), errors='coerce')
            df_equipes['Lon_Mapa'] = pd.to_numeric(df_equipes[col_lon].astype(str).str.replace(',', '.'), errors='coerce')
        else:
            df_equipes['Lat_Mapa'] = np.nan
            df_equipes['Lon_Mapa'] = np.nan

    # 3. A PONTE DE COMUNICAÇÃO: Cálculo de produtividade por Levantador
    resumo_lev = pd.DataFrame(columns=['Levantador', 'Equipe', 'Total_Obras_Real'])
    criticos = []
    todos_levs = []

    if not df_equipes.empty:
        if 'Levantador' in df_equipes.columns and 'Equipe' in df_equipes.columns:
            resumo_lev = df_equipes[['Levantador', 'Equipe']].drop_duplicates()
        elif 'Levantador' in df_equipes.columns:
            resumo_lev = df_equipes[['Levantador']].drop_duplicates()
            resumo_lev['Equipe'] = 'Sem Equipe'
            
        if not df_notas.empty and 'LEVANTADOR' in df_notas.columns:
            contagem = df_notas.groupby('LEVANTADOR').size()
            resumo_lev['Total_Obras_Real'] = resumo_lev['Levantador'].map(contagem).fillna(0)
        else:
            resumo_lev['Total_Obras_Real'] = 0
            
        # Identifica Levantadores Críticos (< 45 obras)
        if not resumo_lev.empty:
            criticos = resumo_lev[resumo_lev['Total_Obras_Real'] < 45]['Levantador'].tolist()
        
        if 'Levantador' in df_equipes.columns:
            todos_levs = sorted(df_equipes['Levantador'].dropna().astype(str).unique().tolist())

    return df_notas, df_equipes, resumo_lev, criticos, todos_levs, {}, {}, pd.DataFrame()

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster
import plotly.express as px
import numpy as np
import os
import io
import sqlite3
import pandera as pa
import streamlit_antd_components as sac

# Configuração de Layout e Identidade Visual Corporativa
st.set_page_config(page_title="Portal Corporativo NIP", layout="wide", page_icon="🏗️")

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES DE ESTADO, BANCO DE DADOS E NAVEGAÇÃO
# -----------------------------------------------------------------------------
DB_PATH = 'controle_torre_nip.db'

if 'db_initialized' not in st.session_state:
    st.session_state.db_initialized = False

if 'menu_idx' not in st.session_state:
    st.session_state.menu_idx = 0

STATUS_PRODUTIVIDADE = ["CORRECAO DE LEVANTAMENTO", "EM LEVANTAMENTO", "PRE ANALISE"]

if 'filtros_salvos' not in st.session_state:
    st.session_state.filtros_salvos = {
        'lev': 'TODOS', 'reg': 'TODOS', 'mun': 'TODOS',
        'lig': 'TODOS', 'sap': 'TODOS', 'list': [] 
    }

def filtrar_levantador_governanca(nome_lev):
    st.session_state.filtros_salvos['lev'] = nome_lev
    st.session_state.filtros_salvos['reg'] = 'TODOS'
    st.session_state.filtros_salvos['mun'] = 'TODOS'
    st.session_state.filtros_salvos['lig'] = 'TODOS'
    st.session_state.filtros_salvos['sap'] = 'TODOS'
    st.session_state.filtros_salvos['list'] = STATUS_PRODUTIVIDADE.copy() 
    st.session_state.menu_idx = 1  

def normalizar_texto(series):
    s = series.astype(str).str.upper().str.strip()
    return s.replace({
        r'[ÁÀÃÂ]': 'A', r'[ÉÈÊ]': 'E', r'[ÍÌ]': 'I',
        r'[ÓÒÕÔ]': 'O', r'[ÚÙ]': 'U', r'Ç': 'C'
    }, regex=True)

# -----------------------------------------------------------------------------
# 1. ENGENHARIA DE DADOS E CONEXÃO SQLITE
# -----------------------------------------------------------------------------
def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notas';")
    if not cursor.fetchone():
        if os.path.exists('NOTAS.xlsx'):
            df_legacy = pd.read_excel('NOTAS.xlsx')
            df_legacy.to_sql('notas', conn, if_exists='replace', index=False)
        else:
            df_empty = pd.DataFrame(columns=['ID SISCO', 'STATUS SAP', 'LEVANTADOR', 'PROTOCOLO', 'REGIONAL', 'MUNICIPIO', 'TIPO LIGACAO', 'STATUS LIST', 'DATA DE DESPACHO CAMPO', 'STATUS SISCO'])
            df_empty.to_sql('notas', conn, if_exists='replace', index=False)
            
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipes';")
    if not cursor.fetchone():
        if os.path.exists('EQUIPES.xlsx'):
            df_eq_legacy = pd.read_excel('EQUIPES.xlsx')
            df_eq_legacy.to_sql('equipes', conn, if_exists='replace', index=False)
        else:
            df_eq_empty = pd.DataFrame(columns=['Município', 'Estado', 'Levantador', 'Regional', 'Longitude', 'Latitude', 'Equipe'])
            df_eq_empty.to_sql('equipes', conn, if_exists='replace', index=False)
    conn.close()
    st.session_state.db_initialized = True

if not st.session_state.db_initialized:
    init_database()

def load_data_from_db():
    conn = get_db_connection()
    df_notas = pd.read_sql("SELECT * FROM notas", conn)
    df_equipes = pd.read_sql("SELECT * FROM equipes", conn)
    conn.close()
    return df_notas, df_equipes

def save_notas_to_db(df_notas_atualizado):
    try:
        conn = get_db_connection()
        df_notas_atualizado.to_sql('notas', conn, if_exists='replace', index=False)
        conn.close()
        return True
    except Exception as e:
        st.error(f"Falha de gravação no banco de dados: {e}")
        return False

def auto_assign_levantador(df_notas, df_equipes):
    df_notas = df_notas.copy()
    df_eq_clean = df_equipes.dropna(subset=['Município']).drop_duplicates(subset=['Município'])
    mapa_levantadores = df_eq_clean.set_index('Município')['Levantador'].to_dict()
    
    df_notas['MUNICIPIO'] = df_notas['MUNICIPIO'].astype(str).str.upper().str.strip()
    if 'LEVANTADOR' not in df_notas.columns:
        df_notas['LEVANTADOR'] = 'SEM LEVANTADOR'
    else:
        df_notas['LEVANTADOR'] = df_notas['LEVANTADOR'].astype(str).str.upper().str.strip()
        
    mask_sem_levantador = (
        df_notas['LEVANTADOR'].isna() | (df_notas['LEVANTADOR'] == 'SEM LEVANTADOR') | 
        (df_notas['LEVANTADOR'] == '') | (df_notas['LEVANTADOR'] == 'NAN') | (df_notas['LEVANTADOR'] == 'NONE')
    )
    df_notas.loc[mask_sem_levantador, 'LEVANTADOR'] = (
        df_notas.loc[mask_sem_levantador, 'MUNICIPIO'].map(mapa_levantadores).fillna('SEM LEVANTADOR')
    )
    
    # Injeta a coluna DATA DE VENCIMENTO automaticamente se ela não existir no BD antigo
    for col in ['STATUS LIST', 'DATA DE DESPACHO CAMPO', 'STATUS SISCO', 'DATA DE VENCIMENTO']:
        if col not in df_notas.columns:
            df_notas[col] = ""
            
    df_notas['STATUS LIST'] = df_notas['STATUS LIST'].astype(str).str.upper().str.strip()
    return df_notas

df_notas_db, df_equipes_db = load_data_from_db()
df_notas_db = auto_assign_levantador(df_notas_db, df_equipes_db)

# -----------------------------------------------------------------------------
# 2. PROCESSAMENTO, MÉTRICAS ANALÍTICAS E CÁLCULO DE SLA
# -----------------------------------------------------------------------------
# --- FUNÇÃO DE INTELIGÊNCIA: SLA E VENCIMENTOS ---
def classificar_prazo(row):
    tipo = str(row.get('TIPO LIGACAO', '')).strip().upper()
    hoje = pd.Timestamp.now().normalize()
    
    grupo_1 = ['ASC', 'UNI', 'UNO']
    grupo_2 = ['SEG', 'SID', 'EUR', 'MGD', 'MTP', 'UNR'] 
    grupo_crono = ['LPT', 'REG', 'PMC', 'ERD', 'SEQ', 'BCP', 'BRE', 'BRT', 'DIG', 'DIS', 'DLD', 'INT', 'MEL', 'OCP', 'TRI', 'EQP', 'FIM', 'MBT', 'MMT']
    grupo_4 = ['NIV']
    
    # Regra do Cronograma Manual
    if tipo in grupo_crono:
        val_venc = row.get('DATA DE VENCIMENTO')
        if pd.isna(val_venc) or str(val_venc).strip() in ['', 'NAN', 'NAT', 'NONE']:
            return "Sem Data"
        dt_venc = pd.to_datetime(val_venc, errors='coerce', dayfirst=True)
        if pd.isna(dt_venc): return "Sem Data"
        dt_venc = dt_venc.normalize()
        
        diff = (dt_venc - hoje).days
        if diff < 0: return "Vencida"
        elif diff <= 3: return "Vencimento Próximo"
        else: return "No Prazo"
        
    # Regra das Datas de Despacho Automáticas
    else:
        val_desp = row.get('DATA DE DESPACHO CAMPO')
        if pd.isna(val_desp) or str(val_desp).strip() in ['', 'NAN', 'NAT', 'NONE']:
            return "Sem Data"
        dt_desp = pd.to_datetime(val_desp, errors='coerce', dayfirst=True)
        if pd.isna(dt_desp): return "Sem Data"
        dt_desp = dt_desp.normalize()
        
        dias_corridos = (hoje - dt_desp).days
        if dias_corridos < 0: dias_corridos = 0
        
        if tipo in grupo_1:
            if dias_corridos <= 10: return "No Prazo"
            elif dias_corridos <= 15: return "Vencimento Próximo"
            else: return "Vencida"
        elif tipo in grupo_2:
            if dias_corridos <= 16: return "No Prazo"
            elif dias_corridos <= 24: return "Vencimento Próximo"
            else: return "Vencida"
        elif tipo in grupo_4:
            if dias_corridos <= 5: return "No Prazo"
            elif dias_corridos <= 8: return "Vencimento Próximo"
            else: return "Vencida"
        else:
            # Fallback (Garante cobertura)
            if dias_corridos <= 10: return "No Prazo"
            elif dias_corridos <= 15: return "Vencimento Próximo"
            else: return "Vencida"

df_coords = df_equipes_db.dropna(subset=['Município', 'Latitude', 'Longitude']).drop_duplicates(subset=['Município'])
mapa_lat = pd.to_numeric(df_coords.set_index('Município')['Latitude'], errors='coerce').to_dict()
mapa_lon = pd.to_numeric(df_coords.set_index('Município')['Longitude'], errors='coerce').to_dict()

df_notas_calc = df_notas_db.copy()
df_notas_calc['Latitude'] = df_notas_calc['MUNICIPIO'].map(mapa_lat)
df_notas_calc['Longitude'] = df_notas_calc['MUNICIPIO'].map(mapa_lon)

# Aplica a inteligência de Prazos em todo o DataFrame
df_notas_calc['Status SLA'] = df_notas_calc.apply(classificar_prazo, axis=1)

municipios_por_levantador = df_equipes_db.groupby('Levantador')['Município'].nunique().reset_index()
municipios_por_levantador.columns = ['Levantador', 'Qtd_Municipios']

cond_list_real = df_notas_calc['STATUS LIST'].isin(STATUS_PRODUTIVIDADE)
df_filtrado_status = df_notas_calc[cond_list_real]
contagem_produtividade = df_filtrado_status['LEVANTADOR'].value_counts().reset_index()
contagem_produtividade.columns = ['Levantador', 'Total_Obras_Real']

todos_levantadores = [l for l in df_equipes_db['Levantador'].dropna().unique() if str(l).strip() not in ['SEM LEVANTADOR', 'NAN', '', 'None']]

resumo_levantadores = pd.DataFrame({'Levantador': todos_levantadores})
resumo_levantadores = pd.merge(resumo_levantadores, contagem_produtividade, on='Levantador', how='left').fillna(0)
resumo_levantadores['Total_Obras_Real'] = resumo_levantadores['Total_Obras_Real'].astype(int)

mapa_lev_equipe = df_equipes_db.dropna(subset=['Levantador', 'Equipe']).drop_duplicates(subset=['Levantador']).set_index('Levantador')['Equipe'].to_dict()
resumo_levantadores['Equipe'] = resumo_levantadores['Levantador'].map(mapa_lev_equipe).fillna('SEM EQUIPE')

levantadores_criticos = resumo_levantadores[resumo_levantadores['Total_Obras_Real'] < 45]['Levantador'].tolist()

# -----------------------------------------------------------------------------
# 3. INTERFACE DE NAVEGAÇÃO PREMIUM LATERAL
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 👤 Portal NIP")
    st.caption("Ecossistema de Governança")
    st.markdown("---")
    
    opcoes_menu = ['Painel Executivo', 'Busca e Governança', 'Carga de Lotes']
    
    menu_selecionado = sac.menu([
        sac.MenuItem(opcoes_menu[0], icon='pie-chart-fill'),
        sac.MenuItem(opcoes_menu[1], icon='sliders'),
        sac.MenuItem(opcoes_menu[2], icon='cloud-upload-fill'),
    ], index=st.session_state.menu_idx, format_func='title', size='md')
    
    if menu_selecionado in opcoes_menu:
        st.session_state.menu_idx = opcoes_menu.index(menu_selecionado)

# --- VISÃO 1: PAINEL EXECUTIVO E MAPAS ---
if menu_selecionado == 'Painel Executivo':
    st.markdown("### Monitoramento de Produtividade (Meta: Mínimo 45 obras)")
    
    if len(resumo_levantadores) == 0 or len(df_notas_db) == 0:
        st.warning("O banco de dados de notas está vazio. Realize uma carga em lote para ativar os indicadores.")
    else:
        for i in range(0, len(resumo_levantadores), 4):
            chunk = resumo_levantadores.iloc[i:i+4]
            cols = st.columns(4)
            for idx, (_, row) in enumerate(chunk.iterrows()):
                lev_nome = row['Levantador']
                qtd_obras_reais = row['Total_Obras_Real']
                eq_nome = row['Equipe']
                is_critico = lev_nome in levantadores_criticos
                
                cor_hex = "#D9534F" if is_critico else "#5CB85C"
                bg_hex = "rgba(217, 83, 79, 0.07)" if is_critico else "rgba(92, 184, 92, 0.07)"
                saldo_necessario = max(0, 45 - qtd_obras_reais)
                
                with cols[idx]:
                    st.markdown(
                        f"""
                        <div style='padding: 12px; border-radius: 6px; background-color: {bg_hex}; border-left: 6px solid {cor_hex}; margin-bottom: 5px; height: 130px; display: flex; flex-direction: column; justify-content: space-between;'>
                            <div>
                                <strong style='font-size: 14px; color: #111;'>{lev_nome}</strong><br>
                                <span style='font-size: 12px; color: #555;'>Equipe: {eq_nome}</span><br>
                            </div>
                            <div style='font-size: 13px; color: #333; margin-top: auto;'>
                                Demandas Produtivas Ativas:<br>
                                <span style='font-size: 16px; font-weight: bold; color: {cor_hex};'>{qtd_obras_reais} / 45</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True
                    )
                    
                    b1, b2 = st.columns([1.3, 1])
                    with b1:
                        if is_critico:
                            if st.button(f"⚡ +{saldo_necessario} Reais", key=f"btn_atrib_{lev_nome}"):
                                cond_livres_reais = (df_notas_db['LEVANTADOR'] == 'SEM LEVANTADOR') & (df_notas_db['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))
                                obras_livres = df_notas_db[cond_livres_reais].index
                                
                                if len(obras_livres) == 0:
                                    st.error("Sem demandas livres.")
                                else:
                                    qtd_atribuir = min(saldo_necessario, len(obras_livres))
                                    indices_para_mudar = obras_livres[:qtd_atribuir]
                                    df_notas_db.loc[indices_para_mudar, 'LEVANTADOR'] = lev_nome
                                    if save_notas_to_db(df_notas_db):
                                        st.success(f"{qtd_atribuir} obras vinculadas a {lev_nome}.")
                                        st.rerun()
                        else:
                            st.button("✅ Bateu a Meta", key=f"btn_ok_{lev_nome}", disabled=True)
                            
                    with b2:
                        st.button("🔍 Ver Obras", on_click=filtrar_levantador_governanca, args=(lev_nome,), key=f"btn_ver_{lev_nome}")

        st.markdown("### 📊 Estatísticas e Distribuição da Carga Geral")
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            fig_rosca_mun = px.pie(municipios_por_levantador, names='Levantador', values='Qtd_Municipios', 
                                   title="Quantidade Total de Municípios por Levantador",
                                   hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
            st.plotly_chart(fig_rosca_mun, use_container_width=True)
            
        with col_g2:
            df_sem_levantador = df_notas_calc[df_notas_calc['LEVANTADOR'] == 'SEM LEVANTADOR']
            df_sem_lev_reg = df_sem_levantador['REGIONAL'].value_counts().reset_index()
            df_sem_lev_reg.columns = ['Regional', 'Quantidade_Sem_Atribuicao']
            fig_rosca_sem_lev = px.pie(df_sem_lev_reg, names='Regional', values='Quantidade_Sem_Atribuicao',
                                       title="Obras Sem Levantador Atribuído por Regional",
                                       hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_rosca_sem_lev, use_container_width=True)

        # NOVO GRÁFICO: SLA POR REGIONAL
        st.markdown("---")
        st.markdown("### ⏳ Acompanhamento de Prazos (SLA) por Regional")
        
        df_sla = df_notas_calc.groupby(['REGIONAL', 'Status SLA']).size().reset_index(name='Quantidade')
        if not df_sla.empty:
            cores_sla = {
                "No Prazo": "#5CB85C",
                "Vencimento Próximo": "#F0AD4E",
                "Vencida": "#D9534F",
                "Sem Data": "#999999"
            }
            fig_sla = px.bar(
                df_sla, 
                x='REGIONAL', 
                y='Quantidade', 
                color='Status SLA',
                color_discrete_map=cores_sla,
                barmode='stack',
                text='Quantidade'
            )
            fig_sla.update_traces(textposition='inside', textfont_color='white')
            fig_sla.update_layout(yaxis_title="Quantidade de Obras", xaxis_title="Regional")
            st.plotly_chart(fig_sla, use_container_width=True)
        else:
            st.info("Não há dados suficientes para gerar o gráfico de SLA.")

        st.markdown("---")
        st.markdown("### 🗺️ Mapa de Distribuição Geográfica (Com Visão de Satélite)")
        
        def construir_mapa(df_eq, df_nt, criticos_tuple):
            mapa = folium.Map(location=[-5.2, -45.0], zoom_start=7)
            
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri', name='Visão de Satélite', overlay=False, control=True
            ).add_to(mapa)
            folium.TileLayer('OpenStreetMap', name='Mapa Padrão', overlay=False, control=True).add_to(mapa)
            
            fg_equipes = folium.FeatureGroup(name="📍 Bases dos Levantadores")
            fg_obras = folium.FeatureGroup(name="🏗️ Demandas Ativas (Clusters)")
            cluster_obras = MarkerCluster(name="Obras Agrupadas", disableClusteringAtZoom=13).add_to(fg_obras)
            
            records_equipes = df_eq.drop_duplicates(subset=['Município', 'Levantador']).to_dict('records')
            for row in records_equipes:
                if pd.notna(row['Latitude']) and pd.notna(row['Longitude']):
                    lev = str(row['Levantador'])
                    if lev in todos_levantadores:
                        cor_pino = 'red' if lev in criticos_tuple else 'green'
                        folium.Marker(
                            location=[float(row['Latitude']), float(row['Longitude'])],
                            icon=folium.Icon(color=cor_pino, icon='user', prefix='fa'),
                            tooltip=f"Levantador: {lev}"
                        ).add_to(fg_equipes)

            df_notas_mapa = df_nt.dropna(subset=['Latitude', 'Longitude']).copy()
            if not df_notas_mapa.empty:
                df_notas_mapa['lat_jitter'] = df_notas_mapa['Latitude'].astype(float) + np.random.normal(0, 0.004, len(df_notas_mapa))
                df_notas_mapa['lon_jitter'] = df_notas_mapa['Longitude'].astype(float) + np.random.normal(0, 0.004, len(df_notas_mapa))
                
                records_obras = df_notas_mapa.to_dict('records')
                for row in records_obras:
                    html_mini_card = f"""
                    <div style="font-family: Arial, sans-serif; font-size: 11px; width: 260px; line-height: 1.4; color: #222;">
                        <div style="background-color: #1A4F7C; color: white; padding: 5px; font-weight: bold; border-radius: 4px 4px 0 0; text-align: center;">INFORMAÇÕES DA OBRA</div>
                        <div style="padding: 7px; border: 1px solid #1A4F7C; border-top: none; background-color: #FFF; border-radius: 0 0 4px 4px;">
                            <b>PROTOCOLO:</b> {row.get('PROTOCOLO', '')}<br>
                            <b>MUNICIPIO:</b> {row.get('MUNICIPIO', '')}<br>
                            <b>LEVANTADOR:</b> {row.get('LEVANTADOR', '')}<br>
                        </div>
                    </div>
                    """
                    lev_obra = str(row['LEVANTADOR'])
                    cor_marcador = 'orange' if lev_obra == 'SEM LEVANTADOR' else ('red' if lev_obra in criticos_tuple else 'blue')
                    
                    folium.Marker(
                        location=[row['lat_jitter'], row['lon_jitter']], 
                        icon=folium.Icon(color=cor_marcador, icon='wrench', prefix='fa'),
                        popup=folium.Popup(html_mini_card, max_width=310)
                    ).add_to(cluster_obras)

            fg_equipes.add_to(mapa)
            fg_obras.add_to(mapa)
            folium.LayerControl().add_to(mapa)
            
            return mapa

        mapa_pronto = construir_mapa(df_equipes_db, df_notas_calc, tuple(levantadores_criticos))
        st_folium(mapa_pronto, use_container_width=True, height=550, returned_objects=[])

# --- VISÃO 2: FILTROS E GOVERNANÇA ---
elif menu_selecionado == 'Busca e Governança':
    st.markdown("### 📝 Filtros e Governança Direta da Base")
    
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    
    op_lev = ["TODOS"] + sorted([str(x) for x in df_notas_db['LEVANTADOR'].dropna().unique()])
    idx_lev = op_lev.index(st.session_state.filtros_salvos['lev']) if st.session_state.filtros_salvos['lev'] in op_lev else 0
    with col_f1:
        filtro_lev = st.selectbox("Filtrar por Levantador:", op_lev, index=idx_lev)
        st.session_state.filtros_salvos['lev'] = filtro_lev

    op_reg = ["TODOS"] + sorted([str(x) for x in df_notas_db['REGIONAL'].dropna().unique()])
    idx_reg = op_reg.index(st.session_state.filtros_salvos['reg']) if st.session_state.filtros_salvos['reg'] in op_reg else 0
    with col_f2:
        filtro_reg = st.selectbox("Filtrar por Regional:", op_reg, index=idx_reg)
        st.session_state.filtros_salvos['reg'] = filtro_reg

    op_mun = ["TODOS"] + sorted([str(x) for x in df_notas_db['MUNICIPIO'].dropna().unique()])
    idx_mun = op_mun.index(st.session_state.filtros_salvos['mun']) if st.session_state.filtros_salvos['mun'] in op_mun else 0
    with col_f3:
        filtro_mun = st.selectbox("Filtrar por Município:", op_mun, index=idx_mun)
        st.session_state.filtros_salvos['mun'] = filtro_mun

    op_lig = ["TODOS"] + sorted([str(x) for x in df_notas_db['TIPO LIGACAO'].dropna().astype(str).unique()])
    idx_lig = op_lig.index(st.session_state.filtros_salvos['lig']) if st.session_state.filtros_salvos['lig'] in op_lig else 0
    with col_f4:
        filtro_lig = st.selectbox("Filtrar por Tipo Ligação:", op_lig, index=idx_lig)
        st.session_state.filtros_salvos['lig'] = filtro_lig

    col_f5, col_f6 = st.columns(2)
    
    op_sap = ["TODOS"] + sorted([str(x) for x in df_notas_db['STATUS SAP'].dropna().unique()])
    idx_sap = op_sap.index(st.session_state.filtros_salvos['sap']) if st.session_state.filtros_salvos['sap'] in op_sap else 0
    with col_f5:
        filtro_sap = st.selectbox("Filtrar por Status SAP:", op_sap, index=idx_sap)
        st.session_state.filtros_salvos['sap'] = filtro_sap

    op_list = sorted([str(x) for x in df_notas_db['STATUS LIST'].dropna().unique() if str(x).strip() != ""])
    default_list = [x for x in st.session_state.filtros_salvos['list'] if x in op_list]
    with col_f6:
        filtro_list = st.multiselect("Filtrar por Status List (Vazio = TODOS):", options=op_list, default=default_list)
        st.session_state.filtros_salvos['list'] = filtro_list

    df_filtrado = df_notas_db.copy()
    if st.session_state.filtros_salvos['lev'] != "TODOS": df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'] == st.session_state.filtros_salvos['lev']]
    if st.session_state.filtros_salvos['reg'] != "TODOS": df_filtrado = df_filtrado[df_filtrado['REGIONAL'] == st.session_state.filtros_salvos['reg']]
    if st.session_state.filtros_salvos['mun'] != "TODOS": df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'] == st.session_state.filtros_salvos['mun']]
    if st.session_state.filtros_salvos['lig'] != "TODOS": df_filtrado = df_filtrado[df_filtrado['TIPO LIGACAO'].astype(str) == st.session_state.filtros_salvos['lig']]
    if st.session_state.filtros_salvos['sap'] != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS SAP'] == st.session_state.filtros_salvos['sap']]
    if len(st.session_state.filtros_salvos['list']) > 0: 
        df_filtrado = df_filtrado[df_filtrado['STATUS LIST'].isin(st.session_state.filtros_salvos['list'])]

    st.info(f"Obras localizadas sob os filtros aplicados: {len(df_filtrado)} registro(s).")
    
    if len(df_filtrado) > 0:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_filtrado.to_excel(writer, index=False, sheet_name='Filtrado')
        st.download_button(
            label="📥 Exportar Dados Filtrados para Excel", 
            data=buffer.getvalue(),
            file_name="relatorio_nip_filtrado.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    st.markdown("---")
    st.markdown("### 📊 Gestão e Edição em Lote")
    st.caption("Altere as células (incluindo DATA DE VENCIMENTO) diretamente na tabela abaixo e clique em Salvar Alterações.")
    
    df_editado = st.data_editor(
        df_filtrado, 
        use_container_width=True, 
        num_rows="dynamic",
        key="editor_notas"
    )

    col_btn1, col_btn2 = st.columns([8, 2])
    with col_btn1:
        if st.button("💾 Salvar Alterações na Base", type="primary"):
            indices_originais = df_editado.index
            df_notas_db.loc[indices_originais] = df_editado
            if save_notas_to_db(df_notas_db):
                st.success("Banco de Dados Atualizado com Sucesso!")
                st.rerun()
                
    with col_btn2:
        with st.expander("⚠️ ÁREA DE PERIGO"):
            confirmacao_global = st.checkbox("Confirmo que desejo apagar TODAS as notas.")
            if st.button("🚨 APAGAR TUDO", type="primary", disabled=not confirmacao_global):
                df_empty = pd.DataFrame(columns=df_notas_db.columns)
                if save_notas_to_db(df_empty):
                    st.success("Banco de dados de obras totalmente limpo!")
                    st.rerun()

# --- VISÃO 3: CARGA DE LOTES ---
elif menu_selecionado == 'Carga de Lotes':
    st.markdown("### 📤 Módulo de Importação de Lotes com Validação Strict")
    st.caption("Arraste o arquivo original. O sistema recusará dados corrompidos ou fora do padrão estabelecido.")
    
    schema_nip = pa.DataFrameSchema({
        "ID SISCO": pa.Column(pa.String, coerce=True, required=True),
        "STATUS SAP": pa.Column(pa.String, coerce=True, required=True),
        "PROTOCOLO": pa.Column(pa.String, coerce=True, required=True),
        "REGIONAL": pa.Column(pa.String, coerce=True, required=True),
        "MUNICIPIO": pa.Column(pa.String, coerce=True, required=True),
        "TIPO LIGACAO": pa.Column(pa.String, coerce=True, required=True)
    }, strict=False)

    arquivo_upload = st.file_uploader("Selecione o arquivo de demandas", type=["csv", "xlsx"])
    
    if arquivo_upload is not None:
        try:
            df_novos_dados = pd.read_csv(arquivo_upload) if arquivo_upload.name.endswith('.csv') else pd.read_excel(arquivo_upload)
            
            try:
                df_validado = schema_nip.validate(df_novos_dados)
                st.success("✅ Layout e Tipagem Homologados pelo Contrato de Dados!")
                
                df_validado['MUNICIPIO'] = df_validado['MUNICIPIO'].astype(str).str.upper().str.strip()
                if 'LEVANTADOR' not in df_validado.columns:
                    df_validado['LEVANTADOR'] = 'SEM LEVANTADOR'
                    
                df_temp_processado = auto_assign_levantador(df_validado, df_equipes_db)
                
                if st.button("⚡ Confirmar Importação e Gravar no Banco de Dados SQLite"):
                    df_final = pd.concat([df_notas_db, df_temp_processado], ignore_index=True)
                    if save_notas_to_db(df_final):
                        st.success(f"Sucesso! {len(df_temp_processado)} novas demandas injetadas no banco de dados.")
                        st.rerun()
                        
            except pa.errors.SchemaError as exc:
                st.error("🚨 Erro Crítico na Estrutura do Lote! A importação foi bloqueada.")
                st.markdown(f"**Detalhe da falha:** O dado na coluna `{exc.schema.name}` não respeita o contrato estabelecido. Esperado: `{exc.schema.dtype}`.")
                st.dataframe(exc.data, use_container_width=True)
                
        except Exception as e:
            st.error(f"Erro inesperado de leitura do arquivo físico: {e}")

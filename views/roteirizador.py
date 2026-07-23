import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import io
import zipfile
import html
import re
from openpyxl.styles import Font

from database import load_core_data

# Injeção de CSS
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }
    .stSelectbox label, .stFileUploader label, .stRadio label, .stNumberInput label, .stMultiSelect label { font-size: 14px !important; font-weight: 600 !important; color: #1A4F7C !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# FUNÇÕES MATEMÁTICAS, LIMPEZA E ROTEIRIZAÇÃO
# ==========================================
def normalize_cols(cols):
    """Remove acentos, espaços extras e padroniza as colunas em maiúsculas para evitar KeyErrors."""
    new_cols = []
    for c in cols:
        c = str(c).strip().upper()
        c = re.sub(r'[ÁÀÂÃÄ]', 'A', c)
        c = re.sub(r'[ÉÈÊË]', 'E', c)
        c = re.sub(r'[ÍÌÎÏ]', 'I', c)
        c = re.sub(r'[ÓÒÔÕÖ]', 'O', c)
        c = re.sub(r'[ÚÙÛÜ]', 'U', c)
        c = re.sub(r'Ç', 'C', c)
        new_cols.append(c)
    return new_cols

def haversine_vectorized(lat1, lon1, lat2, lon2):
    R = 6371.0 # Raio da Terra em km
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def normalizar_municipios(series_mun):
    s = series_mun.astype(str).str.upper()
    s = s.str.replace(r'[ÁÀÂÃÄ]', 'A', regex=True)
    s = s.str.replace(r'[ÉÈÊË]', 'E', regex=True)
    s = s.str.replace(r'[ÍÌÎÏ]', 'I', regex=True)
    s = s.str.replace(r'[ÓÒÔÕÖ]', 'O', regex=True)
    s = s.str.replace(r'[ÚÙÛÜ]', 'U', regex=True)
    s = s.str.replace(r'Ç', 'C', regex=True)
    return s.str.split('-').str[0].str.strip()

def gerar_kml_rota(df_rota, base_nome, base_lat, base_lon, dia, semana, cols_exibir):
    kml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>ROTA_{base_nome}_SEMANA_{semana}_DIA_{dia}</name>
    <Style id="linha-rota">
      <LineStyle><color>ffcf2802</color><width>4</width></LineStyle>
    </Style>
    <Style id="icon-blue-normal">
      <IconStyle><color>ffd18802</color><scale>1</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
      <LabelStyle><scale>0</scale></LabelStyle>
    </Style>
    <Style id="icon-blue-highlight">
      <IconStyle><color>ffd18802</color><scale>1</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
      <LabelStyle><scale>1</scale></LabelStyle>
    </Style>
    <StyleMap id="icon-blue">
      <Pair><key>normal</key><styleUrl>#icon-blue-normal</styleUrl></Pair>
      <Pair><key>highlight</key><styleUrl>#icon-blue-highlight</styleUrl></Pair>
    </StyleMap>
    <Style id="icon-red-normal">
      <IconStyle><color>ff0000ff</color><scale>1</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
      <LabelStyle><scale>0</scale></LabelStyle>
    </Style>
    <Style id="icon-red-highlight">
      <IconStyle><color>ff0000ff</color><scale>1.2</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
      <LabelStyle><scale>1</scale></LabelStyle>
    </Style>
    <StyleMap id="icon-red">
      <Pair><key>normal</key><styleUrl>#icon-red-normal</styleUrl></Pair>
      <Pair><key>highlight</key><styleUrl>#icon-red-highlight</styleUrl></Pair>
    </StyleMap>
'''
    kml_str += f'''    <Placemark>
      <name>BASE: {html.escape(str(base_nome))}</name>
      <styleUrl>#icon-blue</styleUrl>
      <Point><coordinates>{base_lon},{base_lat},0</coordinates></Point>
    </Placemark>\n'''

    coords_linha = f"{base_lon},{base_lat},0\n"

    for _, row in df_rota.iterrows():
        lon, lat = str(row['LONGITUDE']).replace(',','.'), str(row['LATITUDE']).replace(',','.')
        coords_linha += f"          {lon},{lat},0\n"
        
        desc_parts = [f"<b>Ordem:</b> {row['ORDEM']}"]
        ext_data_parts = []
        for col in cols_exibir:
            if col in row:
                val = html.escape(str(row[col]))
                desc_parts.append(f"<b>{col}:</b> {val}")
                ext_data_parts.append(f'<Data name="{col}">\n          <value>{val}</value>\n        </Data>')
                
        desc_cdata = "<br>".join(desc_parts)
        ext_data_str = "\n        ".join(ext_data_parts)
        nome_ponto = f"{row['ORDEM']} - {html.escape(str(row.get('NOME DO SOLICITANTE', 'OBRA')))}"
        
        style_url = "#icon-red" if row.get('PRIORIDADE') == "Sim" else "#icon-blue"
        
        kml_str += f'''    <Placemark>
      <name>{nome_ponto}</name>
      <description><![CDATA[{desc_cdata}]]></description>
      <styleUrl>{style_url}</styleUrl>
      <ExtendedData>
        {ext_data_str}
      </ExtendedData>
      <Point><coordinates>{lon},{lat},0</coordinates></Point>
    </Placemark>\n'''

    kml_str += f'''    <Placemark>
      <name>Caminho do Roteiro</name>
      <styleUrl>#linha-rota</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>\n{coords_linha}        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>'''
    return kml_str

# ==========================================
# VIEW PRINCIPAL
# ==========================================
def view_roteirizador():
    st.markdown("## 🚙 Roteirizador Operacional Avançado")
    st.markdown("Planeje rotas inteligentes, filtre erros do sistema e aloque equipes por território geográfico.")

    _, df_equipes_db, _, _, _, _, _, _ = load_core_data()
    
    # Prepara a base de equipes do sistema (Se disponível)
    lista_levantadores = []
    if not df_equipes_db.empty:
        df_equipes_db.columns = normalize_cols(df_equipes_db.columns)
        if 'LATITUDE' in df_equipes_db.columns and 'LONGITUDE' in df_equipes_db.columns:
            df_equipes_db['LATITUDE'] = pd.to_numeric(df_equipes_db['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
            df_equipes_db['LONGITUDE'] = pd.to_numeric(df_equipes_db['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'LEVANTADOR' in df_equipes_db.columns:
            lista_levantadores = sorted([str(x) for x in df_equipes_db['LEVANTADOR'].dropna().unique().tolist()])

    # --- BARRA LATERAL ---
    with st.sidebar:
        st.markdown("### ⚙️ Metas Operacionais")
        obras_por_dia = st.number_input("Mínimo de Obras por Dia", min_value=5, value=10, step=1)
        obras_por_semana = st.number_input("Mínimo de Obras por Semana", min_value=50, value=50, step=5)
        
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        st.markdown("### 👥 Gestão de Equipes")
        
        origem_bases = st.radio("Fonte dos Levantadores", ["Banco de Dados", "Upload Planilha Levantadores_MA"])
        df_bases = pd.DataFrame()

        if origem_bases == "Banco de Dados":
            levs_selecionados = st.multiselect("Selecione os Levantadores para Roteirizar:", lista_levantadores)
            if levs_selecionados:
                df_bases = df_equipes_db[df_equipes_db['LEVANTADOR'].isin(levs_selecionados)].copy()
                df_bases = df_bases.dropna(subset=['LATITUDE', 'LONGITUDE'])
                st.success(f"{len(df_bases['LEVANTADOR'].unique())} equipe(s) ativada(s).")
        else:
            base_file = st.file_uploader("Upload Planilha Levantadores_MA", type=["xlsx", "xls"])
            if base_file:
                try:
                    df_bases_temp = pd.read_excel(base_file)
                    df_bases_temp.columns = normalize_cols(df_bases_temp.columns)
                    
                    # Inteligência para encontrar a coluna de Levantador caso venha com nome diferente
                    if 'LEVANTADOR' not in df_bases_temp.columns:
                        for possivel_nome in ['NOME', 'TECNICO', 'EQUIPE', 'COLABORADOR']:
                            if possivel_nome in df_bases_temp.columns:
                                df_bases_temp = df_bases_temp.rename(columns={possivel_nome: 'LEVANTADOR'})
                                break
                                
                    if 'LEVANTADOR' not in df_bases_temp.columns:
                        st.error("❌ A planilha anexada não possui uma coluna chamada 'LEVANTADOR', 'NOME' ou 'TECNICO'.")
                    else:
                        opcoes_levs = sorted([str(x) for x in df_bases_temp['LEVANTADOR'].dropna().unique().tolist() if str(x).upper().strip() != 'SEM LEVANTADOR'])
                        levs_selecionados = st.multiselect("Selecione as Equipes:", opcoes_levs)
                        
                        if levs_selecionados:
                            df_bases = df_bases_temp[df_bases_temp['LEVANTADOR'].isin(levs_selecionados)].copy()
                            
                            # Verifica se tem Latitude e Longitude na planilha enviada. Se não tiver, puxa do DB.
                            if 'LATITUDE' not in df_bases.columns or 'LONGITUDE' not in df_bases.columns:
                                if not df_equipes_db.empty and 'LATITUDE' in df_equipes_db.columns:
                                    df_bases = df_bases.merge(df_equipes_db[['LEVANTADOR', 'LATITUDE', 'LONGITUDE']], on='LEVANTADOR', how='left')
                                    st.info("ℹ️ Coordenadas importadas do Banco de Dados pois a planilha enviada não possuía.")
                                else:
                                    st.error("❌ A planilha não possui colunas LATITUDE e LONGITUDE.")
                                    df_bases = pd.DataFrame()
                except Exception as e:
                    st.error(f"Erro ao ler a planilha de Levantadores: {e}")

        st.markdown("### 📍 Regra de Atribuição")
        tipo_atribuicao = st.radio(
            "Como dividir as obras?", 
            [
                "Por Distância da Residência", 
                "Por Municípios Atendidos", 
                "Balancear Geograficamente (Mesma Região)"
            ],
            help="Distância = Joga pra quem mora mais perto. Municípios = Respeita a matriz territorial da planilha. Balanceado = Reparte as obras igualmente por distância entre os selecionados."
        )

    # --- ÁREA PRINCIPAL ---
    st.markdown("### 📁 Upload dos Arquivos de Demanda")
    task_files = st.file_uploader("Selecione os arquivos Excel contendo as Obras a serem roteirizadas", type=["xlsx", "xls"], accept_multiple_files=True)
    
    if not task_files:
        st.info("👆 Por favor, envie os arquivos de demanda (obras) na caixa acima para começar a configuração.")
        return

    try:
        dfs = []
        for f in task_files:
            df_temp = pd.read_excel(f)
            df_temp.columns = normalize_cols(df_temp.columns)
            dfs.append(df_temp)
        df_tasks = pd.concat(dfs, ignore_index=True)
    except Exception as e:
        st.error(f"Erro ao unificar as planilhas: {e}")
        return

    if 'LATITUDE' not in df_tasks.columns or 'LONGITUDE' not in df_tasks.columns:
        st.error("❌ Os arquivos enviados não possuem as colunas obrigatórias 'LATITUDE' e 'LONGITUDE'.")
        return

    # --- FILTRO ANTI-LIXO E ANTI-ERRO ---
    st.markdown("### 🧹 Limpeza Automática do Sistema")
    total_original = len(df_tasks)
    
    df_tasks['LATITUDE'] = pd.to_numeric(df_tasks['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
    df_tasks['LONGITUDE'] = pd.to_numeric(df_tasks['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
    
    df_tasks = df_tasks.dropna(subset=['LATITUDE', 'LONGITUDE'])
    df_tasks = df_tasks[(df_tasks['LATITUDE'] != 0.0) & (df_tasks['LONGITUDE'] != 0.0)]
    
    if 'NOME DO SOLICITANTE' in df_tasks.columns:
        df_tasks = df_tasks.dropna(subset=['NOME DO SOLICITANTE'])
        df_tasks = df_tasks[df_tasks['NOME DO SOLICITANTE'].astype(str).str.strip() != '']
        
    if 'STATUS SAP' in df_tasks.columns:
        df_tasks = df_tasks[~df_tasks['STATUS SAP'].astype(str).str.strip().str.upper().isin(['CANC', 'FINL'])]

    total_validos = len(df_tasks)
    removidos = total_original - total_validos
    
    if removidos > 0:
        st.warning(f"⚠️ O sistema bloqueou automaticamente **{removidos} obras** com erros (Sem GPS, Status CANC/FINL ou Sem Nome). Restam **{total_validos}** válidas.")
    else:
        st.success(f"✅ Base de dados 100% íntegra. ({total_validos} obras lidas).")

    if df_tasks.empty:
        st.error("❌ Nenhuma obra passou pelos filtros de qualidade. Verifique as planilhas.")
        return

    # --- CONFIGURAÇÃO DE EXIBIÇÃO E PRIORIDADE ---
    with st.expander("🛠️ Configuração de Exibição e Prioridade", expanded=True):
        c1, c2 = st.columns(2)
        todas_colunas = df_tasks.columns.tolist()
        cols_padrao = [c for c in ['PROTOCOLO', 'NOME DO SOLICITANTE', 'MUNICIPIO', 'TIPO LIGACAO'] if c in todas_colunas]
        
        colunas_exibir = c1.multiselect("Colunas para Exibir (Pop-ups e KML)", todas_colunas, default=cols_padrao)
        
        col_prioridade = c2.selectbox("Coluna de Prioridade (Opcional)", ["Nenhuma"] + todas_colunas)
        valores_prioridade = []
        if col_prioridade != "Nenhuma":
            vals_unicos = df_tasks[col_prioridade].dropna().unique().tolist()
            valores_prioridade = c2.multiselect(f"Quais valores em '{col_prioridade}' significam URGÊNCIA?", vals_unicos)

    # --- EXECUÇÃO ---
    if st.button("🚀 Iniciar Motor de Roteirização", type="primary", use_container_width=True):
        if df_bases.empty:
            st.error("❌ Selecione ao menos 1 Levantador na barra lateral para gerar rotas.")
            return

        with st.spinner("Processando Inteligência de Terreno e Roteirização Neural..."):
            bases_records = df_bases.to_dict('records')
            
            # --- ATRIBUIÇÃO MÚLTIPLA DE LEVANTADORES ---
            df_tasks['BASE_ATRIBUIDA'] = "NÃO ALOCADO"
            
            if tipo_atribuicao == "Por Distância da Residência":
                def get_nearest_base(lat, lon):
                    min_dist = float('inf')
                    best_base = None
                    for b in bases_records:
                        b_lat, b_lon = b.get('LATITUDE'), b.get('LONGITUDE')
                        if pd.notna(b_lat) and pd.notna(b_lon):
                            d = haversine_vectorized(lat, lon, float(str(b_lat).replace(',','.')), float(str(b_lon).replace(',','.')))
                            if d < min_dist:
                                min_dist, best_base = d, b['LEVANTADOR']
                    return best_base
                df_tasks['BASE_ATRIBUIDA'] = df_tasks.apply(lambda r: get_nearest_base(r['LATITUDE'], r['LONGITUDE']), axis=1)

            elif tipo_atribuicao == "Por Municípios Atendidos":
                if 'MUNICIPIO' not in df_tasks.columns or 'MUNICIPIO' not in df_bases.columns:
                    st.error("A coluna 'MUNICIPIO' precisa existir nas Obras e na base de Levantadores para este modo funcionar.")
                    return
                
                mun_to_lev = {}
                for b in bases_records:
                    muns_atendidos = str(b.get('MUNICIPIO', '')).split(',')
                    for m in muns_atendidos:
                        m_limpo = normalizar_municipios(pd.Series([m])).iloc[0]
                        if m_limpo: mun_to_lev[m_limpo] = b['LEVANTADOR']
                        
                df_tasks['MUN_LIMPO'] = normalizar_municipios(df_tasks['MUNICIPIO'])
                df_tasks['BASE_ATRIBUIDA'] = df_tasks['MUN_LIMPO'].map(mun_to_lev).fillna("NÃO ALOCADO")
                df_tasks = df_tasks.drop(columns=['MUN_LIMPO'])

            elif tipo_atribuicao == "Balancear Geograficamente (Mesma Região)":
                lev_names = list(set([b['LEVANTADOR'] for b in bases_records]))
                n_lev = len(lev_names)
                df_tasks = df_tasks.sort_values(by=['LATITUDE', 'LONGITUDE']).reset_index(drop=True)
                chunks = np.array_split(df_tasks.index, n_lev)
                for i, chunk in enumerate(chunks):
                    df_tasks.loc[chunk, 'BASE_ATRIBUIDA'] = lev_names[i]

            # Filtra obras que não conseguiram alocação
            df_unallocated = df_tasks[df_tasks['BASE_ATRIBUIDA'] == "NÃO ALOCADO"]
            df_tasks = df_tasks[df_tasks['BASE_ATRIBUIDA'] != "NÃO ALOCADO"].copy()

            if df_tasks.empty:
                st.error("Nenhuma obra pôde ser alocada aos levantadores escolhidos. Verifique a correspondência de municípios ou distâncias.")
                return

            # --- ROTEIRIZAÇÃO (CAIXEIRO VIAJANTE GULOSO) ---
            routed_data = []
            levantadores_unicos = list(set([b['LEVANTADOR'] for b in bases_records]))
            
            for b_name in levantadores_unicos:
                base_rows = df_bases[df_bases['LEVANTADOR'] == b_name]
                if base_rows.empty: continue
                
                base_ref = base_rows.iloc[0] # Pega a primeira latitude válida como ponto de partida
                if pd.isna(base_ref.get('LATITUDE')) or pd.isna(base_ref.get('LONGITUDE')):
                    continue
                
                b_lat = float(str(base_ref['LATITUDE']).replace(',','.'))
                b_lon = float(str(base_ref['LONGITUDE']).replace(',','.'))
                
                df_b = df_tasks[df_tasks['BASE_ATRIBUIDA'] == b_name].copy()
                if df_b.empty: continue
                
                curr_lat, curr_lon = b_lat, b_lon
                unvisited = df_b.copy()
                ordem_absoluta = 1
                
                while not unvisited.empty:
                    dists = haversine_vectorized(curr_lat, curr_lon, unvisited['LATITUDE'].values, unvisited['LONGITUDE'].values)
                    nearest_idx = unvisited.index[dists.argmin()]
                    nearest_row = unvisited.loc[nearest_idx]
                    
                    row_dict = nearest_row.to_dict()
                    row_dict['ORDEM'] = ordem_absoluta
                    
                    idx_global = ordem_absoluta - 1
                    semana = (idx_global // obras_por_semana) + 1
                    obra_na_semana = idx_global % obras_por_semana
                    dia = (obra_na_semana // obras_por_dia) + 1
                    
                    row_dict['SEMANA'] = semana
                    row_dict['DIA'] = dia
                    row_dict['DISTANCIA_KM'] = round(dists.min(), 2)
                    
                    # Checagem de Prioridade
                    is_prio = "Não"
                    if col_prioridade != "Nenhuma" and row_dict.get(col_prioridade) in valores_prioridade:
                        is_prio = "Sim"
                    row_dict['PRIORIDADE'] = is_prio
                    
                    routed_data.append(row_dict)
                    
                    curr_lat, curr_lon = nearest_row['LATITUDE'], nearest_row['LONGITUDE']
                    unvisited = unvisited.drop(nearest_idx)
                    ordem_absoluta += 1

            if len(routed_data) == 0:
                st.error("Falha no roteamento. Nenhuma base possuía coordenadas válidas como ponto de partida.")
                return

            df_routed = pd.DataFrame(routed_data)

            # --- RESULTADOS E KPIS ---
            st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("📌 Obras Roteirizadas", len(df_routed))
            k2.metric("👥 Técnicos em Campo", df_routed['BASE_ATRIBUIDA'].nunique())
            k3.metric("📅 Total de Dias Utilizados", df_routed.groupby('BASE_ATRIBUIDA')['DIA'].max().sum())
            k4.metric("🚨 Obras Prioritárias", len(df_routed[df_routed['PRIORIDADE'] == 'Sim']) if 'PRIORIDADE' in df_routed else 0)

            if not df_unallocated.empty:
                st.warning(f"⚠️ {len(df_unallocated)} obras não encontraram cobertura e ficaram sem Rota.")

            # --- MAPA FOLIUM ---
            st.markdown("#### 🗺️ Visualização Geográfica do Plano")
            mapa = folium.Map(location=[df_routed['LATITUDE'].mean(), df_routed['LONGITUDE'].mean()], zoom_start=8)
            cores = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'darkblue']
            
            for idx, base_nome in enumerate(df_routed['BASE_ATRIBUIDA'].unique()):
                cor_rota = cores[idx % len(cores)]
                df_base_rota = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome]
                
                base_rows = df_bases[df_bases['LEVANTADOR'] == base_nome]
                if base_rows.empty: continue
                base_ref = base_rows.iloc[0]
                b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))
                
                folium.Marker([b_lat, b_lon], icon=folium.Icon(color='black', icon='home', prefix='fa'), tooltip=f"Partida/Base: {base_nome}").add_to(mapa)
                
                for semana in df_base_rota['SEMANA'].unique():
                    for dia in df_base_rota[df_base_rota['SEMANA'] == semana]['DIA'].unique():
                        df_dia = df_base_rota[(df_base_rota['SEMANA'] == semana) & (df_base_rota['DIA'] == dia)]
                        fg = folium.FeatureGroup(name=f"{base_nome} | Sem {semana} | Dia {dia}")
                        
                        pontos_linha = [(b_lat, b_lon)] + list(zip(df_dia['LATITUDE'], df_dia['LONGITUDE']))
                        folium.PolyLine(pontos_linha, color=cor_rota, weight=3, opacity=0.7).add_to(fg)
                        
                        for _, r in df_dia.iterrows():
                            icone = 'star' if r['PRIORIDADE'] == "Sim" else 'info-sign'
                            cor_icone = 'red' if r['PRIORIDADE'] == "Sim" else cor_rota
                            
                            info_html = f"<b>Ordem:</b> {r['ORDEM']} | <b>Semana:</b> {r['SEMANA']} | <b>Dia:</b> {r['DIA']}<br>"
                            for c in colunas_exibir:
                                if c in r: info_html += f"<b>{c}:</b> {r[c]}<br>"
                                
                            folium.Marker(
                                [r['LATITUDE'], r['LONGITUDE']], 
                                icon=folium.Icon(color=cor_icone, icon=icone),
                                popup=folium.Popup(info_html, max_width=300)
                            ).add_to(fg)
                        fg.add_to(mapa)
            
            folium.LayerControl().add_to(mapa)
            st_folium(mapa, use_container_width=True, height=500, returned_objects=[])

            # --- EXPORTAÇÕES (EXCEL E KML) ---
            st.markdown("#### 📥 Exportar Resultados Finais")
            col_b1, col_b2, col_b3 = st.columns(3)

            # Excel com Formatação Vermelho Negrito
            buf_xl = io.BytesIO()
            with pd.ExcelWriter(buf_xl, engine='openpyxl') as writer:
                df_routed.to_excel(writer, index=False, sheet_name='Roteiro')
                ws = writer.sheets['Roteiro']
                
                red_font = Font(color="FF0000", bold=True)
                prio_flag_idx = df_routed.columns.get_loc('PRIORIDADE') + 1 
                
                if col_prioridade != "Nenhuma" and col_prioridade in df_routed.columns:
                    prio_col_idx = df_routed.columns.get_loc(col_prioridade) + 1
                    
                    for row_idx in range(2, len(df_routed) + 2):
                        if ws.cell(row=row_idx, column=prio_flag_idx).value == "Sim":
                            ws.cell(row=row_idx, column=prio_col_idx).font = red_font
                            ws.cell(row=row_idx, column=prio_flag_idx).font = red_font
            
            col_b1.download_button("📥 Baixar Planilha Oficial (Excel)", data=buf_xl.getvalue(), file_name="roteiro_operacional.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

            csv_data = df_routed.to_csv(index=False, sep=';').encode('utf-8-sig')
            col_b2.download_button("📥 Baixar Planilha em CSV", data=csv_data, file_name="roteiro_operacional.csv", mime="text/csv", use_container_width=True)

            # Arquivos KML Zippados (Divididos por Base, Semana e Dia)
            buf_zip = io.BytesIO()
            with zipfile.ZipFile(buf_zip, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for base_nome in df_routed['BASE_ATRIBUIDA'].unique():
                    base_rows = df_bases[df_bases['LEVANTADOR'] == base_nome]
                    if base_rows.empty: continue
                    base_ref = base_rows.iloc[0]
                    b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))
                    
                    df_base = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome]
                    for semana in df_base['SEMANA'].unique():
                        for dia in df_base[df_base['SEMANA'] == semana]['DIA'].unique():
                            df_dia = df_base[(df_base['SEMANA'] == semana) & (df_base['DIA'] == dia)]
                            kml_str = gerar_kml_rota(df_dia, base_nome, b_lat, b_lon, dia, semana, colunas_exibir)
                            # Remove espaços e traços estranhos do nome do arquivo
                            nome_arquivo_seguro = re.sub(r'[^A-Za-z0-9_]', '', base_nome.replace(" ", "_"))
                            zip_file.writestr(f"ROTA_{nome_arquivo_seguro}_SEM_{semana}_DIA_{dia}.kml", kml_str.encode('utf-8'))
            
            col_b3.download_button("🗺️ Baixar Todas as Rotas (KML ZIP)", data=buf_zip.getvalue(), file_name="rotas_kml.zip", mime="application/zip", use_container_width=True)

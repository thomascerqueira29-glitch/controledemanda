import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import io
import zipfile
import html
import re
import os
import requests
import time
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
# FUNÇÕES DE ESTADO E LIMPEZA
# ==========================================
if "roteamento_concluido" not in st.session_state:
    st.session_state.roteamento_concluido = False

def limpar_roteirizador():
    chaves_para_limpar = ['roteamento_concluido', 'df_routed', 'bases_records', 'tipo_periodo', 'colunas_exibir', 'col_prioridade']
    for key in chaves_para_limpar:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

def normalize_cols(cols):
    """Padroniza as colunas em maiúsculas e remove acentos."""
    new_cols = []
    for c in cols:
        c = str(c).strip().upper()
        c = re.sub(r'[ÁÀÂÃÄ]', 'A', regex=True)
        c = re.sub(r'[ÉÈÊË]', 'E', regex=True)
        c = re.sub(r'[ÍÌÎÏ]', 'I', regex=True)
        c = re.sub(r'[ÓÒÔÕÖ]', 'O', regex=True)
        c = re.sub(r'[ÚÙÛÜ]', 'U', regex=True)
        c = re.sub(r'Ç', 'C', regex=True)
        new_cols.append(c)
    return new_cols

def normalizar_municipios(series_mun):
    s = series_mun.astype(str).str.upper()
    s = s.str.replace(r'[ÁÀÂÃÄ]', 'A', regex=True)
    s = s.str.replace(r'[ÉÈÊË]', 'E', regex=True)
    s = s.str.replace(r'[ÍÌÎÏ]', 'I', regex=True)
    s = s.str.replace(r'[ÓÒÔÕÖ]', 'O', regex=True)
    s = s.str.replace(r'[ÚÙÛÜ]', 'U', regex=True)
    s = s.str.replace(r'Ç', 'C', regex=True)
    return s.str.split('-').str[0].str.strip()

# ==========================================
# FUNÇÕES MATEMÁTICAS E DE ROTEIRIZAÇÃO OSRM
# ==========================================
def haversine_vectorized(lat1, lon1, lat2, lon2):
    R = 6371.0 
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def obter_rota_ruas(lat1, lon1, lat2, lon2):
    """Busca a rota geométrica seguindo o arruamento (via API OSRM). Se falhar, retorna reta."""
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            data = r.json()
            if data['code'] == 'Ok':
                return data['routes'][0]['geometry']['coordinates'] 
    except Exception:
        pass
    return [[lon1, lat1], [lon2, lat2]] 

# ==========================================
# GERAÇÃO DE ARQUIVOS (EXCEL E KML ESTRUTURADO)
# ==========================================
def gerar_excel_bytes(df, col_prioridade):
    """Gera o arquivo Excel em bytes pintando os dados de prioridade."""
    buf_xl = io.BytesIO()
    with pd.ExcelWriter(buf_xl, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Roteiro')
        ws = writer.sheets['Roteiro']
        red_font = Font(color="FF0000", bold=True)
        if 'PRIORIDADE' in df.columns:
            prio_flag_idx = df.columns.get_loc('PRIORIDADE') + 1 
            if col_prioridade != "Nenhuma" and col_prioridade in df.columns:
                prio_col_idx = df.columns.get_loc(col_prioridade) + 1
                for row_idx in range(2, len(df) + 2):
                    if ws.cell(row=row_idx, column=prio_flag_idx).value == "Sim":
                        ws.cell(row=row_idx, column=prio_col_idx).font = red_font
                        ws.cell(row=row_idx, column=prio_flag_idx).font = red_font
    return buf_xl.getvalue()

def gerar_kml_agrupado(df_rota, bases_records, doc_name, cols_exibir):
    """Gera um arquivo KML com a estrutura de Pastas (Folders) e RÓTULOS (Labels) ativados."""
    # LabelStyle scale=0.8 deixa o texto (Nome/Protocolo) sempre visível em cima do pino
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{doc_name}</name>
  <Style id="linha-rota"><LineStyle><color>ffcf2802</color><width>4</width></LineStyle></Style>
  
  <Style id="icon-blue-normal">
    <IconStyle><color>ffd18802</color><scale>1</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
    <LabelStyle><scale>0.8</scale></LabelStyle>
  </Style>
  <Style id="icon-blue-highlight">
    <IconStyle><color>ffd18802</color><scale>1.2</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
    <LabelStyle><scale>1.0</scale></LabelStyle>
  </Style>
  <StyleMap id="icon-blue"><Pair><key>normal</key><styleUrl>#icon-blue-normal</styleUrl></Pair><Pair><key>highlight</key><styleUrl>#icon-blue-highlight</styleUrl></Pair></StyleMap>
  
  <Style id="icon-red-normal">
    <IconStyle><color>ff0000ff</color><scale>1</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
    <LabelStyle><scale>0.8</scale></LabelStyle>
  </Style>
  <Style id="icon-red-highlight">
    <IconStyle><color>ff0000ff</color><scale>1.3</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
    <LabelStyle><scale>1.0</scale></LabelStyle>
  </Style>
  <StyleMap id="icon-red"><Pair><key>normal</key><styleUrl>#icon-red-normal</styleUrl></Pair><Pair><key>highlight</key><styleUrl>#icon-red-highlight</styleUrl></Pair></StyleMap>
'''

    for base_nome in df_rota['BASE_ATRIBUIDA'].unique():
        df_base = df_rota[df_rota['BASE_ATRIBUIDA'] == base_nome]
        base_ref = next((b for b in bases_records if b['LEVANTADOR'] == base_nome), None)
        b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))

        kml += f'  <Folder>\n    <name>Levantador: {html.escape(str(base_nome))}</name>\n'
        kml += f'''    <Placemark>
      <name>BASE: {html.escape(str(base_nome))}</name>
      <styleUrl>#icon-blue</styleUrl>
      <Point><coordinates>{b_lon},{b_lat},0</coordinates></Point>
    </Placemark>\n'''

        for semana in df_base['SEMANA'].unique():
            df_semana = df_base[df_base['SEMANA'] == semana]
            kml += f'    <Folder>\n      <name>Semana {semana}</name>\n'

            for dia in df_semana['DIA'].unique():
                df_dia = df_semana[df_semana['DIA'] == dia]
                kml += f'      <Folder>\n        <name>Dia {dia}</name>\n'

                coords_linha_kml = ""
                for _, row in df_dia.iterrows():
                    lon, lat = str(row['LONGITUDE']).replace(',','.'), str(row['LATITUDE']).replace(',','.')

                    desc_parts = [f"<b>Ordem na Rota:</b> {row['ORDEM']}"]
                    desc_parts.append(f"<b>Distância do Ponto Anterior:</b> {row['DISTANCIA_PONTO_ANTERIOR_KM']} KM")
                    ext_data_parts = []
                    for col in cols_exibir:
                        if col in row:
                            val = html.escape(str(row[col]))
                            desc_parts.append(f"<b>{col}:</b> {val}")
                            ext_data_parts.append(f'<Data name="{col}"><value>{val}</value></Data>')

                    desc_cdata = "<br>".join(desc_parts)
                    ext_data_str = "\n            ".join(ext_data_parts)
                    
                    # NOME DO PONTO AGORA INCLUI A ORDEM E O PROTOCOLO
                    protocolo_str = html.escape(str(row.get('PROTOCOLO', 'Sem Protocolo')))
                    nome_ponto = f"[{row['ORDEM']}] Prot: {protocolo_str}"
                    
                    style_url = "#icon-red" if row.get('PRIORIDADE') == "Sim" else "#icon-blue"

                    kml += f'''        <Placemark>
          <name>{nome_ponto}</name>
          <description><![CDATA[{desc_cdata}]]></description>
          <styleUrl>{style_url}</styleUrl>
          <ExtendedData>
            {ext_data_str}
          </ExtendedData>
          <Point><coordinates>{lon},{lat},0</coordinates></Point>
        </Placemark>\n'''
                    
                    if isinstance(row.get('ROTA_GEOMETRIA'), list):
                        for pt_lon, pt_lat in row['ROTA_GEOMETRIA']:
                            coords_linha_kml += f"          {pt_lon},{pt_lat},0\n"
                    else:
                        coords_linha_kml += f"          {lon},{lat},0\n"

                kml += f'''        <Placemark>
          <name>Traçado do Roteiro (Arruamento)</name>
          <styleUrl>#linha-rota</styleUrl>
          <LineString>
            <tessellate>1</tessellate>
            <coordinates>\n{coords_linha_kml}            </coordinates>
          </LineString>
        </Placemark>\n'''
                kml += '      </Folder>\n' 
            kml += '    </Folder>\n' 
        kml += '  </Folder>\n' 
    kml += '</Document>\n</kml>'
    return kml

# ==========================================
# VIEW PRINCIPAL DA PÁGINA
# ==========================================
def view_roteirizador():
    
    # -------------------------------------------------------------
    # TELA DE RESULTADOS (Mostrada apenas quando o cálculo termina)
    # -------------------------------------------------------------
    if st.session_state.roteamento_concluido:
        st.markdown("## 🎯 Resultados da Roteirização")
        
        df_routed = st.session_state.df_routed
        bases_records = st.session_state.bases_records
        tipo_periodo = st.session_state.tipo_periodo
        colunas_exibir = st.session_state.colunas_exibir
        col_prioridade = st.session_state.col_prioridade
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("📌 Obras Roteirizadas", len(df_routed))
        k2.metric("👥 Equipes em Campo", df_routed['BASE_ATRIBUIDA'].nunique())
        k3.metric(f"📅 Total de {tipo_periodo}s Utilizados", df_routed.groupby('BASE_ATRIBUIDA')['PERIODO'].max().sum() if not df_routed.empty else 0)
        k4.metric("🚨 Obras Prioritárias", len(df_routed[df_routed['PRIORIDADE'] == 'Sim']) if 'PRIORIDADE' in df_routed else 0)

        # --- MAPA FOLIUM (Reconstruído a partir do State) ---
        st.markdown("#### 🗺️ Visualização Geográfica do Plano")
        mapa = folium.Map(location=[df_routed['LATITUDE'].mean(), df_routed['LONGITUDE'].mean()], zoom_start=8) if not df_routed.empty else folium.Map(location=[-5.2, -45.0], zoom_start=7)
        cores = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'darkblue']
        
        for idx, base_nome in enumerate(df_routed['BASE_ATRIBUIDA'].unique()):
            cor_rota = cores[idx % len(cores)]
            df_base_rota = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome]
            
            base_ref = next((b for b in bases_records if b['LEVANTADOR'] == base_nome), None)
            b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))
            folium.Marker([b_lat, b_lon], icon=folium.Icon(color='black', icon='home', prefix='fa'), tooltip=f"Base: {base_nome}").add_to(mapa)
            
            for periodo_val in df_base_rota['PERIODO'].unique():
                df_periodo = df_base_rota[df_base_rota['PERIODO'] == periodo_val]
                fg = folium.FeatureGroup(name=f"{base_nome} | {tipo_periodo} {periodo_val}")
                
                pontos_linha_folium = []
                for _, r in df_periodo.iterrows():
                    if isinstance(r.get('ROTA_GEOMETRIA'), list):
                        for lon, lat in r['ROTA_GEOMETRIA']:
                            pontos_linha_folium.append([lat, lon]) 
                            
                folium.PolyLine(pontos_linha_folium, color=cor_rota, weight=3, opacity=0.8).add_to(fg)
                
                for _, r in df_periodo.iterrows():
                    icone = 'star' if r['PRIORIDADE'] == "Sim" else 'info-sign'
                    cor_icone = 'red' if r['PRIORIDADE'] == "Sim" else cor_rota
                    
                    info_html = f"<b>Ordem:</b> {r['ORDEM']} | <b>{tipo_periodo}:</b> {r['PERIODO']}<br><b>Distância Ponto Anterior:</b> {r['DISTANCIA_PONTO_ANTERIOR_KM']} KM<br>"
                    for c in colunas_exibir:
                        if c in r: info_html += f"<b>{c}:</b> {r[c]}<br>"
                        
                    folium.Marker(
                        [r['LATITUDE'], r['LONGITUDE']], 
                        icon=folium.Icon(color=cor_icone, icon=icone),
                        popup=folium.Popup(info_html, max_width=300)
                    ).add_to(fg)
                fg.add_to(mapa)
        
        folium.LayerControl().add_to(mapa)
        st_folium(mapa, use_container_width=True, height=550, returned_objects=[])

        # --- EXPORTAÇÕES (Geração Blindada) ---
        st.markdown("#### 📥 Baixar Resultados")
        
        # 1. Empacota todas as planilhas Excel
        buf_zip_xl = io.BytesIO()
        with zipfile.ZipFile(buf_zip_xl, 'w', zipfile.ZIP_DEFLATED) as zip_xl:
            zip_xl.writestr("Roteiro_Geral.xlsx", gerar_excel_bytes(df_routed, col_prioridade))
            planilhas_geradas = ["Roteiro_Geral.xlsx"]
            for base_nome in df_routed['BASE_ATRIBUIDA'].unique():
                df_lev = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome].copy()
                nome_seguro = re.sub(r'[^A-Za-z0-9_]', '', str(base_nome).replace(" ", "_"))
                if not df_lev.empty:
                    nome_arquivo = f"Roteiro_{nome_seguro}.xlsx"
                    zip_xl.writestr(nome_arquivo, gerar_excel_bytes(df_lev, col_prioridade))
                    planilhas_geradas.append(nome_arquivo)
        zip_xl_bytes = buf_zip_xl.getvalue()

        # 2. Empacota todos os Mapas KML
        buf_zip_kml = io.BytesIO()
        with zipfile.ZipFile(buf_zip_kml, 'w', zipfile.ZIP_DEFLATED) as zip_kml:
            kml_geral = gerar_kml_agrupado(df_routed, bases_records, "Rota_Geral_Completa", colunas_exibir)
            zip_kml.writestr("Rota_Geral.kml", kml_geral.encode('utf-8'))
            mapas_gerados = ["Rota_Geral.kml"]
            for base_nome in df_routed['BASE_ATRIBUIDA'].unique():
                df_lev = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome].copy()
                nome_seguro = re.sub(r'[^A-Za-z0-9_]', '', str(base_nome).replace(" ", "_"))
                if not df_lev.empty:
                    nome_arquivo = f"Rota_{nome_seguro}.kml"
                    kml_lev = gerar_kml_agrupado(df_lev, bases_records, f"Rota_{nome_seguro}", colunas_exibir)
                    zip_kml.writestr(nome_arquivo, kml_lev.encode('utf-8'))
                    mapas_gerados.append(nome_arquivo)
        zip_kml_bytes = buf_zip_kml.getvalue()

        # Mostra pro usuário o que tem dentro do ZIP para dar segurança
        with st.expander("📄 Ver lista de arquivos gerados (Conteúdo dos ZIPs)"):
            st.markdown("**Planilhas Excel:** " + ", ".join(planilhas_geradas))
            st.markdown("**Mapas KML:** " + ", ".join(mapas_gerados))

        # Botões de Download Nativos (Navegador)
        col_b1, col_b2, col_b3 = st.columns([1, 1, 1])
        col_b1.download_button("🌐 1. Baixar Planilhas (ZIP Excel)", data=zip_xl_bytes, file_name="Planilhas_Roteiro.zip", mime="application/zip", use_container_width=True)
        col_b2.download_button("🗺️ 2. Baixar Mapas (KML ZIP)", data=zip_kml_bytes, file_name="Mapas_KML.zip", mime="application/zip", use_container_width=True)
        if col_b3.button("🧹 Zerar Roteirizador", type="primary", use_container_width=True):
            limpar_roteirizador()

        # Botões de Salvamento Direto no PC
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("#### 💻 Salvar Diretamente em uma Pasta do seu PC")
        caminho_padrao = os.path.join(os.path.expanduser("~"), "Downloads")
        caminho_exportacao = st.text_input("Digite o caminho da pasta onde deseja salvar:", value=caminho_padrao)
        
        if st.button("💾 Salvar Arquivos na Pasta Indicada"):
            try:
                if not os.path.exists(caminho_exportacao):
                    os.makedirs(caminho_exportacao)
                
                with open(os.path.join(caminho_exportacao, "Planilhas_Roteiro.zip"), "wb") as f:
                    f.write(zip_xl_bytes)
                with open(os.path.join(caminho_exportacao, "Mapas_KML.zip"), "wb") as f:
                    f.write(zip_kml_bytes)
                    
                st.success(f"✅ Sucesso! Os pacotes de planilhas e mapas foram salvos em: `{caminho_exportacao}`")
            except Exception as e:
                st.error(f"Erro ao tentar salvar no computador: {e} (Verifique se o sistema tem permissão de escrita nessa pasta).")
        
        return 


    # -------------------------------------------------------------
    # TELA DE CONFIGURAÇÃO INICIAL (Se roteamento não concluído)
    # -------------------------------------------------------------
    st.markdown("## 🚙 Roteirizador Operacional Avançado")
    st.markdown("Planeje rotas inteligentes seguindo o traçado das ruas e limite o volume de trabalho por período.")

    # --- BARRA LATERAL (APENAS DIA/SEMANA) ---
    with st.sidebar:
        st.markdown("### ⚙️ Período de Roteirização")
        tipo_periodo = st.radio("Como você quer agrupar o roteiro?", ["Dia", "Semana"], help="Selecione apenas uma opção.")
        
        if tipo_periodo == "Dia":
            obras_por_periodo = st.number_input("Obras por Dia (Mín. 5)", min_value=5, value=10, step=1)
            limite_periodos = st.number_input("Quantos dias de roteirização?", min_value=1, value=5, step=1, help="Limite máximo de dias que o técnico vai rodar.")
        else:
            obras_por_periodo = st.number_input("Obras por Semana (Mín. 50)", min_value=50, value=50, step=5)
            limite_periodos = st.number_input("Quantas semanas de roteirização?", min_value=1, value=4, step=1, help="Limite máximo de semanas que o técnico vai rodar.")

    # --- ÁREA CENTRAL (UPLOAD E EQUIPES JUNTOS) ---
    col_up_1, col_up_2 = st.columns(2)

    with col_up_1:
        st.markdown("### 👥 1. Gestão de Equipes (Bases)")
        origem_bases = st.radio("Fonte dos Levantadores", ["Banco de Dados do Sistema", "Upload Planilha Levantadores_MA"])
        df_bases = pd.DataFrame()

        if origem_bases == "Banco de Dados do Sistema":
            _, df_equipes_db, _, _, _, _, _, _ = load_core_data()
            if not df_equipes_db.empty:
                df_equipes_db.columns = normalize_cols(df_equipes_db.columns)
                df_equipes_db['LATITUDE'] = pd.to_numeric(df_equipes_db.get('LATITUDE', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce')
                df_equipes_db['LONGITUDE'] = pd.to_numeric(df_equipes_db.get('LONGITUDE', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce')
                lista_lev = sorted([str(x) for x in df_equipes_db['LEVANTADOR'].dropna().unique().tolist()])
                
                levs_selecionados = st.multiselect("Selecione as Equipes que irão a campo:", lista_lev)
                if levs_selecionados:
                    df_bases = df_equipes_db[df_equipes_db['LEVANTADOR'].isin(levs_selecionados)].copy()
                    df_bases = df_bases.dropna(subset=['LATITUDE', 'LONGITUDE'])
        else:
            base_file = st.file_uploader("Suba a planilha Levantadores_MA", type=["xlsx", "xls"])
            if base_file:
                try:
                    df_bases_temp = pd.read_excel(base_file)
                    df_bases_temp.columns = normalize_cols(df_bases_temp.columns)
                    if 'LEVANTADOR' not in df_bases_temp.columns:
                        for p_nome in ['NOME', 'TECNICO', 'EQUIPE', 'COLABORADOR']:
                            if p_nome in df_bases_temp.columns:
                                df_bases_temp = df_bases_temp.rename(columns={p_nome: 'LEVANTADOR'})
                                break
                    if 'LEVANTADOR' in df_bases_temp.columns:
                        opcoes_levs = sorted([str(x) for x in df_bases_temp['LEVANTADOR'].dropna().unique().tolist() if str(x).upper().strip() != 'SEM LEVANTADOR'])
                        levs_selecionados = st.multiselect("Selecione as Equipes:", opcoes_levs)
                        if levs_selecionados:
                            df_bases = df_bases_temp[df_bases_temp['LEVANTADOR'].isin(levs_selecionados)].copy()
                except Exception as e:
                    st.error(f"Erro ao ler a planilha: {e}")

        st.markdown("##### Regra de Atribuição (Divisão de Obras)")
        tipo_atribuicao = st.radio(
            "Regra", 
            ["Por Distância da Residência", "Por Municípios Atendidos", "Balancear Geograficamente (Mesma Região)"],
            label_visibility="collapsed"
        )

    with col_up_2:
        st.markdown("### 📁 2. Upload de Demandas (Obras)")
        task_files = st.file_uploader("Selecione a(s) planilha(s) de Obras", type=["xlsx", "xls"], accept_multiple_files=True)
        
        if not task_files:
            st.info("Aguardando upload para habilitar a configuração.")
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

    # --- FILTRO ANTI-LIXO ---
    if 'LATITUDE' not in df_tasks.columns or 'LONGITUDE' not in df_tasks.columns:
        st.error("❌ A planilha de Obras precisa ter LATITUDE e LONGITUDE.")
        return

    st.markdown("---")
    st.markdown("### 🧹 Limpeza Automática do Sistema")
    total_orig = len(df_tasks)
    
    df_tasks['LATITUDE'] = pd.to_numeric(df_tasks['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
    df_tasks['LONGITUDE'] = pd.to_numeric(df_tasks['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
    df_tasks = df_tasks.dropna(subset=['LATITUDE', 'LONGITUDE'])
    df_tasks = df_tasks[(df_tasks['LATITUDE'] != 0.0) & (df_tasks['LONGITUDE'] != 0.0)]
    
    if 'NOME DO SOLICITANTE' in df_tasks.columns:
        df_tasks = df_tasks.dropna(subset=['NOME DO SOLICITANTE'])
        df_tasks = df_tasks[df_tasks['NOME DO SOLICITANTE'].astype(str).str.strip() != '']
    if 'STATUS SAP' in df_tasks.columns:
        df_tasks = df_tasks[~df_tasks['STATUS SAP'].astype(str).str.strip().str.upper().isin(['CANC', 'FINL'])]

    if total_orig - len(df_tasks) > 0:
        st.warning(f"⚠️ {total_orig - len(df_tasks)} obras com erros sistêmicos (GPS Vazio, Status Morto) foram ignoradas. Restam **{len(df_tasks)} válidas.**")

    if df_tasks.empty: return

    # --- EXIBIÇÃO E PRIORIDADE ---
    with st.expander("🛠️ 3. Configuração de Exibição e Prioridade no KML", expanded=True):
        c_ex1, c_ex2 = st.columns(2)
        todas_cols = df_tasks.columns.tolist()
        cols_padrao = [c for c in ['PROTOCOLO', 'NOME DO SOLICITANTE', 'MUNICIPIO', 'TIPO LIGACAO'] if c in todas_cols]
        colunas_exibir = c_ex1.multiselect("Colunas para aparecer no Balão do KML", todas_cols, default=cols_padrao)
        
        col_prioridade = c_ex2.selectbox("Coluna que define a URGÊNCIA (Vai ficar Vermelho)", ["Nenhuma"] + todas_cols)
        valores_prioridade = []
        if col_prioridade != "Nenhuma":
            valores_prioridade = c_ex2.multiselect("Quais valores indicam Urgência?", df_tasks[col_prioridade].dropna().unique().tolist())

    # --- MOTOR DE EXECUÇÃO ---
    if st.button("🚀 Iniciar Motor de Roteirização (Pode levar alguns minutos)", type="primary", use_container_width=True):
        if df_bases.empty:
            st.error("Selecione ao menos 1 Levantador válido.")
            return

        progresso_texto = st.empty()
        barra_progresso = st.progress(0)
        tempo_restante_texto = st.empty()
        
        start_time = time.time()
        api_calls = 0
        
        bases_records = df_bases.to_dict('records')
        df_tasks['BASE_ATRIBUIDA'] = "NÃO ALOCADO"
        
        progresso_texto.text("📍 Calculando matriz de atribuição territorial...")
        if tipo_atribuicao == "Por Distância da Residência":
            def get_nearest_base(lat, lon):
                min_dist = float('inf')
                best_base = None
                for b in bases_records:
                    if pd.notna(b.get('LATITUDE')):
                        d = haversine_vectorized(lat, lon, float(b['LATITUDE']), float(b['LONGITUDE']))
                        if d < min_dist: min_dist, best_base = d, b['LEVANTADOR']
                return best_base
            df_tasks['BASE_ATRIBUIDA'] = df_tasks.apply(lambda r: get_nearest_base(r['LATITUDE'], r['LONGITUDE']), axis=1)

        elif tipo_atribuicao == "Por Municípios Atendidos":
            mun_to_lev = {}
            for b in bases_records:
                for m in str(b.get('MUNICIPIO', '')).split(','):
                    m_limpo = normalizar_municipios(pd.Series([m])).iloc[0]
                    if m_limpo: mun_to_lev[m_limpo] = b['LEVANTADOR']
            df_tasks['MUN_LIMPO'] = normalizar_municipios(df_tasks['MUNICIPIO'])
            df_tasks['BASE_ATRIBUIDA'] = df_tasks['MUN_LIMPO'].map(mun_to_lev).fillna("NÃO ALOCADO")
            df_tasks = df_tasks.drop(columns=['MUN_LIMPO'])

        elif tipo_atribuicao == "Balancear Geograficamente (Mesma Região)":
            lev_names = list(set([b['LEVANTADOR'] for b in bases_records]))
            df_tasks = df_tasks.sort_values(by=['LATITUDE', 'LONGITUDE']).reset_index(drop=True)
            chunks = np.array_split(df_tasks.index, len(lev_names))
            for i, chunk in enumerate(chunks):
                df_tasks.loc[chunk, 'BASE_ATRIBUIDA'] = lev_names[i]

        df_unallocated = df_tasks[df_tasks['BASE_ATRIBUIDA'] == "NÃO ALOCADO"]
        df_tasks = df_tasks[df_tasks['BASE_ATRIBUIDA'] != "NÃO ALOCADO"].copy()
        
        if df_tasks.empty:
            st.error("Falha: Nenhuma obra encontrada no território das equipes selecionadas.")
            return

        if not df_unallocated.empty:
            st.warning(f"⚠️ {len(df_unallocated)} obras ficaram sem rota pois não correspondem à matriz de municípios ou proximidade escolhida.")

        routed_data = []
        levantadores_unicos = list(set([b['LEVANTADOR'] for b in bases_records]))
        total_obras_alocadas = len(df_tasks)
        obras_processadas = 0
        obras_sobra_total = 0

        for b_name in levantadores_unicos:
            base_ref = df_bases[df_bases['LEVANTADOR'] == b_name].iloc[0]
            if pd.isna(base_ref.get('LATITUDE')): continue
            
            curr_lat, curr_lon = float(base_ref['LATITUDE']), float(base_ref['LONGITUDE'])
            unvisited = df_tasks[df_tasks['BASE_ATRIBUIDA'] == b_name].copy()
            ordem_absoluta = 1
            
            while not unvisited.empty:
                dists = haversine_vectorized(curr_lat, curr_lon, unvisited['LATITUDE'].values, unvisited['LONGITUDE'].values)
                nearest_idx = unvisited.index[dists.argmin()]
                nearest_row = unvisited.loc[nearest_idx]
                dist_km = round(dists.min(), 2)
                
                idx_global = ordem_absoluta - 1
                periodo_atual = (idx_global // obras_por_periodo) + 1
                
                if periodo_atual > limite_periodos:
                    obras_sobra_total += len(unvisited)
                    obras_processadas += len(unvisited)
                    barra_progresso.progress(min(obras_processadas / total_obras_alocadas, 1.0))
                    break
                
                progresso_texto.text(f"🗺️ Desenhando rota para {b_name} (Obra {ordem_absoluta})... Consultando Satélite.")
                rota_geom = obter_rota_ruas(curr_lat, curr_lon, nearest_row['LATITUDE'], nearest_row['LONGITUDE'])
                
                row_dict = nearest_row.to_dict()
                row_dict['ORDEM'] = ordem_absoluta
                row_dict['SEMANA'] = periodo_atual if tipo_periodo == "Semana" else 1
                row_dict['DIA'] = (idx_global % obras_por_periodo) + 1 if tipo_periodo == "Dia" else 1
                row_dict['PERIODO'] = row_dict['DIA'] if tipo_periodo == "Dia" else row_dict['SEMANA']
                row_dict['DISTANCIA_PONTO_ANTERIOR_KM'] = dist_km
                row_dict['ROTA_GEOMETRIA'] = rota_geom
                
                is_prio = "Sim" if col_prioridade != "Nenhuma" and row_dict.get(col_prioridade) in valores_prioridade else "Não"
                row_dict['PRIORIDADE'] = is_prio
                
                routed_data.append(row_dict)
                curr_lat, curr_lon = nearest_row['LATITUDE'], nearest_row['LONGITUDE']
                unvisited = unvisited.drop(nearest_idx)
                ordem_absoluta += 1
                
                obras_processadas += 1
                api_calls += 1
                barra_progresso.progress(min(obras_processadas / total_obras_alocadas, 1.0))
                
                elapsed = time.time() - start_time
                avg_time = elapsed / api_calls
                obras_restantes = total_obras_alocadas - obras_processadas
                
                if obras_restantes > 0:
                    est_rem = avg_time * obras_restantes
                    m, s = divmod(int(est_rem), 60)
                    h, m = divmod(m, 60)
                    if h > 0:
                        tempo_restante_texto.markdown(f"⏳ **Tempo estimado restante:** {h:02d}h {m:02d}m {s:02d}s")
                    else:
                        tempo_restante_texto.markdown(f"⏳ **Tempo estimado restante:** {m:02d}m {s:02d}s")
                else:
                    tempo_restante_texto.markdown("✅ **Processamento Concluído! Montando arquivos...**")
                
                time.sleep(0.1) 

        if obras_sobra_total > 0:
            st.warning(f"⏳ {obras_sobra_total} obras ficaram de fora do roteiro porque excederam o limite de {limite_periodos} {tipo_periodo.lower()}(s) definido.")

        st.session_state.df_routed = pd.DataFrame(routed_data)
        st.session_state.bases_records = bases_records
        st.session_state.tipo_periodo = tipo_periodo
        st.session_state.colunas_exibir = colunas_exibir
        st.session_state.col_prioridade = col_prioridade
        st.session_state.roteamento_concluido = True
        
        st.rerun()

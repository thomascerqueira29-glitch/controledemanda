import streamlit as st
import pandas as pd
import numpy as np
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import io
import zipfile
import html
import re
import requests
import time
from datetime import datetime
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
# FUNÇÕES DE LIMPEZA E FORMATAÇÃO
# ==========================================
def limpar_roteirizador():
    st.session_state.roteamento_concluido = False
    st.session_state.df_routed = pd.DataFrame()
    st.session_state.bases_records = []
    st.session_state.tipo_periodo = "Dia"
    st.session_state.colunas_exibir = []
    st.session_state.col_prioridade = "Nenhuma"
    st.session_state.colunas_originais = []
    st.rerun()

def normalize_cols(cols):
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

@st.cache_data(show_spinner=False)
def obter_coordenadas_municipio_cached(municipio):
    if not municipio or pd.isna(municipio) or str(municipio).strip() == "":
        return np.nan, np.nan
    try:
        time.sleep(1.2)
        mun_str = str(municipio).strip()
        url = f"https://nominatim.openstreetmap.org/search?q={mun_str},+Maranhão,+Brasil&format=json&limit=1"
        headers = {"User-Agent": "GeradorRotasOperacional/4.5"}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if len(data) > 0:
                return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass
    return np.nan, np.nan

def obter_rota_ruas(lat1, lon1, lat2, lon2):
    try:
        headers = {"User-Agent": "GeradorRotasOperacional/4.5"}
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=full&geometries=geojson"
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data['code'] == 'Ok':
                return data['routes'][0]['geometry']['coordinates'] 
    except Exception:
        pass
    return [[lon1, lat1], [lon2, lat2]] 

def identificar_icone_folium(row, colunas):
    tipo_str = ""
    if 'TIPO LIGACAO' in colunas:
        tipo_str = str(row.get('TIPO LIGACAO', '')).upper()
    elif 'SERVICO' in colunas:
        tipo_str = str(row.get('SERVICO', '')).upper()
    elif 'TIPO NOTA' in colunas:
        tipo_str = str(row.get('TIPO NOTA', '')).upper()
        
    if 'NOVA' in tipo_str or 'LIGACAO' in tipo_str or 'UNI' in tipo_str or 'UNR' in tipo_str: return 'bolt'
    if 'MANUT' in tipo_str or 'REPARO' in tipo_str: return 'wrench'
    if 'INSP' in tipo_str or 'VISTORIA' in tipo_str: return 'eye-open'
    if row.get('PROTOCOLO') == 'RETORNO_BASE': return 'home'
    if row.get('PROTOCOLO') == 'PAUSA_ALMOCO': return 'cutlery'
    return 'info-sign'

# ==========================================
# GERAÇÃO DE ARQUIVOS (EXCEL E KML ESTRUTURADO)
# ==========================================
def gerar_excel_bytes(df, col_prioridade, colunas_originais=None):
    df_export = df.copy()
    
    if 'ROTA_GEOMETRIA' in df_export.columns:
        df_export = df_export.drop(columns=['ROTA_GEOMETRIA'])
        
    if colunas_originais:
        cols_atuais = df_export.columns.tolist()
        cols_novas_geradas = [c for c in cols_atuais if c not in colunas_originais]
        cols_finais_ordenadas = [c for c in colunas_originais if c in cols_atuais] + cols_novas_geradas
        df_export = df_export[cols_finais_ordenadas]

    buf_xl = io.BytesIO()
    with pd.ExcelWriter(buf_xl, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False, sheet_name='Roteiro')
        ws = writer.sheets['Roteiro']
        red_font = Font(color="FF0000", bold=True)
        if 'PRIORIDADE' in df_export.columns:
            prio_flag_idx = df_export.columns.get_loc('PRIORIDADE') + 1 
            for row_idx in range(2, len(df_export) + 2):
                if ws.cell(row=row_idx, column=prio_flag_idx).value == "Sim":
                    ws.cell(row=row_idx, column=prio_flag_idx).font = red_font
                    if col_prioridade != "Nenhuma" and col_prioridade in df_export.columns:
                        prio_col_idx = df_export.columns.get_loc(col_prioridade) + 1
                        ws.cell(row=row_idx, column=prio_col_idx).font = red_font
    return buf_xl.getvalue()

def gerar_kml_agrupado(df_rota, bases_records, doc_name, cols_exibir):
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{doc_name}</name>
  <Style id="linha-rota"><LineStyle><color>ffcf2802</color><width>4</width></LineStyle></Style>
  
  <Style id="icon-blue">
    <IconStyle><color>ffd18802</color><scale>1.1</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
    <LabelStyle><scale>0.9</scale></LabelStyle>
  </Style>
  <Style id="icon-red">
    <IconStyle><color>ff0000ff</color><scale>1.3</scale><Icon><href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
    <LabelStyle><scale>1.0</scale></LabelStyle>
  </Style>
  <Style id="icon-green">
    <IconStyle><color>ff00ff00</color><scale>1.2</scale><Icon><href>https://maps.google.com/mapfiles/kml/shapes/homegardenbusiness.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
  </Style>
  <Style id="icon-yellow">
    <IconStyle><color>ff00ffff</color><scale>1.3</scale><Icon><href>https://maps.google.com/mapfiles/kml/shapes/dining.png</href></Icon><hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/></IconStyle>
    <LabelStyle><scale>1.0</scale></LabelStyle>
  </Style>
'''

    for base_nome in df_rota['BASE_ATRIBUIDA'].unique():
        df_base = df_rota[df_rota['BASE_ATRIBUIDA'] == base_nome]
        base_ref = next((b for b in bases_records if b['LEVANTADOR'] == base_nome), None)
        b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))

        res_nome = str(base_ref.get('RESIDENCIA', base_nome))

        kml += f'  <Folder>\n    <name>Levantador: {html.escape(str(base_nome))}</name>\n'
        kml += f'''    <Placemark>
      <name>BASE: {html.escape(str(res_nome))}</name>
      <styleUrl>#icon-green</styleUrl>
      <Point><coordinates>{b_lon},{b_lat},0</coordinates></Point>
    </Placemark>\n'''

        for semana in df_base['SEMANA'].unique():
            df_semana = df_base[df_base['SEMANA'] == semana]
            kml += f'    <Folder>\n      <name>Semana {semana}</name>\n'

            for dia in df_semana['DIA'].unique():
                df_dia = df_semana[df_semana['DIA'] == dia].copy()
                df_dia = df_dia.sort_values(by='ORDEM')
                
                kml += f'      <Folder>\n        <name>Dia {dia}</name>\n'

                coords_linha_kml = ""
                for _, row in df_dia.iterrows():
                    lon, lat = str(row['LONGITUDE']).replace(',','.'), str(row['LATITUDE']).replace(',','.')

                    desc_parts = [f"<b>Ordem na Rota:</b> {row.get('ORDEM', 0)}"]
                    desc_parts.append(f"<b>Distância do Ponto Anterior:</b> {row.get('DISTANCIA_PONTO_ANTERIOR_KM', 0)} KM")
                    ext_data_parts = []
                    
                    if row.get('PROTOCOLO') == 'RETORNO_BASE':
                        desc_cdata = "<b>RETORNO À BASE DE ORIGEM</b>"
                        ext_data_str = ""
                        nome_ponto = "🏠 FIM DO DIA - RETORNO"
                        style_url = "#icon-green"
                    elif row.get('PROTOCOLO') == 'PAUSA_ALMOCO':
                        desc_cdata = "<b>PAUSA PROGRAMADA PARA REFEIÇÃO (1h)</b>"
                        ext_data_str = ""
                        nome_ponto = "🍔 ALMOÇO DA EQUIPE"
                        style_url = "#icon-yellow"
                    else:
                        for col in cols_exibir:
                            if col in row:
                                val = html.escape(str(row[col]))
                                desc_parts.append(f"<b>{col}:</b> {val}")
                                ext_data_parts.append(f'<Data name="{col}"><value>{val}</value></Data>')
                        desc_cdata = "<br>".join(desc_parts)
                        ext_data_str = "\n            ".join(ext_data_parts)
                        protocolo_str = html.escape(str(row.get('PROTOCOLO', 'Sem Protocolo')))
                        
                        tag_prio = "[PRIORIDADE] " if row.get('PRIORIDADE') == "Sim" else ""
                        nome_ponto = f"{tag_prio}[{row.get('ORDEM', 0)}] Prot: {protocolo_str}"
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
    if "roteamento_concluido" not in st.session_state:
        st.session_state.roteamento_concluido = False
    if "df_routed" not in st.session_state:
        st.session_state.df_routed = pd.DataFrame()
    if "bases_records" not in st.session_state:
        st.session_state.bases_records = []
    if "tipo_periodo" not in st.session_state:
        st.session_state.tipo_periodo = "Dia"
    if "colunas_exibir" not in st.session_state:
        st.session_state.colunas_exibir = []
    if "col_prioridade" not in st.session_state:
        st.session_state.col_prioridade = "Nenhuma"
    if "colunas_originais" not in st.session_state:
        st.session_state.colunas_originais = []

    # -------------------------------------------------------------
    # TELA DE RESULTADOS E EDIÇÃO (PÓS-ROTEIRIZAÇÃO)
    # -------------------------------------------------------------
    if st.session_state.roteamento_concluido and not st.session_state.df_routed.empty:
        st.markdown("## 🎯 Resultados da Roteirização Corporativa")
        
        # O data_editor permite edição em tempo real (Ajuste Fino)
        st.markdown("### ✍️ Ajuste Fino Manual (Painel do Despachante)")
        st.info("Dê um **duplo clique** nas células abaixo para alterar o responsável ou a ordem das obras. Suas edições sairão direto nos downloads finais.")
        
        df_editado_ui = st.data_editor(
            st.session_state.df_routed,
            use_container_width=True,
            column_config={
                "ROTA_GEOMETRIA": None, # Esconde o código geográfico gigante para não poluir a tela
                "LATITUDE": st.column_config.NumberColumn(disabled=True),
                "LONGITUDE": st.column_config.NumberColumn(disabled=True),
                "DISTANCIA_PONTO_ANTERIOR_KM": st.column_config.NumberColumn(disabled=True)
            }
        )
        
        # Atualiza a base para os downloads usando a versão editada pelo usuário
        df_routed = df_editado_ui.copy()
        
        bases_records = st.session_state.bases_records
        tipo_periodo = st.session_state.tipo_periodo
        colunas_exibir = st.session_state.colunas_exibir
        col_prioridade = st.session_state.col_prioridade
        colunas_originais = st.session_state.colunas_originais
        
        # Filtra registros não operacionais para métricas
        df_real_tasks = df_routed[~df_routed['PROTOCOLO'].isin(['RETORNO_BASE', 'PAUSA_ALMOCO'])]
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("📌 Obras Roteirizadas", len(df_real_tasks))
        k2.metric("👥 Equipes em Campo", df_routed['BASE_ATRIBUIDA'].nunique())
        k3.metric("🛣️ KM Total Projetado", f"{df_routed['DISTANCIA_PONTO_ANTERIOR_KM'].sum():.1f} km")
        k4.metric("🚨 Prioridades", len(df_real_tasks[df_real_tasks['PRIORIDADE'] == 'Sim']) if 'PRIORIDADE' in df_real_tasks else 0)

        # --- DASHBOARDS DE PRODUTIVIDADE NATIVOS ---
        st.markdown("---")
        st.markdown("### 📊 Dashboards de Produtividade")
        c_dash1, c_dash2 = st.columns(2)
        
        with c_dash1:
            st.markdown("##### 📦 Volume de Obras por Equipe")
            obras_por_equipe = df_real_tasks['BASE_ATRIBUIDA'].value_counts()
            st.bar_chart(obras_por_equipe, color="#1A4F7C")
            
        with c_dash2:
            st.markdown("##### 🛣️ Quilometragem Projetada por Equipe")
            km_por_equipe = df_routed.groupby('BASE_ATRIBUIDA')['DISTANCIA_PONTO_ANTERIOR_KM'].sum()
            st.bar_chart(km_por_equipe, color="#FF4B4B")
        st.markdown("---")

        st.markdown("#### 🗺️ Visualização Geográfica do Plano")
        mapa = folium.Map(location=[df_routed['LATITUDE'].mean(), df_routed['LONGITUDE'].mean()], zoom_start=8) if not df_routed.empty else folium.Map(location=[-5.2, -45.0], zoom_start=7)
        cores = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'darkblue']
        
        marker_cluster = MarkerCluster(name="Obras (Agrupadas)").add_to(mapa)
        
        for idx, base_nome in enumerate(df_routed['BASE_ATRIBUIDA'].unique()):
            cor_rota = cores[idx % len(cores)]
            df_base_rota = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome]
            
            base_ref = next((b for b in bases_records if b['LEVANTADOR'] == base_nome), None)
            b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))
            res_nome = str(base_ref.get('RESIDENCIA', base_nome))
            folium.Marker([b_lat, b_lon], icon=folium.Icon(color='black', icon='home', prefix='fa'), tooltip=f"Base: {res_nome}").add_to(mapa)
            
            for periodo_val in df_base_rota['PERIODO'].unique():
                df_periodo = df_base_rota[df_base_rota['PERIODO'] == periodo_val]
                fg_linhas = folium.FeatureGroup(name=f"Linhas {base_nome} | P: {periodo_val}", show=False)
                
                pontos_linha_folium = []
                for _, r in df_periodo.iterrows():
                    if isinstance(r.get('ROTA_GEOMETRIA'), list):
                        for lon, lat in r['ROTA_GEOMETRIA']:
                            pontos_linha_folium.append([lat, lon]) 
                            
                folium.PolyLine(pontos_linha_folium, color=cor_rota, weight=3, opacity=0.8).add_to(fg_linhas)
                fg_linhas.add_to(mapa)
                
                for _, r in df_periodo.iterrows():
                    if r['PROTOCOLO'] in ['RETORNO_BASE', 'PAUSA_ALMOCO']: continue
                    
                    icone = identificar_icone_folium(r, df_routed.columns)
                    cor_icone = 'red' if r.get('PRIORIDADE') == "Sim" else cor_rota
                    
                    info_html = f"<b>Ordem:</b> {r.get('ORDEM', 0)} | <b>{tipo_periodo}:</b> {r.get('PERIODO', 0)}<br><b>Distância Ponto Anterior:</b> {r.get('DISTANCIA_PONTO_ANTERIOR_KM', 0)} KM<br>"
                    for c in colunas_exibir:
                        if c in r: info_html += f"<b>{c}:</b> {r[c]}<br>"
                        
                    folium.Marker(
                        [r['LATITUDE'], r['LONGITUDE']], 
                        icon=folium.Icon(color=cor_icone, icon=icone),
                        popup=folium.Popup(info_html, max_width=300)
                    ).add_to(marker_cluster)
        
        folium.LayerControl().add_to(mapa)
        st_folium(mapa, use_container_width=True, height=550, returned_objects=[])

        st.markdown("#### 📥 Baixar Resultados e Integrações")
        
        data_atual = datetime.now().strftime("%d_%m_%Y")
        
        buf_zip_xl = io.BytesIO()
        with zipfile.ZipFile(buf_zip_xl, 'w', zipfile.ZIP_DEFLATED) as zip_xl:
            # 1. Roteiro Geral
            nome_roteiro_geral = f"Roteiro_Geral_{data_atual}.xlsx"
            zip_xl.writestr(nome_roteiro_geral, gerar_excel_bytes(df_routed, col_prioridade, colunas_originais))
            planilhas_geradas = [nome_roteiro_geral]
            
            # 2. Base Power BI
            nome_pbi = f"Base_Dashboards_PowerBI_{data_atual}.csv"
            cols_atuais_bi = df_routed.columns.tolist()
            cols_novas_bi = [c for c in cols_atuais_bi if c not in colunas_originais]
            cols_finais_bi = [c for c in colunas_originais if c in cols_atuais_bi] + cols_novas_bi
            csv_pbi = df_routed[cols_finais_bi].to_csv(index=False, sep=';', decimal=',', encoding='utf-8-sig')
            zip_xl.writestr(nome_pbi, csv_pbi)
            planilhas_geradas.append(nome_pbi)
            
            # 3. Layout SAP (Blindado: Remove Pausa Almoço e Retorno)
            sap_cols = [c for c in ['PROTOCOLO', 'ORDEM', 'BASE_ATRIBUIDA', 'TIPO LIGACAO', 'STATUS SAP'] if c in df_real_tasks.columns]
            if sap_cols:
                nome_sap = f"Layout_Importacao_SAP_{data_atual}.xlsx"
                df_sap = df_real_tasks[sap_cols].copy()
                df_sap['NOVO_STATUS_ATUALIZACAO'] = ''
                zip_xl.writestr(nome_sap, gerar_excel_bytes(df_sap, "Nenhuma"))
                planilhas_geradas.append(nome_sap)

            # 4. Relatório de Expectativa
            nome_resumo = f"Expectativa_{'Semanal' if tipo_periodo == 'Semana' else 'Diaria'}_{data_atual}.xlsx"
            resumo_data = []
            
            for base in df_routed['BASE_ATRIBUIDA'].unique():
                df_base = df_routed[df_routed['BASE_ATRIBUIDA'] == base]
                
                for periodo in df_base['PERIODO'].unique():
                    df_periodo = df_base[df_base['PERIODO'] == periodo]
                    df_periodo_real = df_periodo[~df_periodo['PROTOCOLO'].isin(['RETORNO_BASE', 'PAUSA_ALMOCO'])]
                    
                    qtd_obras = len(df_periodo_real)
                    qtd_prio = len(df_periodo_real[df_periodo_real['PRIORIDADE'] == 'Sim']) if 'PRIORIDADE' in df_periodo_real.columns else 0
                    km_total = round(df_periodo['DISTANCIA_PONTO_ANTERIOR_KM'].sum(), 2)
                    
                    resumo_data.append({
                        'LEVANTADOR': base,
                        f'{tipo_periodo.upper()}': periodo,
                        'OBRAS ROTEIRIZADAS': qtd_obras,
                        'OBRAS PRIORITARIAS': qtd_prio,
                        'KM TOTAL PROJETADO': km_total
                    })
            
            df_resumo = pd.DataFrame(resumo_data)
            buf_resumo = io.BytesIO()
            with pd.ExcelWriter(buf_resumo, engine='openpyxl') as writer:
                df_resumo.to_excel(writer, index=False, sheet_name='Resumo')
            zip_xl.writestr(nome_resumo, buf_resumo.getvalue())
            planilhas_geradas.append(nome_resumo)

            # 5. Planilhas Individuais (por Levantador)
            for base_nome in df_routed['BASE_ATRIBUIDA'].unique():
                df_lev = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome].copy()
                nome_seguro = re.sub(r'[^A-Za-z0-9_]', '', str(base_nome).replace(" ", "_"))
                if not df_lev.empty:
                    nome_arquivo = f"Roteiro_{nome_seguro}_{data_atual}.xlsx"
                    zip_xl.writestr(nome_arquivo, gerar_excel_bytes(df_lev, col_prioridade, colunas_originais))
                    planilhas_geradas.append(nome_arquivo)
                    
        zip_xl_bytes = buf_zip_xl.getvalue()

        buf_zip_kml = io.BytesIO()
        with zipfile.ZipFile(buf_zip_kml, 'w', zipfile.ZIP_DEFLATED) as zip_kml:
            nome_kml_geral = f"Rota_Geral_{data_atual}.kml"
            kml_geral = gerar_kml_agrupado(df_routed, bases_records, f"Rota_Geral_{data_atual}", colunas_exibir)
            zip_kml.writestr(nome_kml_geral, kml_geral.encode('utf-8'))
            mapas_gerados = [nome_kml_geral]
            
            for base_nome in df_routed['BASE_ATRIBUIDA'].unique():
                df_lev = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome].copy()
                nome_seguro = re.sub(r'[^A-Za-z0-9_]', '', str(base_nome).replace(" ", "_"))
                if not df_lev.empty:
                    nome_arquivo = f"Rota_{nome_seguro}_{data_atual}.kml"
                    kml_lev = gerar_kml_agrupado(df_lev, bases_records, f"Rota_{nome_seguro}", colunas_exibir)
                    zip_kml.writestr(nome_arquivo, kml_lev.encode('utf-8'))
                    mapas_gerados.append(nome_arquivo)
        zip_kml_bytes = buf_zip_kml.getvalue()

        with st.expander("📄 Ver lista de arquivos gerados (Conteúdo dos ZIPs)"):
            st.markdown("**Planilhas Excel:** " + ", ".join(planilhas_geradas))
            st.markdown("**Mapas KML:** " + ", ".join(mapas_gerados))

        col_b1, col_b2, col_b3 = st.columns([1, 1, 1])
        col_b1.download_button("🌐 1. Planilhas Finais (ZIP)", data=zip_xl_bytes, file_name=f"Dados_Estruturados_Roteiro_{data_atual}.zip", mime="application/zip", use_container_width=True)
        col_b2.download_button("🗺️ 2. Baixar Mapas (KML ZIP)", data=zip_kml_bytes, file_name=f"Mapas_KML_{data_atual}.zip", mime="application/zip", use_container_width=True)
        if col_b3.button("🧹 Zerar Roteirizador", type="primary", use_container_width=True):
            limpar_roteirizador()
        
        return 

    # -------------------------------------------------------------
    # TELA DE CONFIGURAÇÃO INICIAL
    # -------------------------------------------------------------
    st.markdown("## 🚙 Roteirizador Operacional Avançado")
    st.markdown("Planeje rotas inteligentes integradas a controles de esforço e retorno à base.")

    with st.sidebar:
        st.markdown("### ⚙️ Gestão de Esforço Diário")
        tipo_periodo = st.radio("Como agrupar o roteiro?", ["Dia", "Semana"], horizontal=True)
        
        modo_limite = st.radio("Critério limitador da equipe:", ["Quantidade Fixa de Obras", "Carga Horária (Tempo Estimado)"])
        
        if modo_limite == "Quantidade Fixa de Obras":
            obras_por_periodo = st.number_input(f"Máximo de Obras por {tipo_periodo}", min_value=1, value=10, step=1)
            limite_periodos = st.number_input(f"Limite total de {tipo_periodo}s a roteirizar", min_value=1, value=5, step=1)
        else:
            horas_por_dia = st.number_input(f"Horas de trabalho disponíveis por {tipo_periodo}", min_value=1.0, value=8.0, step=0.5)
            tempo_medio_obra = st.number_input("Tempo médio de execução por obra (Horas)", min_value=0.1, value=1.5, step=0.1)
            velocidade_media_kmh = st.number_input("Velocidade média do veículo (km/h)", min_value=10.0, value=30.0, step=5.0)
            limite_periodos = st.number_input(f"Limite total de {tipo_periodo}s a roteirizar", min_value=1, value=5, step=1)

    col_up_1, col_up_2 = st.columns(2)

    with col_up_1:
        st.markdown("### 👥 1. Gestão de Equipes (Bases)")
        origem_bases = st.radio("Fonte dos Levantadores", ["Banco de Dados do Sistema", "Upload Planilha Levantadores_MA"])
        df_bases = pd.DataFrame()

        if origem_bases == "Banco de Dados do Sistema":
            _, df_equipes_db, _, _, _, _, _, _ = load_core_data()
            if not df_equipes_db.empty:
                df_equipes_db.columns = normalize_cols(df_equipes_db.columns)
                
                if 'RESIDENCIA' in df_equipes_db.columns:
                    muns_unicos = df_equipes_db['RESIDENCIA'].dropna().unique()
                    mapa_coords = {}
                    
                    with st.spinner("🌍 Mapeando coordenadas dos municípios-base (Satélite)..."):
                        for mun in muns_unicos:
                            if str(mun).strip() != "":
                                lat, lon = obter_coordenadas_municipio_cached(mun)
                                mapa_coords[mun] = (lat, lon)
                                
                    df_equipes_db['LATITUDE'] = df_equipes_db['RESIDENCIA'].map(lambda x: mapa_coords.get(x, (np.nan, np.nan))[0])
                    df_equipes_db['LONGITUDE'] = df_equipes_db['RESIDENCIA'].map(lambda x: mapa_coords.get(x, (np.nan, np.nan))[1])
                else:
                    df_equipes_db['LATITUDE'] = pd.to_numeric(df_equipes_db.get('LATITUDE', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce')
                    df_equipes_db['LONGITUDE'] = pd.to_numeric(df_equipes_db.get('LONGITUDE', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce')

                lista_lev = sorted([str(x) for x in df_equipes_db['LEVANTADOR'].dropna().unique().tolist()])
                
                levs_selecionados = st.multiselect("Selecione as Equipes que irão a campo:", lista_lev)
                if levs_selecionados:
                    df_bases = df_equipes_db[df_equipes_db['LEVANTADOR'].isin(levs_selecionados)].copy()
                    df_bases = df_bases.dropna(subset=['LATITUDE', 'LONGITUDE'])
                    
                    if len(df_bases) < len(levs_selecionados):
                        st.warning("⚠️ Alguns levantadores foram ignorados pois o município de residência deles não pôde ser localizado ou configurado.")
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
                            
                            if 'RESIDENCIA' in df_bases.columns:
                                muns_unicos = df_bases['RESIDENCIA'].dropna().unique()
                                mapa_coords = {}
                                with st.spinner("🌍 Mapeando coordenadas dos municípios-base (Satélite)..."):
                                    for mun in muns_unicos:
                                        lat, lon = obter_coordenadas_municipio_cached(mun)
                                        mapa_coords[mun] = (lat, lon)
                                df_bases['LATITUDE'] = df_bases['RESIDENCIA'].map(lambda x: mapa_coords.get(x, (np.nan, np.nan))[0])
                                df_bases['LONGITUDE'] = df_bases['RESIDENCIA'].map(lambda x: mapa_coords.get(x, (np.nan, np.nan))[1])
                            else:
                                df_bases['LATITUDE'] = pd.to_numeric(df_bases.get('LATITUDE', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce')
                                df_bases['LONGITUDE'] = pd.to_numeric(df_bases.get('LONGITUDE', pd.Series()).astype(str).str.replace(',', '.'), errors='coerce')
                                
                            df_bases = df_bases.dropna(subset=['LATITUDE', 'LONGITUDE'])
                            if len(df_bases) < len(levs_selecionados):
                                st.warning("⚠️ Alguns levantadores foram ignorados pela falta de coordenadas ou Residência válida.")
                except Exception as e:
                    st.error(f"Erro ao ler a planilha: {e}")

        st.markdown("##### Regra de Atribuição Territorial")
        tipo_atribuicao = st.radio(
            "Regra", 
            ["Por Proximidade Geográfica das Coordenadas (Ignora texto)", "Por Municípios Atendidos (Lê texto da planilha)", "Balancear Geograficamente (Mesma Região)"],
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
                if len(dfs) == 0:
                    st.session_state.colunas_originais = df_temp.columns.tolist()
                df_temp.columns = normalize_cols(df_temp.columns)
                dfs.append(df_temp)
            df_tasks = pd.concat(dfs, ignore_index=True)
        except Exception as e:
            st.error(f"Erro ao unificar as planilhas: {e}")
            return

    if 'LATITUDE' not in df_tasks.columns or 'LONGITUDE' not in df_tasks.columns:
        st.error("❌ A planilha de Obras precisa ter LATITUDE e LONGITUDE.")
        return

    st.markdown("---")
    
    # === LIMPEZA AUTOMÁTICA DE DADOS ===
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

    if 'STATUS LIST' in df_tasks.columns:
        status_validos = [
            'EM LEVANTAMENTO', '0', 
            'SEM INFORMAÇÕES', 'SEM INFORMACOES', 
            'CORREÇÃO DE LEVANTAMENTO', 'CORRECAO DE LEVANTAMENTO', 
            'PRÉ ANÁLISE', 'PRE ANALISE'
        ]
        df_tasks = df_tasks[df_tasks['STATUS LIST'].astype(str).str.strip().str.upper().isin(status_validos)]

    if total_orig - len(df_tasks) > 0:
        st.warning(f"⚠️ {total_orig - len(df_tasks)} obras com erros sistêmicos (GPS Vazio, Status Morto ou Status List inválido) foram ignoradas. Restam **{len(df_tasks)} válidas.**")

    if df_tasks.empty: return

    # === PRÉ-ALOCAÇÃO TERRITORIAL ===
    df_tasks_alocadas = pd.DataFrame()
    bases_records = []
    
    if not df_bases.empty:
        bases_records = df_bases.to_dict('records')
        df_tasks['BASE_ATRIBUIDA'] = "NÃO ALOCADO"
        
        if tipo_atribuicao == "Por Proximidade Geográfica das Coordenadas (Ignora texto)":
            def get_nearest_base(lat, lon):
                min_dist = float('inf')
                best_base = None
                for b in bases_records:
                    if pd.notna(b.get('LATITUDE')):
                        d = haversine_vectorized(lat, lon, float(b['LATITUDE']), float(b['LONGITUDE']))
                        if d < min_dist: min_dist, best_base = d, b['LEVANTADOR']
                return best_base
            df_tasks['BASE_ATRIBUIDA'] = df_tasks.apply(lambda r: get_nearest_base(r['LATITUDE'], r['LONGITUDE']), axis=1)

        elif tipo_atribuicao == "Por Municípios Atendidos (Lê texto da planilha)":
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
        df_tasks_alocadas = df_tasks[df_tasks['BASE_ATRIBUIDA'] != "NÃO ALOCADO"].copy()

        if df_tasks_alocadas.empty:
            st.error("Falha: Nenhuma obra encontrada no território das equipes selecionadas. Troque a regra ou o Levantador.")
            return

        if not df_unallocated.empty:
            st.warning(f"⚠️ {len(df_unallocated)} obras carregadas ficaram sem Levantador pois não pertencem à área das equipes selecionadas.")

    # === CONFIGURAÇÃO DE EXIBIÇÃO E PRIORIDADES ===
    if not df_tasks_alocadas.empty:
        with st.expander("🛠️ 3. Configuração de Roteirização (Filtros e Prioridades)", expanded=True):
            c_ex1, c_ex2 = st.columns(2)
            
            if 'TIPO NOTA' in df_tasks_alocadas.columns:
                tipos_nota_unicos = sorted(df_tasks_alocadas['TIPO NOTA'].astype(str).dropna().unique().tolist())
                tipos_selecionados = c_ex1.multiselect("🏷️ Filtrar TIPO DE NOTA (Opcional):", tipos_nota_unicos, default=tipos_nota_unicos)
                
                if not tipos_selecionados:
                    st.warning("Selecione pelo menos um Tipo de Nota para prosseguir.")
                    return
                df_tasks_alocadas = df_tasks_alocadas[df_tasks_alocadas['TIPO NOTA'].astype(str).isin(tipos_selecionados)]

            todas_cols = df_tasks_alocadas.columns.tolist()
            cols_padrao = [c for c in ['PROTOCOLO', 'NOME DO SOLICITANTE', 'MUNICIPIO', 'TIPO LIGACAO', 'STATUS SAP', 'STATUS LIST', 'TIPO NOTA'] if c in todas_cols]
            colunas_exibir = c_ex1.multiselect("Colunas para aparecer no Balão do KML", todas_cols, default=cols_padrao)
            
            col_prioridade = c_ex2.selectbox("Coluna que define a URGÊNCIA (Sinal Vermelho)", ["Nenhuma"] + todas_cols)
            valores_prioridade = []
            
            if col_prioridade != "Nenhuma":
                opcoes_validas_prioridade = sorted(df_tasks_alocadas[col_prioridade].astype(str).dropna().unique().tolist())
                valores_prioridade = c_ex2.multiselect("Quais valores indicam Urgência? (Filtrado por Equipe)", opcoes_validas_prioridade)

    # === INÍCIO DO PROCESSAMENTO ===
    if st.button("🚀 Iniciar Motor de Roteirização (Processo em Nuvem)", type="primary", use_container_width=True):
        if df_tasks_alocadas.empty:
            st.error("Selecione equipes e regras compatíveis com a planilha primeiro.")
            return

        if col_prioridade != "Nenhuma" and len(valores_prioridade) > 0:
            df_tasks_alocadas['PRIORIDADE'] = df_tasks_alocadas[col_prioridade].apply(lambda x: 'Sim' if str(x) in valores_prioridade else 'Não')
        else:
            df_tasks_alocadas['PRIORIDADE'] = 'Não'

        progresso_texto = st.empty()
        barra_progresso = st.progress(0)
        tempo_restante_texto = st.empty()
        
        start_time = time.time()
        api_calls = 0
        total_obras_rotear = len(df_tasks_alocadas)
        obras_processadas = 0
        obras_sobra_total = 0

        routed_data = []
        levantadores_unicos = list(set([b['LEVANTADOR'] for b in bases_records]))

        for b_name in levantadores_unicos:
            base_ref = df_bases[df_bases['LEVANTADOR'] == b_name].iloc[0]
            if pd.isna(base_ref.get('LATITUDE')): continue
            
            base_lat, base_lon = float(base_ref['LATITUDE']), float(base_ref['LONGITUDE'])
            curr_lat, curr_lon = base_lat, base_lon
            
            unvisited = df_tasks_alocadas[df_tasks_alocadas['BASE_ATRIBUIDA'] == b_name].copy()
            ordem_absoluta = 1
            periodo_atual = 1
            obras_no_periodo_atual = 0
            tempo_acumulado_periodo = 0.0
            almoco_inserido = False
            
            while not unvisited.empty:
                
                # ------ LÓGICA DA PAUSA PARA ALMOÇO AUTOMÁTICA ------
                if modo_limite == "Carga Horária (Tempo Estimado)" and tempo_acumulado_periodo >= 4.0 and not almoco_inserido:
                    progresso_texto.text(f"🍔 Programando parada de almoço para {b_name}...")
                    routed_data.append({
                        'PROTOCOLO': 'PAUSA_ALMOCO',
                        'NOME DO SOLICITANTE': '🍔 HORÁRIO DE ALMOÇO (1h)',
                        'LATITUDE': curr_lat,
                        'LONGITUDE': curr_lon,
                        'BASE_ATRIBUIDA': b_name,
                        'ORDEM': ordem_absoluta,
                        'SEMANA': periodo_atual if tipo_periodo == "Semana" else 1,
                        'DIA': periodo_atual if tipo_periodo == "Dia" else 1,
                        'PERIODO': periodo_atual,
                        'DISTANCIA_PONTO_ANTERIOR_KM': 0.0,
                        'ROTA_GEOMETRIA': [[curr_lon, curr_lat], [curr_lon, curr_lat]],
                        'PRIORIDADE': 'Não'
                    })
                    tempo_acumulado_periodo += 1.0 
                    ordem_absoluta += 1
                    almoco_inserido = True

                # ====== LÓGICA DE FURAR A FILA (PRIORIDADE) ======
                unvisited_prio = unvisited[unvisited['PRIORIDADE'] == 'Sim']
                
                if not unvisited_prio.empty:
                    dists = haversine_vectorized(curr_lat, curr_lon, unvisited_prio['LATITUDE'].values, unvisited_prio['LONGITUDE'].values)
                    nearest_idx = unvisited_prio.index[dists.argmin()]
                else:
                    dists = haversine_vectorized(curr_lat, curr_lon, unvisited['LATITUDE'].values, unvisited['LONGITUDE'].values)
                    nearest_idx = unvisited.index[dists.argmin()]
                
                nearest_row = unvisited.loc[nearest_idx]
                dist_km = round(dists.min(), 2)
                
                quebrar_periodo = False
                
                if modo_limite == "Quantidade Fixa de Obras":
                    if obras_no_periodo_atual >= obras_por_periodo:
                        quebrar_periodo = True
                else:
                    tempo_viagem_h = dist_km / velocidade_media_kmh
                    tempo_necessario = tempo_viagem_h + tempo_medio_obra
                    if tempo_acumulado_periodo + tempo_necessario > horas_por_dia and obras_no_periodo_atual > 0:
                        quebrar_periodo = True

                if quebrar_periodo:
                    progresso_texto.text(f"🏠 Desenhando rota de Retorno à Base para {b_name} (Período {periodo_atual})...")
                    rota_retorno = obter_rota_ruas(curr_lat, curr_lon, base_lat, base_lon)
                    api_calls += 1
                    
                    dist_retorno = haversine_vectorized(curr_lat, curr_lon, base_lat, base_lon)
                    routed_data.append({
                        'PROTOCOLO': 'RETORNO_BASE',
                        'NOME DO SOLICITANTE': 'BASE_RETORNO',
                        'LATITUDE': base_lat,
                        'LONGITUDE': base_lon,
                        'BASE_ATRIBUIDA': b_name,
                        'ORDEM': ordem_absoluta,
                        'SEMANA': periodo_atual if tipo_periodo == "Semana" else 1,
                        'DIA': periodo_atual if tipo_periodo == "Dia" else 1,
                        'PERIODO': periodo_atual,
                        'DISTANCIA_PONTO_ANTERIOR_KM': round(dist_retorno, 2),
                        'ROTA_GEOMETRIA': rota_retorno,
                        'PRIORIDADE': 'Não'
                    })
                    
                    time.sleep(1.2)
                    
                    periodo_atual += 1
                    ordem_absoluta = 1
                    obras_no_periodo_atual = 0
                    tempo_acumulado_periodo = 0.0
                    almoco_inserido = False
                    curr_lat, curr_lon = base_lat, base_lon 
                    
                    if periodo_atual > limite_periodos:
                        obras_sobra_total += len(unvisited)
                        obras_processadas += len(unvisited) 
                        break
                    
                    continue 

                progresso_texto.text(f"🗺️ Roteirizando {b_name} | {tipo_periodo} {periodo_atual} | Obra {ordem_absoluta}...")
                rota_geom = obter_rota_ruas(curr_lat, curr_lon, nearest_row['LATITUDE'], nearest_row['LONGITUDE'])
                api_calls += 1
                
                row_dict = nearest_row.to_dict()
                row_dict['ORDEM'] = ordem_absoluta
                row_dict['SEMANA'] = periodo_atual if tipo_periodo == "Semana" else 1
                row_dict['DIA'] = periodo_atual if tipo_periodo == "Dia" else 1
                row_dict['PERIODO'] = periodo_atual
                row_dict['DISTANCIA_PONTO_ANTERIOR_KM'] = dist_km
                row_dict['ROTA_GEOMETRIA'] = rota_geom
                
                routed_data.append(row_dict)
                
                curr_lat, curr_lon = nearest_row['LATITUDE'], nearest_row['LONGITUDE']
                unvisited = unvisited.drop(nearest_idx)
                
                ordem_absoluta += 1
                obras_no_periodo_atual += 1
                obras_processadas += 1
                
                if modo_limite != "Quantidade Fixa de Obras":
                    tempo_acumulado_periodo += (dist_km / velocidade_media_kmh) + tempo_medio_obra
                
                elapsed = time.time() - start_time
                avg_time = elapsed / api_calls
                obras_restantes = total_obras_rotear - obras_processadas
                
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
                    
                barra_progresso.progress(min(obras_processadas / total_obras_rotear, 1.0))
                time.sleep(1.2)
                
            if obras_no_periodo_atual > 0 and periodo_atual <= limite_periodos:
                progresso_texto.text(f"🏠 Encerrando pacote de {b_name}, traçando retorno final...")
                rota_retorno = obter_rota_ruas(curr_lat, curr_lon, base_lat, base_lon)
                api_calls += 1
                dist_retorno = haversine_vectorized(curr_lat, curr_lon, base_lat, base_lon)
                routed_data.append({
                    'PROTOCOLO': 'RETORNO_BASE',
                    'NOME DO SOLICITANTE': 'BASE_RETORNO',
                    'LATITUDE': base_lat,
                    'LONGITUDE': base_lon,
                    'BASE_ATRIBUIDA': b_name,
                    'ORDEM': ordem_absoluta,
                    'SEMANA': periodo_atual if tipo_periodo == "Semana" else 1,
                    'DIA': periodo_atual if tipo_periodo == "Dia" else 1,
                    'PERIODO': periodo_atual,
                    'DISTANCIA_PONTO_ANTERIOR_KM': round(dist_retorno, 2),
                    'ROTA_GEOMETRIA': rota_retorno,
                    'PRIORIDADE': 'Não'
                })
                time.sleep(1.2)

        if obras_sobra_total > 0:
            st.warning(f"⏳ {obras_sobra_total} obras ficaram de fora do roteiro porque a carga horária/limite estourou.")

        st.session_state.df_routed = pd.DataFrame(routed_data)
        st.session_state.bases_records = bases_records
        st.session_state.tipo_periodo = tipo_periodo
        st.session_state.colunas_exibir = colunas_exibir
        st.session_state.col_prioridade = col_prioridade
        st.session_state.roteamento_concluido = True
        
        st.rerun()

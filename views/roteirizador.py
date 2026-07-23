import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import io
import zipfile
import html

# Injeção de CSS
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }
    .stSelectbox label, .stFileUploader label, .stRadio label, .stNumberInput label { font-size: 14px !important; font-weight: 600 !important; color: #1A4F7C !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# FUNÇÕES MATEMÁTICAS E DE ROTEIRIZAÇÃO
# ==========================================
def haversine_vectorized(lat1, lon1, lat2, lon2):
    """Calcula a distância em KM entre um ponto e um vetor de pontos usando a fórmula de Haversine."""
    R = 6371.0 # Raio da Terra em km
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def gerar_kml_rota(df_rota, base_nome, base_lat, base_lon, dia, cols_exibir):
    """Gera o arquivo XML/KML padronizado de uma rota específica."""
    kml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>ROTA_{base_nome}_DIA_{dia}</name>
    <Style id="linha-rota">
      <LineStyle><color>ffcf2802</color><width>4</width></LineStyle>
    </Style>
'''
    # Adiciona a Base
    kml_str += f'''    <Placemark>
      <name>BASE: {html.escape(str(base_nome))}</name>
      <Point><coordinates>{base_lon},{base_lat},0</coordinates></Point>
    </Placemark>\n'''

    coords_linha = f"{base_lon},{base_lat},0\n"

    # Adiciona os Pontos (Obras)
    for _, row in df_rota.iterrows():
        lon, lat = str(row['LONGITUDE']).replace(',','.'), str(row['LATITUDE']).replace(',','.')
        coords_linha += f"          {lon},{lat},0\n"
        
        desc_parts = [f"<b>Ordem:</b> {row['ORDEM']}"]
        for col in cols_exibir:
            if col in row:
                desc_parts.append(f"<b>{col}:</b> {html.escape(str(row[col]))}")
                
        desc_cdata = "<br>".join(desc_parts)
        nome_ponto = f"{row['ORDEM']} - {html.escape(str(row.get('NOME DO SOLICITANTE', 'OBRA')))}"
        
        kml_str += f'''    <Placemark>
      <name>{nome_ponto}</name>
      <description><![CDATA[{desc_cdata}]]></description>
      <Point><coordinates>{lon},{lat},0</coordinates></Point>
    </Placemark>\n'''

    # Adiciona a Linha (Caminho)
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
    # --- BARRA LATERAL ---
    with st.sidebar:
        st.markdown("### ⚙️ Configurações")
        obras_por_dia = st.number_input("Obras por dia", min_value=1, value=8, step=1)
        
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        st.markdown("### 📍 Bases Operacionais")
        origem_bases = st.radio("Origem das Bases", ["Upload Planilha", "Cadastro Manual"], label_visibility="collapsed")
        
        df_bases = pd.DataFrame()
        if origem_bases == "Upload Planilha":
            base_file = st.file_uploader("Upload da Planilha de Bases", type=["xlsx", "xls"])
            if base_file:
                try:
                    df_bases = pd.read_excel(base_file)
                    df_bases.columns = [str(c).strip().upper() for c in df_bases.columns]
                except Exception as e:
                    st.error(f"Erro ao ler arquivo: {e}")
        else:
            st.caption("Insira os dados da base abaixo:")
            df_bases_manual = pd.DataFrame([{"NOME": "Base Principal", "LATITUDE": -5.2, "LONGITUDE": -45.0}])
            df_bases = st.data_editor(df_bases_manual, num_rows="dynamic", use_container_width=True, hide_index=True)

    # --- ÁREA PRINCIPAL ---
    st.markdown("## 🚙 Roteirizador Operacional")
    st.markdown("### 📁 Upload dos Arquivos de Demanda")
    task_files = st.file_uploader("Selecione um ou mais arquivos Excel com as Obras", type=["xlsx", "xls"], accept_multiple_files=True)
    
    if not task_files:
        st.info("👆 Por favor, envie os arquivos de tarefas na caixa acima para começar a configuração.")
        return

    # Processamento dos Arquivos de Tarefas
    try:
        dfs = []
        for f in task_files:
            df_temp = pd.read_excel(f)
            df_temp.columns = [str(c).strip().upper() for c in df_temp.columns]
            dfs.append(df_temp)
        df_tasks = pd.concat(dfs, ignore_index=True)
    except Exception as e:
        st.error(f"Erro ao unificar as planilhas: {e}")
        return

    if 'LATITUDE' not in df_tasks.columns or 'LONGITUDE' not in df_tasks.columns:
        st.error("❌ Os arquivos enviados não possuem as colunas obrigatórias 'LATITUDE' e 'LONGITUDE'.")
        return

    # Tratamento Numérico
    df_tasks['LATITUDE'] = pd.to_numeric(df_tasks['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
    df_tasks['LONGITUDE'] = pd.to_numeric(df_tasks['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
    df_tasks = df_tasks.dropna(subset=['LATITUDE', 'LONGITUDE']).copy()

    if df_tasks.empty:
        st.error("❌ Nenhuma coordenada válida foi encontrada após a limpeza de dados.")
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
            valores_prioridade = c2.multiselect(f"Valores prioritários em '{col_prioridade}'", vals_unicos)

    # --- EXECUÇÃO ---
    if st.button("🚀 Executar Roteirização", type="primary", use_container_width=True):
        if df_bases.empty or 'LATITUDE' not in df_bases.columns or 'LONGITUDE' not in df_bases.columns or 'NOME' not in df_bases.columns:
            st.error("❌ Planilha de Bases inválida. Verifique se contém as colunas NOME, LATITUDE e LONGITUDE.")
            return

        with st.spinner("Calculando rotas otimizadas e agrupando demandas..."):
            # 1. Atribuição à Base Mais Próxima
            bases_records = df_bases.to_dict('records')
            
            def get_nearest_base(lat, lon):
                min_dist = float('inf')
                best_base = None
                for b in bases_records:
                    d = haversine_vectorized(lat, lon, float(str(b['LATITUDE']).replace(',','.')), float(str(b['LONGITUDE']).replace(',','.')))
                    if d < min_dist:
                        min_dist, best_base = d, b['NOME']
                return best_base

            df_tasks['BASE_ATRIBUIDA'] = df_tasks.apply(lambda r: get_nearest_base(r['LATITUDE'], r['LONGITUDE']), axis=1)

            # 2. Roteirização Nearest Neighbor (Por Base)
            routed_data = []
            for base in bases_records:
                b_name = base['NOME']
                b_lat = float(str(base['LATITUDE']).replace(',','.'))
                b_lon = float(str(base['LONGITUDE']).replace(',','.'))
                
                df_b = df_tasks[df_tasks['BASE_ATRIBUIDA'] == b_name].copy()
                if df_b.empty: continue
                
                curr_lat, curr_lon = b_lat, b_lon
                unvisited = df_b.copy()
                ordem = 1
                
                while not unvisited.empty:
                    dists = haversine_vectorized(curr_lat, curr_lon, unvisited['LATITUDE'].values, unvisited['LONGITUDE'].values)
                    nearest_idx = unvisited.index[dists.argmin()]
                    nearest_row = unvisited.loc[nearest_idx]
                    
                    row_dict = nearest_row.to_dict()
                    row_dict['ORDEM'] = ordem
                    row_dict['DIA'] = ((ordem - 1) // obras_por_dia) + 1
                    row_dict['DISTANCIA_ATE_AQUI_KM'] = round(dists.min(), 2)
                    
                    # Checagem de Prioridade
                    is_prio = "Não"
                    if col_prioridade != "Nenhuma" and row_dict.get(col_prioridade) in valores_prioridade:
                        is_prio = "Sim"
                    row_dict['PRIORIDADE'] = is_prio
                    
                    routed_data.append(row_dict)
                    
                    curr_lat, curr_lon = nearest_row['LATITUDE'], nearest_row['LONGITUDE']
                    unvisited = unvisited.drop(nearest_idx)
                    ordem += 1

            df_routed = pd.DataFrame(routed_data)

            # --- RESULTADOS E KPIS ---
            st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)
            k1, k2, k3 = st.columns(3)
            k1.metric("📌 Total de Obras", len(df_routed))
            k2.metric("🏢 Bases Ativas", df_routed['BASE_ATRIBUIDA'].nunique())
            k3.metric("📅 Total de Dias Planejados", df_routed.groupby('BASE_ATRIBUIDA')['DIA'].max().sum())

            # Tabela de Resultados
            st.markdown("#### 📋 Resumo das Rotas Geradas")
            st.dataframe(df_routed, use_container_width=True, height=250)

            # --- MAPA FOLIUM ---
            st.markdown("#### 🗺️ Visualização Geográfica")
            mapa = folium.Map(location=[df_routed['LATITUDE'].mean(), df_routed['LONGITUDE'].mean()], zoom_start=8)
            
            # Adiciona Bases (Vermelho)
            for b in bases_records:
                b_lat, b_lon = float(str(b['LATITUDE']).replace(',','.')), float(str(b['LONGITUDE']).replace(',','.'))
                folium.Marker([b_lat, b_lon], icon=folium.Icon(color='red', icon='building', prefix='fa'), tooltip=f"Base: {b['NOME']}").add_to(mapa)

            # Adiciona Rotas e Pontos
            cores = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'darkblue']
            
            for idx, base_nome in enumerate(df_routed['BASE_ATRIBUIDA'].unique()):
                cor_rota = cores[idx % len(cores)]
                df_base_rota = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome]
                
                for dia in df_base_rota['DIA'].unique():
                    df_dia = df_base_rota[df_base_rota['DIA'] == dia]
                    fg = folium.FeatureGroup(name=f"Rota {base_nome} - Dia {dia}")
                    
                    # Linha do Caminho
                    base_ref = next((b for b in bases_records if b['NOME'] == base_nome), None)
                    b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))
                    
                    pontos_linha = [(b_lat, b_lon)] + list(zip(df_dia['LATITUDE'], df_dia['LONGITUDE']))
                    folium.PolyLine(pontos_linha, color=cor_rota, weight=3, opacity=0.7).add_to(fg)
                    
                    # Marcadores
                    for _, r in df_dia.iterrows():
                        icone = 'star' if r['PRIORIDADE'] == "Sim" else 'info-sign'
                        cor_icone = 'darkorange' if r['PRIORIDADE'] == "Sim" else cor_rota
                        
                        info_html = f"<b>Ordem:</b> {r['ORDEM']} | <b>Dia:</b> {r['DIA']}<br>"
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

            # --- EXPORTAÇÕES ---
            st.markdown("#### 📥 Exportar Resultados")
            col_b1, col_b2, col_b3 = st.columns(3)

            # Excel
            buf_xl = io.BytesIO()
            df_routed.to_excel(buf_xl, index=False, engine='openpyxl')
            col_b1.download_button("📥 Baixar Excel Geral", data=buf_xl.getvalue(), file_name="roteiro_operacional.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

            # CSV
            csv_data = df_routed.to_csv(index=False, sep=';').encode('utf-8-sig')
            col_b2.download_button("📥 Baixar CSV Geral", data=csv_data, file_name="roteiro_operacional.csv", mime="text/csv", use_container_width=True)

            # Arquivos KML Zippados (Um para cada Base/Dia)
            buf_zip = io.BytesIO()
            with zipfile.ZipFile(buf_zip, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for base_nome in df_routed['BASE_ATRIBUIDA'].unique():
                    base_ref = next((b for b in bases_records if b['NOME'] == base_nome), None)
                    b_lat, b_lon = float(str(base_ref['LATITUDE']).replace(',','.')), float(str(base_ref['LONGITUDE']).replace(',','.'))
                    
                    df_base = df_routed[df_routed['BASE_ATRIBUIDA'] == base_nome]
                    for dia in df_base['DIA'].unique():
                        df_dia = df_base[df_base['DIA'] == dia]
                        kml_str = gerar_kml_rota(df_dia, base_nome, b_lat, b_lon, dia, colunas_exibir)
                        zip_file.writestr(f"ROTA_{base_nome}_DIA_{dia}.kml", kml_str.encode('utf-8'))
            
            col_b3.download_button("🗺️ Baixar Todas as Rotas (KML ZIP)", data=buf_zip.getvalue(), file_name="rotas_kml.zip", mime="application/zip", use_container_width=True)

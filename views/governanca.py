import streamlit as st
import pandas as pd
import numpy as np
import io
import html
from datetime import datetime
from database import load_core_data, save_notas_to_db, vectorized_haversine, SEM_LEVANTADOR, STATUS_PRODUTIVIDADE

def view_governanca():
    st.markdown("### 🔎 Busca e Governança")
    st.markdown("Gerencie a fila, aloque demandas, exporte dados e edite a base oficial de obras de forma centralizada.")

    # =====================================================================
    # 1. CARREGAMENTO DOS DADOS E SEGURANÇA (RLS)
    # =====================================================================
    df_notas, df_equipes_db, resumo_levantadores, levantadores_criticos, todos_levantadores, mapa_lat, mapa_lon, _ = load_core_data()
    
    perfil_atual = st.session_state.get("perfil_usuario")
    usuario_atual = st.session_state.get("usuario")

    # Proteção em Nível de Linha (Se for Levantador, ele só vê e edita o dele)
    if perfil_atual == "LEVANTADOR" and usuario_atual:
        usuario_limpo = usuario_atual.strip().upper()
        df_notas = df_notas[df_notas['LEVANTADOR'].str.strip().str.upper() == usuario_limpo]
        df_equipes_db = df_equipes_db[df_equipes_db['Levantador'].str.strip().str.upper() == usuario_limpo]
        resumo_levantadores = resumo_levantadores[resumo_levantadores['Levantador'].str.strip().str.upper() == usuario_limpo]
        todos_levantadores = [usuario_limpo]
        st.info(f"👁️ **Modo Foco (RLS Ativo):** Exibindo apenas a base e as obras atribuídas a você ({usuario_atual}).")

    if df_notas.empty and resumo_levantadores.empty:
        st.warning("O banco de dados está vazio. Faça a importação na Carga de Lotes.")
        return

    # =====================================================================
    # 2. MÓDULO DE DESEMPENHO E GESTÃO DE FILA (INJETADO)
    # =====================================================================
    col_t1, col_t2 = st.columns([1.5, 1])
    with col_t1:
        st.markdown("#### 📋 Desempenho e Alocação")
        
        col_mun_eq = 'Município' if 'Município' in df_equipes_db.columns else 'MUNICIPIO'
        
        if not df_equipes_db.empty and col_mun_eq in df_equipes_db.columns and 'Levantador' in df_equipes_db.columns:
            muns_atribuidos = df_equipes_db[df_equipes_db['Levantador'] != SEM_LEVANTADOR].groupby('Levantador')[col_mun_eq].apply(
                lambda x: len(set([str(m).title() for m in x if pd.notna(m) and str(m).strip() != '']))
            ).reset_index(name='Area_Atuacao')
            
            resumo_view = pd.merge(resumo_levantadores, muns_atribuidos, on='Levantador', how='left')
            resumo_view['Area_Atuacao'] = resumo_view['Area_Atuacao'].fillna(0).astype(int)
        else:
            resumo_view = resumo_levantadores.copy()
            resumo_view['Area_Atuacao'] = 0

        st.dataframe(
            resumo_view[['Levantador', 'Equipe', 'Area_Atuacao', 'Total_Obras_Real']].sort_values('Total_Obras_Real', ascending=False), 
            use_container_width=True, hide_index=True, height=280, 
            column_config={
                "Levantador": "Técnico", 
                "Equipe": "Equipe", 
                "Area_Atuacao": st.column_config.NumberColumn("📍 Qtd Municípios", format="%d"),
                "Total_Obras_Real": st.column_config.ProgressColumn("Carga (Meta: 50)", format="%d", min_value=0, max_value=50)
            }
        )
        
    with col_t2:
        st.markdown("#### ⚡ Gestão de Fila")
        with st.container(border=True):
            c_sel, c_inf = st.columns([3, 1])
            
            if perfil_atual == "LEVANTADOR":
                lev_sel = usuario_atual.upper()
                c_sel.markdown(f"**Técnico Ativo:**<br>{lev_sel}", unsafe_allow_html=True)
            else:
                lev_sel = c_sel.selectbox("Selecione o Técnico:", todos_levantadores, label_visibility="collapsed", key="sel_tech_gov")
                
            if st.session_state.get('last_lev_gov') != lev_sel:
                st.session_state.assign_step_gov = 0; st.session_state.show_demanda_gov = False; st.session_state.last_lev_gov = lev_sel
                
            obras_do_lev = int(resumo_levantadores[resumo_levantadores['Levantador'] == lev_sel]['Total_Obras_Real'].iloc[0]) if not resumo_levantadores[resumo_levantadores['Levantador'] == lev_sel].empty else 0
            cor_badge = "#e8f4f8" if obras_do_lev >= 50 else "#fce8e8"
            c_inf.markdown(f"<div style='text-align:center; background:{cor_badge}; border-radius:5px; padding:6px;'><b style='font-size:18px;'>{obras_do_lev}</b><br><small style='font-size:10px; font-weight:bold;'>OBRAS</small></div>", unsafe_allow_html=True)
            
            st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
            
            if st.session_state.get('perfil_usuario') == "ADMIN":
                if obras_do_lev < 50:
                    if st.session_state.get('assign_step_gov', 0) == 0:
                        if st.button(f"➕ Atribuir {50 - obras_do_lev} Obras", use_container_width=True, type="primary", key="btn_atr_gov"): st.session_state.assign_step_gov = 1; st.rerun()
                    elif st.session_state.assign_step_gov == 1:
                        st.info("Confirmar geo-atribuição?")
                        c_a, c_b = st.columns(2)
                        if c_a.button("✅ Sim", use_container_width=True, type="primary", key="btn_sim_gov"):
                            df_livres = df_notas[(df_notas['LEVANTADOR'] == SEM_LEVANTADOR) & (df_notas['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))].copy()
                            if len(df_livres) == 0: st.error("Fila Vazia!"); st.session_state.assign_step_gov = 0
                            else:
                                tr = df_equipes_db[df_equipes_db['Levantador'] == lev_sel]
                                r_lat = mapa_lat.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Latitude']).replace(',','.'))
                                r_lon = mapa_lon.get(str(tr['Residencia'].iloc[0]).strip().upper(), np.nan) if 'Residencia' in tr.columns and pd.notna(tr['Residencia'].iloc[0]) else float(str(tr.iloc[0]['Longitude']).replace(',','.'))
                                
                                df_livres['L_Lat'] = pd.to_numeric(df_livres['MUNICIPIO'].map(mapa_lat), errors='coerce')
                                df_livres['L_Lon'] = pd.to_numeric(df_livres['MUNICIPIO'].map(mapa_lon), errors='coerce')
                                df_livres['D_KM'] = vectorized_haversine(r_lat, r_lon, df_livres['L_Lat'], df_livres['L_Lon'])
                                
                                att = df_livres.sort_values('D_KM').head(50 - obras_do_lev).index
                                df_update = df_notas.copy()
                                df_update.loc[att, 'LEVANTADOR'] = lev_sel
                                if save_notas_to_db(df_update): st.success("Vinculado!"); st.session_state.assign_step_gov = 2; load_core_data.clear(); st.rerun()
                        if c_b.button("❌ Não", use_container_width=True, key="btn_nao_gov"): st.session_state.assign_step_gov = 0; st.rerun()
                    elif st.session_state.assign_step_gov == 2:
                        st.success("✅ Atribuição Concluída.")
                        if st.button("📋 Gerar Demanda", use_container_width=True, type="primary", key="btn_gerar1_gov"): st.session_state.show_demanda_gov = True; st.session_state.assign_step_gov = 0; st.rerun()
                else:
                    st.success("✅ Meta Atingida.")
                    if st.button("📋 Gerar Demanda", use_container_width=True, type="primary", key="btn_gerar2_gov"): st.session_state.show_demanda_gov = True
            else: 
                st.success(f"✅ Demanda Sincronizada.")
                if st.button("📋 Gerar Minha Demanda", use_container_width=True, type="primary", key="btn_gerar_lev_gov"): st.session_state.show_demanda_gov = True
                
            tech_muns = df_notas[(df_notas['LEVANTADOR'] == lev_sel) & (df_notas['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))]['MUNICIPIO'].unique()
            tech_muns = [str(m).strip().title() for m in tech_muns if str(m).strip().upper() not in ['NAN', 'NONE', '', '<NA>']]
            muns_str = ", ".join(tech_muns) if tech_muns else "Nenhuma cidade ativa."
            
            st.markdown(f"""
            <div style='margin-top: 15px; padding: 12px; background-color: #f8f9fa; border-radius: 6px; border-left: 4px solid #1A4F7C;'>
                <p style='margin: 0; font-size: 11px; color: #666; font-weight: bold; text-transform: uppercase;'>📍 Área de Atuação (Obras Alocadas)</p>
                <p style='margin: 5px 0 0 0; font-size: 13px; color: #222;'>{muns_str}</p>
            </div>
            """, unsafe_allow_html=True)
            
    if st.session_state.get('show_demanda_gov', False):
        st.markdown("---")
        df_demanda = df_notas[(df_notas['LEVANTADOR'] == lev_sel) & (df_notas['STATUS LIST'].isin(STATUS_PRODUTIVIDADE))].copy()
        
        if len(df_demanda) > 0:
            df_exp = df_demanda.copy()
            
            # Matriz exata para o Export
            colunas_exigidas = ['PROTOCOLO', 'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 'PONTO DE REFERENCIA', 'TIPO LIGACAO']
            
            for col in colunas_exigidas:
                if col not in df_exp.columns:
                    if col == 'ENDEREÇO' and 'ENDERECO' in df_exp.columns: df_exp['ENDEREÇO'] = df_exp['ENDERECO']
                    elif col == 'INSTALACAO' and 'INSTALAÇÃO' in df_exp.columns: df_exp['INSTALACAO'] = df_exp['INSTALAÇÃO']
                    elif col == 'TIPO LIGACAO' and 'TIPO LIGAÇÃO' in df_exp.columns: df_exp['TIPO LIGACAO'] = df_exp['TIPO LIGAÇÃO']
                    else: df_exp[col] = '' 
            
            df_exp = df_exp[colunas_exigidas]
            
            # Inteligência do Nome
            muns_unicos = df_exp['MUNICIPIO'].dropna().replace(['', 'NAN', 'NONE'], pd.NA).dropna().unique()
            if len(muns_unicos) == 1: mun_nome = str(muns_unicos[0]).strip().upper()
            elif len(muns_unicos) > 1: mun_nome = f"{str(muns_unicos[0]).strip().upper()} E OUTROS"
            else: mun_nome = "DEMANDA"
            
            data_hoje = datetime.now().strftime('%d.%m.%Y')
            lev_nome = str(lev_sel).strip().upper()
            base_filename = f"{mun_nome} - {data_hoje} ({lev_nome})"
            
            # KML Seguro
            kml_str = f'''<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n  <Document>\n    <name>{base_filename}.xlsx</name>\n    <Style id="icon-1899-0288D1-normal">\n      <IconStyle>\n        <color>ffd18802</color>\n        <scale>1</scale>\n        <Icon>\n          <href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href>\n        </Icon>\n        <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>\n      </IconStyle>\n      <LabelStyle>\n        <scale>0</scale>\n      </LabelStyle>\n    </Style>\n    <Style id="icon-1899-0288D1-highlight">\n      <IconStyle>\n        <color>ffd18802</color>\n        <scale>1</scale>\n        <Icon>\n          <href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href>\n        </Icon>\n        <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>\n      </IconStyle>\n      <LabelStyle>\n        <scale>1</scale>\n      </LabelStyle>\n    </Style>\n    <StyleMap id="icon-1899-0288D1">\n      <Pair>\n        <key>normal</key>\n        <styleUrl>#icon-1899-0288D1-normal</styleUrl>\n      </Pair>\n      <Pair>\n        <key>highlight</key>\n        <styleUrl>#icon-1899-0288D1-highlight</styleUrl>\n      </Pair>\n    </StyleMap>\n'''
            for _, r in df_exp.iterrows():
                lon_raw = str(r.get('LONGITUDE', '')).replace(',','.')
                lat_raw = str(r.get('LATITUDE', '')).replace(',','.')
                
                try:
                    lon_val = float(lon_raw)
                    lat_val = float(lat_raw)
                    coords_kml = f"{lon_val},{lat_val},0"
                except: continue 
                
                desc_parts = []
                ext_data_parts = []
                for col in colunas_exigidas:
                    val = str(r.get(col, '')).strip()
                    if col != 'NOME DO SOLICITANTE': desc_parts.append(f"{col}: {val}")
                    ext_data_parts.append(f'<Data name="{col}">\n          <value>{html.escape(val)}</value>\n        </Data>')
                    
                desc_cdata = "<br>".join(desc_parts)
                ext_data_str = "\n        ".join(ext_data_parts)
                nome_solic = html.escape(str(r.get('NOME DO SOLICITANTE', '')))
                
                kml_str += f'''    <Placemark>\n      <name>{nome_solic}</name>\n      <description><![CDATA[{desc_cdata}]]></description>\n      <styleUrl>#icon-1899-0288D1</styleUrl>\n      <ExtendedData>\n        {ext_data_str}\n      </ExtendedData>\n      <Point>\n        <coordinates>\n          {coords_kml}\n        </coordinates>\n      </Point>\n    </Placemark>\n'''
            kml_str += '''  </Document>\n</kml>'''
            
            # Excel Buffer
            buf = io.BytesIO()
            df_exp.to_excel(buf, index=False, engine='openpyxl')
            
            st.info(f"⚡ **{len(df_exp)} obras processadas** para exportação. (O Excel conterá 100% da carga. O KML mapeará apenas locais com coordenadas válidas).")
            
            c_b1, c_b2, c_b3 = st.columns([2.5, 2.5, 4])
            c_b1.download_button("📥 Planilha (Excel)", data=buf.getvalue(), file_name=f"{base_filename}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="dl_xl_gov")
            c_b2.download_button("🗺️ Mapa (KML)", data=kml_str.encode('utf-8'), file_name=f"{base_filename}.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True, key="dl_kml_gov")
            
            if c_b3.button("Fechar Ferramenta", use_container_width=True, key="btn_fechar_gov"): st.session_state.show_demanda_gov = False; st.rerun()

    st.markdown("---")

    # =====================================================================
    # 3. MÓDULO DE EXPLORAÇÃO E GOVERNANÇA (EDITOR DE BASE)
    # =====================================================================
    st.markdown("#### 🔍 Explorador e Edição da Base de Dados")
    
    colunas_template = [
        'ID SISCO', 'STATUS SISCO', 'TIPO LIGACAO SISCO', 'DESCRIÇÃO SERVIÇO SISCO', 
        'DATA CRIAÇAO SISCO', 'STATUS SAP', 'LEVANTADOR', 'STATUS LIST', 
        'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'PROTOCOLO', 
        'CONTA CONTRATO', 'INSTALACAO', 'NOME DO SOLICITANTE', 'REGIONAL', 
        'MUNICIPIO', 'ENDEREÇO', 'LOCALIDADE', 'LONGITUDE', 'LATITUDE', 
        'PONTO DE REFERENCIA', 'TIPO LIGACAO'
    ]
    
    for col in colunas_template:
        if col not in df_notas.columns: df_notas[col] = ""
            
    cols_extras = [c for c in df_notas.columns if c not in colunas_template]
    df_notas = df_notas[colunas_template + cols_extras]

    colunas_data = ['DATA CRIAÇAO SISCO', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST']
    for col in colunas_data:
        if col in df_notas.columns:
            df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce').dt.date

    # Filtros da Tabela
    regioes = ["TODAS"] + sorted(list(set([str(x) for x in df_notas['REGIONAL'].unique() if pd.notna(x)])))
    municipios = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['MUNICIPIO'].unique() if pd.notna(x)])))
    levantadores = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['LEVANTADOR'].unique() if pd.notna(x)])))
    status_sap = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['STATUS SAP'].unique() if pd.notna(x)])))
    status_list_op = ["TODOS"] + sorted(list(set([str(x) for x in df_notas['STATUS LIST'].unique() if pd.notna(x)])))

    if 'target_status_list' in st.session_state:
        alvo = st.session_state.pop('target_status_list')
        match = next((s for s in status_list_op if str(s).upper() == alvo), None)
        st.session_state['filtro_list_widget'] = match if match else 'TODOS'

    if st.session_state.get('filtro_lev_widget') and st.session_state['filtro_lev_widget'] not in levantadores:
        st.session_state['filtro_lev_widget'] = "TODOS"

    with st.container(border=True):
        st.markdown("#### 🎯 Painel de Filtros da Base")
        
        c_busca, c_cols = st.columns([3, 1.5])
        busca_livre = c_busca.text_input("Busca Rápida", placeholder="🔍 Pesquise por ID SISCO, Protocolo ou Nome...", label_visibility="collapsed", key="search_gov")
        
        todas_cols = df_notas.columns.tolist()
        cols_padrao = ['ID SISCO', 'PROTOCOLO', 'LEVANTADOR', 'STATUS LIST', 'STATUS SAP', 'REGIONAL', 'MUNICIPIO', 'DATA CRIAÇAO SISCO']
        cols_padrao = [c for c in cols_padrao if c in todas_cols]
        
        colunas_selecionadas = c_cols.multiselect("Colunas Visíveis", todas_cols, default=cols_padrao, placeholder="Escolha as colunas...", key="ms_cols_gov")
        
        c1, c2, c3, c4, c5 = st.columns(5)
        filtro_reg = c1.selectbox("Regional", regioes, key="filtro_reg_widget")
        filtro_mun = c2.selectbox("Município", municipios, key="filtro_mun_widget")
        filtro_lev = c3.selectbox("Levantador", levantadores, key="filtro_lev_widget")
        filtro_sap = c4.selectbox("Status SAP", status_sap, key="filtro_sap_widget")
        filtro_list = c5.selectbox("Status List", status_list_op, key="filtro_list_widget")
        
    df_filtrado = df_notas.copy()
    
    if filtro_reg != "TODAS": df_filtrado = df_filtrado[df_filtrado['REGIONAL'].astype(str) == filtro_reg]
    if filtro_mun != "TODOS": df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'].astype(str) == filtro_mun]
    if filtro_lev != "TODOS": df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'].astype(str) == filtro_lev]
    if filtro_sap != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS SAP'].astype(str) == filtro_sap]
    if filtro_list != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS LIST'].astype(str) == filtro_list]
    
    if busca_livre:
        termo = str(busca_livre).lower()
        df_filtrado = df_filtrado[
            df_filtrado['ID SISCO'].astype(str).str.lower().str.contains(termo) |
            df_filtrado['PROTOCOLO'].astype(str).str.lower().str.contains(termo) |
            df_filtrado['NOME DO SOLICITANTE'].astype(str).str.lower().str.contains(termo)
        ]

    st.caption(f"**Total Encontrado na Base:** {len(df_filtrado)} registros filtrados.")

    if not colunas_selecionadas: colunas_selecionadas = cols_padrao
    df_para_editar = df_filtrado[colunas_selecionadas].copy()
    
    config_colunas = {}
    for col in colunas_data:
        if col in colunas_selecionadas: config_colunas[col] = st.column_config.DateColumn(col, format="DD/MM/YYYY")
            
    if 'STATUS LIST' in colunas_selecionadas:
        opcoes_status = sorted(list(set([str(x) for x in df_notas['STATUS LIST'].unique() if pd.notna(x) and x.strip() != ""])))
        config_colunas['STATUS LIST'] = st.column_config.SelectboxColumn("STATUS LIST", help="Altere o status clicando na seta", options=opcoes_status)

    df_editado = st.data_editor(
        df_para_editar,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        height=450,
        column_config=config_colunas,
        key="editor_gov"
    )

    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("#### ⚡ Ações da Base de Dados")
        col_save, spacer, col_adv = st.columns([3, 4, 3])
        
        if col_save.button("💾 Salvar Alterações Tabela", type="primary", use_container_width=True, key="btn_save_tab_gov"):
            if st.session_state.perfil_usuario == "LEITURA":
                st.error("Acesso Negado: O seu perfil é apenas leitura.")
            else:
                df_notas.update(df_editado)
                novos_indices = [idx for idx in df_editado.index if idx not in df_notas.index]
                if novos_indices:
                    novas_linhas = df_editado.loc[novos_indices]
                    novas_linhas = novas_linhas.reindex(columns=df_notas.columns)
                    df_notas = pd.concat([df_notas, novas_linhas])
                
                for col in colunas_data:
                    if col in df_notas.columns:
                        df_notas[col] = pd.to_datetime(df_notas[col], errors='coerce').dt.strftime('%d/%m/%Y').fillna("")
                
                save_notas_to_db(df_notas)
                st.success("✅ Edições salvas com sucesso no banco de dados!")
                st.rerun()

        with col_adv.popover("⚙️ Configurações Avançadas", use_container_width=True):
            st.markdown("**Área de Risco**")
            st.info("Ações aqui afetam toda a base de dados oficial.")
            if st.button("🗑️ Apagar Base Inteira", type="secondary", use_container_width=True, key="btn_del_gov"):
                if st.session_state.perfil_usuario != "ADMIN":
                    st.error("Acesso Negado: Apenas ADMINS podem limpar a base.")
                else:
                    save_notas_to_db(pd.DataFrame(columns=colunas_template), backup=True)
                    st.success("✅ Banco de dados limpo! A estrutura original foi preservada.")
                    st.rerun()

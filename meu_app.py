st.plotly_chart(fig_rosca_mun, use_container_width=True)
            
        with col_g2:
            df_sem_levantador = df_notas_calc[df_notas_calc['LEVANTADOR'] == 'SEM LEVANTADOR']
            df_sem_lev_reg = df_sem_levantador['REGIONAL'].value_counts().reset_index()
            df_sem_lev_reg.columns = ['Regional', 'Quantidade_Sem_Atribuicao']
            fig_rosca_sem_lev = px.pie(df_sem_lev_reg, names='Regional', values='Quantidade_Sem_Atribuicao',
                                       title="Obras Sem Levantador Atribuído por Regional",
                                       hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_rosca_sem_lev.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5))
            st.plotly_chart(fig_rosca_sem_lev, use_container_width=True)

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

        # AJUSTE 3: Altura do mapa aumentada de 550 para 750
        mapa_pronto = construir_mapa(df_equipes_db, df_notas_calc, tuple(levantadores_criticos))
        st_folium(mapa_pronto, use_container_width=True, height=750, returned_objects=[])

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

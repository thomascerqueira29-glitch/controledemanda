import streamlit as st
import pandas as pd
import io
from database import load_core_data, save_notas_to_db

def render_filtros_governanca(df_notas):
    col_f1, col_f2, col_f3 = st.columns(3)
    col_f4, col_f5, col_f6 = st.columns(3)
    
    op_lev = ["TODOS"] + sorted([str(x) for x in df_notas['LEVANTADOR'].unique()])
    if 'ui_lev' not in st.session_state or st.session_state.ui_lev not in op_lev: st.session_state.ui_lev = 'TODOS'
    with col_f1: filtro_lev = st.selectbox("Filtrar por Levantador:", op_lev, key='ui_lev')

    op_reg = ["TODOS"] + sorted([str(x) for x in df_notas['REGIONAL'].unique()])
    if 'ui_reg' not in st.session_state or st.session_state.ui_reg not in op_reg: st.session_state.ui_reg = 'TODOS'
    with col_f2: filtro_reg = st.selectbox("Filtrar por Regional:", op_reg, key='ui_reg')

    op_mun = ["TODOS"] + sorted([str(x) for x in df_notas['MUNICIPIO'].unique()])
    if 'ui_mun' not in st.session_state or st.session_state.ui_mun not in op_mun: st.session_state.ui_mun = 'TODOS'
    with col_f3: filtro_mun = st.selectbox("Filtrar por Município:", op_mun, key='ui_mun')

    op_lig = ["TODOS"] + sorted([str(x) for x in df_notas['TIPO LIGACAO'].unique()])
    if 'ui_lig' not in st.session_state or st.session_state.ui_lig not in op_lig: st.session_state.ui_lig = 'TODOS'
    with col_f4: filtro_lig = st.selectbox("Filtrar por Tipo Ligação:", op_lig, key='ui_lig')

    op_sap = ["TODOS"] + sorted([str(x) for x in df_notas['STATUS SAP'].unique()])
    if 'ui_sap' not in st.session_state or st.session_state.ui_sap not in op_sap: st.session_state.ui_sap = 'TODOS'
    with col_f5: filtro_sap = st.selectbox("Filtrar por Status SAP:", op_sap, key='ui_sap')

    op_list = sorted([str(x) for x in df_notas['STATUS LIST'].unique() if str(x).strip() != ""])
    if 'ui_list' not in st.session_state: st.session_state.ui_list = []
    st.session_state.ui_list = [x for x in st.session_state.ui_list if x in op_list]
    with col_f6: filtro_list = st.multiselect("Filtrar por Status List (Vazio = TODOS):", options=op_list, key='ui_list')

    df_filtrado = df_notas.copy()
    if filtro_lev != "TODOS": df_filtrado = df_filtrado[df_filtrado['LEVANTADOR'] == filtro_lev]
    if filtro_reg != "TODOS": df_filtrado = df_filtrado[df_filtrado['REGIONAL'] == filtro_reg]
    if filtro_mun != "TODOS": df_filtrado = df_filtrado[df_filtrado['MUNICIPIO'] == filtro_mun]
    if filtro_lig != "TODOS": df_filtrado = df_filtrado[df_filtrado['TIPO LIGACAO'].astype(str) == filtro_lig]
    if filtro_sap != "TODOS": df_filtrado = df_filtrado[df_filtrado['STATUS SAP'] == filtro_sap]
    if len(filtro_list) > 0: df_filtrado = df_filtrado[df_filtrado['STATUS LIST'].isin(filtro_list)]
    
    return df_filtrado, filtro_list, op_sap, op_list

def view_governanca():
    st.markdown("### 📝 Governança Direta")
    df_notas_db, _, _, _, _, _, _, _ = load_core_data()
    df_f, l1, l2, l3 = render_filtros_governanca(df_notas_db)
    st.info(f"Localizadas: {len(df_f)} notas.")
    
    c_btn1, c_btn2, c_btn3 = st.columns([2, 2, 6])
    if not df_f.empty:
        buf = io.BytesIO()
        df_f.to_excel(buf, index=False)
        c_btn1.download_button("📥 Excel", data=buf.getvalue(), file_name="gov_filtro.xlsx", use_container_width=True)
        
    admin = st.session_state.perfil_usuario == "ADMIN"
    btn_save = c_btn2.button("💾 Salvar DB", type="primary", use_container_width=True) if admin else c_btn2.button("🔒 Restrito", disabled=True, use_container_width=True)
    if admin:
        with c_btn3.expander("⚠️ ÁREA DE PERIGO"):
            if st.button("🚨 APAGAR TUDO", type="primary", disabled=not st.checkbox("Confirmo")):
                save_notas_to_db(pd.DataFrame(columns=df_notas_db.columns), backup=True); st.rerun()
                
    df_edit = st.data_editor(df_f.fillna(""), use_container_width=True, num_rows="dynamic", disabled=not admin,
                             column_config={"ID SISCO": st.column_config.TextColumn(disabled=True), "STATUS SAP": st.column_config.SelectboxColumn(options=l2), "STATUS LIST": st.column_config.SelectboxColumn(options=l3)})
    if btn_save:
        df_up = df_notas_db.copy(); df_up.loc[df_edit.index] = df_edit
        if save_notas_to_db(df_up, acao_auditoria="Edição Governança"): st.toast("Salvo!"); load_core_data.clear(); st.rerun()

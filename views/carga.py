import streamlit as st
import pandas as pd
import pandera as pa
from database import load_core_data, save_notas_to_db, SEM_LEVANTADOR

def view_carga():
    if st.session_state.perfil_usuario != "ADMIN": st.error("Restrito."); return
    st.markdown("### 📤 Importação Strict")
    s_nip = pa.DataFrameSchema({"PROTOCOLO": pa.Column(pa.String, coerce=True, required=True), "MUNICIPIO": pa.Column(pa.String, coerce=True, required=True)}, strict=False)
    upl = st.file_uploader("Lote de Demandas", type=["csv", "xlsx"])
    if upl:
        df_n = pd.read_csv(upl) if upl.name.endswith('.csv') else pd.read_excel(upl)
        df_n = df_n.dropna(subset=['MUNICIPIO', 'PROTOCOLO']).copy()
        df_n['PROTOCOLO'] = df_n['PROTOCOLO'].astype(str).str.replace(r'\.0$', '', regex=True)
        try:
            df_v = s_nip.validate(df_n)
            st.success("Homologado!")
            
            df_notas_db, df_equipes_db, _, _, _, _, _, _ = load_core_data()
            
            df_proc = df_v.copy()
            map_levs = df_equipes_db.dropna(subset=['Município']).drop_duplicates(subset=['Município']).set_index('Município')['Levantador'].to_dict()
            if 'MUNICIPIO' in df_proc.columns: df_proc['MUNICIPIO'] = df_proc['MUNICIPIO'].astype(str).str.upper().str.strip()
            if 'LEVANTADOR' not in df_proc.columns: df_proc['LEVANTADOR'] = SEM_LEVANTADOR
            
            m_vazio = df_proc['LEVANTADOR'].isna() | df_proc['LEVANTADOR'].isin(['', 'NAN', 'NONE', '0'])
            df_proc.loc[m_vazio, 'LEVANTADOR'] = df_proc.loc[m_vazio, 'MUNICIPIO'].map(map_levs).fillna(SEM_LEVANTADOR)
            
            for col in ['STATUS LIST', 'DATA ENVIO A CAMPO - LIST', 'DATA DE LEVANTAMENTO LIST', 'STATUS SISCO', 'DATA CRIAÇAO SISCO', 'DATA DE VENCIMENTO']:
                if col not in df_proc.columns: df_proc[col] = ""
                    
            df_proc['STATUS LIST'] = df_proc['STATUS LIST'].astype(str).str.upper().str.strip()
            
            if st.button("⚡ Gravar DB"):
                if save_notas_to_db(pd.concat([df_notas_db, df_proc], ignore_index=True), backup=True): st.rerun()
        except Exception as e: st.error(f"Erro no Lote: {e}")

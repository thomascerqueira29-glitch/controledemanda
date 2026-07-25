import streamlit as st
import pandas as pd
import time
import io
import sqlite3
from database import DB_PATH

def view_carga():
    # =====================================================================
    # 1. CABEÇALHO E DOWNLOAD DE TEMPLATE
    # =====================================================================
    st.markdown("### ☁️ Carga de Lotes (Dropzone)")
    st.markdown("Carregue a sua base de obras atualizada. O sistema aceita formatos Excel (.xlsx) ou Texto Separado por Vírgulas (.csv).")
    st.markdown("<br>", unsafe_allow_html=True)

    # Definição das colunas da regra Strict atualizada para o Template Bot
    colunas_oficiais = [
        'ID SISCO', 'PAT', 'STATUS SAP', 'STATUS LIST', 'NOME', 'ENDEREÇO', 
        'INFORMAÇÕES EXTRAS', 'PROTOCOLO', 'TIPO NOTA', 'LOCALIDADE', 'REGIONAL', 
        'MUNICIPIO', 'Descrição', 'INICIO AVARIA', 'LATITUDE', 'LONGITUDE', 
        'STATUS ATUAL (LEVANTAMENTO)'
    ]

    # Gera o arquivo de modelo em memória na hora
    df_template = pd.DataFrame(columns=colunas_oficiais)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_template.to_excel(writer, index=False, sheet_name='TEMPLATE_STRICT')
    
    col_texto, col_botao = st.columns([2.5, 1.5])
    with col_texto:
        st.info("⚠️ **Atenção (Regra Strict):** O arquivo enviada irá **substituir totalmente** a base anterior, garantindo que os números do painel reflitam apenas a carga atual.")
    with col_botao:
        st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
        st.download_button(
            label="📥 Baixar Modelo de Planilha",
            data=buffer.getvalue(),
            file_name="template_bot.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # =====================================================================
    # 2. DROPZONE MODERNA E FEEDBACK VISUAL
    # =====================================================================
    with st.container(border=True):
        st.markdown("<h4 style='text-align: center; color: #1A4F7C; margin-bottom: 5px;'>Arraste e solte seu arquivo aqui</h4>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #666; font-size: 14px; margin-bottom: 20px;'>Ou clique em 'Browse files' para buscar no seu computador.<br><b>Limite: Até 200MB por arquivo</b></p>", unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader("", type=['xlsx', 'csv'], label_visibility="collapsed")

        if uploaded_file is not None:
            st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
            st.markdown(f"📄 **Arquivo selecionado:** `{uploaded_file.name}`")
            
            if st.button("🚀 Enviar e Substituir Base Oficial", type="primary", use_container_width=True):
                progress_bar = st.progress(0, text="⏳ Iniciando leitura do arquivo...")
                
                try:
                    time.sleep(0.3)
                    progress_bar.progress(30, text="⚙️ Processando matriz de dados...")
                    
                    if uploaded_file.name.endswith('.csv'):
                        df_new = pd.read_csv(uploaded_file, encoding='utf-8', sep=';')
                    else:
                        df_new = pd.read_excel(uploaded_file)
                    
                    progress_bar.progress(60, text="🔎 Executando validação de colunas (Regra Strict)...")
                    time.sleep(0.4)
                    
                    # Verificador de Colunas
                    missing_cols = [c for c in colunas_oficiais if c not in df_new.columns]
                    
                    if missing_cols:
                        progress_bar.empty()
                        st.error(f"❌ **Falha na Validação (Arquivo Inválido)**")
                        st.markdown(f"O seu arquivo está sem as seguintes colunas obrigatórias: \n`{', '.join(missing_cols)}`")
                        st.warning("Dica: Baixe o Modelo de Planilha acima e cole seus dados nele para garantir compatibilidade.")
                    else:
                        progress_bar.progress(85, text="💾 Substituindo registros no Banco de Dados Oficial...")
                        
                        # Trava de segurança para a coluna LEVANTADOR caso não exista no template novo
                        if 'LEVANTADOR' not in df_new.columns:
                            df_new['LEVANTADOR'] = "SEM LEVANTADOR"
                            
                        # Salva usando REPLACE para nunca acumular lixo ou duplicar dados antigos
                        with sqlite3.connect(DB_PATH, timeout=20) as conn:
                            df_new.to_sql('notas', conn, if_exists='replace', index=False)
                        
                        progress_bar.progress(100, text="✅ Importação concluída!")
                        time.sleep(0.3)
                        progress_bar.empty()
                        
                        st.success(f"🎉 **Sucesso!** A base anterior foi substituída. O novo lote com exatamente {len(df_new)} obras já está sincronizado com o Painel Executivo e a Governança.")
                
                except Exception as e:
                    progress_bar.empty()
                    st.error(f"❌ **Erro crítico ao ler o arquivo:** {e}")

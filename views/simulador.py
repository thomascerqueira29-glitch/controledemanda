import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from database import load_core_data, SEM_LEVANTADOR, STATUS_PRODUTIVIDADE

def view_simulador():
    st.markdown("### 🧮 Simulador de Alocação de Equipes")
    st.markdown("Otimize a distribuição de levantadores e preveja a cobertura das regionais em tempo real.")
    
    # =====================================================================
    # 1. CARREGAMENTO DOS DADOS
    # =====================================================================
    df_notas, df_equipes, resumo_lev, criticos, todos_levs, _, _, _ = load_core_data()
    
    if df_notas.empty:
        st.warning("Banco de dados vazio. Importe uma base para começar as simulações.")
        return

    # Extração de Métricas Chaves
    total_obras = len(df_notas)
    total_municipios = df_notas['MUNICIPIO'].nunique()
    
    # Considera obras ativas para a simulação de produtividade
    if 'STATUS LIST' in df_notas.columns:
        df_ativas = df_notas[df_notas['STATUS LIST'].astype(str).str.upper().isin([s.upper() for s in STATUS_PRODUTIVIDADE])].copy()
    else:
        df_ativas = df_notas.copy()
    
    obras_livres_total = len(df_ativas[df_ativas['LEVANTADOR'] == SEM_LEVANTADOR])
    obras_cobertas_total = len(df_ativas[df_ativas['LEVANTADOR'] != SEM_LEVANTADOR])
    cobertura_geral_atual = (obras_cobertas_total / len(df_ativas) * 100) if len(df_ativas) > 0 else 0

    # =====================================================================
    # 2. CARDS DE INDICADORES (KPIs)
    # =====================================================================
    def kpi_card(title, value, icon, color):
        return f"""
        <div style="background-color: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-left: 6px solid {color}; height: 100%; border: 1px solid #f0f2f6;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <p style="margin:0; font-size: 13px; color: #6c757d; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">{title}</p>
                <span style="font-size: 22px;">{icon}</span>
            </div>
            <h2 style="margin: 10px 0 0 0; color: #1e1e1e; font-size: 38px; font-weight: 800;">{value}</h2>
        </div>
        """
        
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi_card("Total Municípios", f"{total_municipios}", "🗺️", "#3b82f6"), unsafe_allow_html=True) 
    c2.markdown(kpi_card("Total Obras Ativas", f"{len(df_ativas)}", "🏗️", "#8b5cf6"), unsafe_allow_html=True) 
    c3.markdown(kpi_card("Gap Atual (Livres)", f"{obras_livres_total}", "⚠️", "#f59e0b"), unsafe_allow_html=True) 
    c4.markdown(kpi_card("Cobertura Atual", f"{cobertura_geral_atual:.1f}%", "🎯", "#10b981"), unsafe_allow_html=True) 
    st.markdown("<br><br>", unsafe_allow_html=True)

    # =====================================================================
    # 3. ARQUITETURA DA INFORMAÇÃO: TABELA UNIFICADA INTERATIVA
    # =====================================================================
    st.markdown("<h4 style='color: #1A4F7C;'>🛠️ Simulação de Cenários por Regional</h4>", unsafe_allow_html=True)
    st.info("💡 **Dica:** Dê um duplo clique na coluna `Novos Levantadores` para simular contratações. Os resultados são recalculados em tempo real na própria linha.")
    
    # Agrupamento de obras livres e totais por regional
    df_reg = df_ativas.groupby('REGIONAL').agg(
        Total_Obras=('PROTOCOLO', 'count'),
        Obras_Livres=('LEVANTADOR', lambda x: (x == SEM_LEVANTADOR).sum())
    ).reset_index()
    
    # ---------------------------------------------------------------------
    # CORREÇÃO DA FORÇA DE TRABALHO ATUAL
    # Agora a contagem é feita olhando para a lista OFICIAL de equipes (df_equipes)
    # garantindo que os números batam com a estrutura fixa (5, 3, 2, 2, 3)
    # ---------------------------------------------------------------------
    if not df_equipes.empty:
        # Identifica a coluna correta de regional na base oficial
        col_reg_eq = 'Regional' if 'Regional' in df_equipes.columns else 'REGIONAL' if 'REGIONAL' in df_equipes.columns else None
        
        if col_reg_eq and 'Levantador' in df_equipes.columns:
            df_eq_clean = df_equipes.dropna(subset=['Levantador', col_reg_eq])
            df_eq_clean = df_eq_clean[df_eq_clean['Levantador'].astype(str).str.strip() != '']
            
            equipes_por_regional = df_eq_clean.groupby(col_reg_eq)['Levantador'].nunique().reset_index()
            equipes_por_regional.columns = ['REGIONAL', 'Equipes Atuais']
            equipes_por_regional['REGIONAL'] = equipes_por_regional['REGIONAL'].astype(str).str.upper()
        else:
            equipes_por_regional = pd.DataFrame(columns=['REGIONAL', 'Equipes Atuais'])
    else:
        equipes_por_regional = pd.DataFrame(columns=['REGIONAL', 'Equipes Atuais'])
    
    # Cruza as informações das obras com as equipes oficiais
    df_reg['REGIONAL'] = df_reg['REGIONAL'].astype(str).str.upper()
    df_reg = pd.merge(df_reg, equipes_por_regional, on='REGIONAL', how='left')
    df_reg['Equipes Atuais'] = df_reg['Equipes Atuais'].fillna(0).astype(int)
    # ---------------------------------------------------------------------

    df_reg['Obras_Cobertas'] = df_reg['Total_Obras'] - df_reg['Obras_Livres']
    
    # Inicia a memória de simulação caso não exista
    if 'sim_inputs' not in st.session_state:
        st.session_state.sim_inputs = {reg: 0 for reg in df_reg['REGIONAL']}
        
    # Sincroniza dados novos com a memória
    for reg in df_reg['REGIONAL']:
        if reg not in st.session_state.sim_inputs:
            st.session_state.sim_inputs[reg] = 0
            
    # Alimenta o DataFrame com as edições do usuário
    df_reg['Novos Levantadores'] = df_reg['REGIONAL'].map(st.session_state.sim_inputs).fillna(0).astype(int)
    
    # Projeções Matemáticas
    META_POR_LEVANTADOR = 45 
    df_reg['Projeção'] = df_reg['Obras_Cobertas'] + (df_reg['Novos Levantadores'] * META_POR_LEVANTADOR)
    
    df_reg['Gap Restante'] = np.maximum(0, df_reg['Total_Obras'] - df_reg['Projeção'])
    df_reg['Cobertura %'] = np.minimum(100, (df_reg['Projeção'] / df_reg['Total_Obras']) * 100)
    
    # Prepara visualização limpa
    df_display = df_reg[['REGIONAL', 'Total_Obras', 'Equipes Atuais', 'Obras_Livres', 'Novos Levantadores', 'Gap Restante', 'Cobertura %']].copy()
    df_display.rename(columns={'Total_Obras': 'Total Obras', 'Obras_Livres': 'Gap Atual'}, inplace=True)
    
    # Componente de Data Editor Moderno
    edited_df = st.data_editor(
        df_display,
        column_config={
            "REGIONAL": st.column_config.TextColumn("Regional", disabled=True),
            "Total Obras": st.column_config.NumberColumn("Total Obras", disabled=True),
            "Equipes Atuais": st.column_config.NumberColumn("Equipes Atuais", disabled=True, help="Lista oficial de equipes fixas cadastradas no sistema para esta regional"),
            "Gap Atual": st.column_config.NumberColumn("Gap Atual", disabled=True),
            "Novos Levantadores": st.column_config.NumberColumn(
                "✏️ Novos Levantadores (Input)", 
                min_value=0, 
                step=1,
                help="Insira a quantidade de novas equipes/levantadores que você deseja alocar"
            ),
            "Gap Restante": st.column_config.NumberColumn("Gap Restante", disabled=True),
            "Cobertura %": st.column_config.ProgressColumn(
                "Cobertura Projetada %", 
                format="%.1f%%", 
                min_value=0, 
                max_value=100
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="simulador_editor_ativo"
    )
    
    # Feedback visual rápido
    needs_rerun = False
    for index, row in edited_df.iterrows():
        reg = row['REGIONAL']
        novo_val = row['Novos Levantadores']
        if st.session_state.sim_inputs.get(reg) != novo_val:
            st.session_state.sim_inputs[reg] = novo_val
            needs_rerun = True
            
    if needs_rerun:
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # =====================================================================
    # 4. VISUALIZAÇÃO DE DADOS: GRÁFICO HORIZONTAL
    # =====================================================================
    st.markdown("<h4 style='color: #1A4F7C;'>📊 Análise de Gap Projetado por Regional</h4>", unsafe_allow_html=True)
    
    col_chart, col_summary = st.columns([2.5, 1.5])
    
    with col_chart:
        df_chart = edited_df.copy()
        df_chart = df_chart.sort_values('Gap Restante', ascending=True) 
        
        fig = px.bar(
            df_chart, 
            x='Gap Restante', 
            y='REGIONAL', 
            orientation='h',
            text='Gap Restante',
            color='Gap Restante',
            color_continuous_scale=px.colors.sequential.Reds,
            labels={'Gap Restante': 'Obras Descobertas', 'REGIONAL': ''}
        )
        
        fig.update_traces(textposition='outside')
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', 
            paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=20, b=0),
            coloraxis_showscale=False,
            xaxis=dict(showgrid=True, gridcolor='#e5e7eb'),
            yaxis=dict(showgrid=False)
        )
        st.plotly_chart(fig, use_container_width=True)
        
    with col_summary:
        st.markdown("<div style='padding-top: 15px;'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("#### 📝 Resumo da Simulação")
            
            total_equipes_atuais = edited_df['Equipes Atuais'].sum()
            total_novos = edited_df['Novos Levantadores'].sum()
            gap_original = edited_df['Gap Atual'].sum()
            gap_projetado = edited_df['Gap Restante'].sum()
            
            reducao = gap_original - gap_projetado
            
            st.markdown(f"**Equipes Atuais (Base):** `{total_equipes_atuais}` técnicos")
            st.markdown(f"**Novas Contratações:** `{total_novos}` técnicos")
            st.markdown(f"**Obras Resgatadas:** `{reducao}`")
            st.markdown(f"**Gap Final (Pendentes):** `{gap_projetado}` obras")
            
            if gap_projetado == 0 and gap_original > 0:
                st.success("✨ Excelente! O cenário atinge 100% de cobertura.")
            elif gap_projetado < gap_original:
                st.info(f"Este cenário reduz o seu Gap atual em {((reducao/gap_original)*100):.1f}%.")
            else:
                st.warning("Insira técnicos na tabela para projetar o cenário.")

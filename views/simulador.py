import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from database import load_core_data, get_base_levantadores, save_base_levantadores, get_equipes_base_simulador, save_equipes_base_simulador, STATUS_PRODUTIVIDADE

def view_simulador():
    st.markdown("### 🧮 Simulador de Alocação de Equipes e Gestão de Território")
    st.markdown("Otimize a distribuição de levantadores e defina as áreas de atuação.")
    
    # =====================================================================
    # 1. CARREGAMENTO DOS DADOS GERAIS E MEMÓRIA
    # =====================================================================
    df_notas, _, _, _, todos_levs, _, _, _ = load_core_data()
    df_equipes_territorio = get_base_levantadores() 
    
    if df_notas.empty or df_equipes_territorio.empty:
        st.warning("Importe a Base de Obras e a Planilha de Levantadores na Carga de Lotes para usar este módulo.")
        return

    # Filtro Anti-Lixo da Regional
    lixos_reg = ['0', '0.0', 'NAN', 'NONE', '', '<NA>']
    df_notas_validas = df_notas[~df_notas['REGIONAL'].astype(str).str.strip().str.upper().isin(lixos_reg)].copy()

    # =====================================================================
    # 2. MOTOR DE SIMULAÇÃO 
    # =====================================================================
    df_reg = df_notas_validas.groupby('REGIONAL').agg(Total_Obras=('PROTOCOLO', 'count')).reset_index()
    
    df_eq_clean = df_equipes_territorio.copy()
    col_lev = 'Levantador' if 'Levantador' in df_eq_clean.columns else 'LEVANTADOR'
    col_reg_eq = 'Regional' if 'Regional' in df_eq_clean.columns else 'REGIONAL'
    
    mun_total_reg = df_eq_clean.groupby(col_reg_eq).size().reset_index(name='Total Municípios')
    mun_total_reg['REGIONAL'] = mun_total_reg[col_reg_eq].astype(str).str.upper()
    if col_reg_eq != 'REGIONAL':
        mun_total_reg = mun_total_reg.drop(columns=[col_reg_eq])
    
    df_eq_livres = df_eq_clean[df_eq_clean[col_lev].astype(str).str.strip().str.upper() == 'SEM LEVANTADOR']
    mun_livres_reg = df_eq_livres.groupby(col_reg_eq).size().reset_index(name='Gap Atual (Munc)')
    mun_livres_reg['REGIONAL'] = mun_livres_reg[col_reg_eq].astype(str).str.upper()
    if col_reg_eq != 'REGIONAL':
        mun_livres_reg = mun_livres_reg.drop(columns=[col_reg_eq])
    
    df_reg['REGIONAL'] = df_reg['REGIONAL'].astype(str).str.upper()
    
    df_reg = pd.merge(df_reg, mun_total_reg, on='REGIONAL', how='left')
    df_reg['Total Municípios'] = df_reg['Total Municípios'].fillna(0).astype(int)
    
    df_reg = pd.merge(df_reg, mun_livres_reg, on='REGIONAL', how='left')
    df_reg['Gap Atual (Munc)'] = df_reg['Gap Atual (Munc)'].fillna(0).astype(int)
    
    # -----------------------------------------------------------------
    # INJEÇÃO DA MEMÓRIA PERSISTENTE DO BANCO (Ocorre a cada login)
    # -----------------------------------------------------------------
    equipes_salvas = get_equipes_base_simulador()
    
    if 'sim_atuais' not in st.session_state:
        st.session_state.sim_atuais = {reg: equipes_salvas.get(reg, 0) for reg in df_reg['REGIONAL']}
    if 'sim_novos' not in st.session_state:
        st.session_state.sim_novos = {reg: 0 for reg in df_reg['REGIONAL']}
        
    for reg in df_reg['REGIONAL']:
        if reg not in st.session_state.sim_atuais: st.session_state.sim_atuais[reg] = equipes_salvas.get(reg, 0)
        if reg not in st.session_state.sim_novos: st.session_state.sim_novos[reg] = 0
            
    df_reg['Equipes Atuais'] = df_reg['REGIONAL'].map(st.session_state.sim_atuais).fillna(0).astype(int)
    df_reg['Novos Levantadores'] = df_reg['REGIONAL'].map(st.session_state.sim_novos).fillna(0).astype(int)
    
    # Projeção Matemática Dinâmica da Cobertura
    META_MUNICIPIOS_POR_EQUIPE = 10 
    df_reg['Capacidade Adicional'] = df_reg['Novos Levantadores'] * META_MUNICIPIOS_POR_EQUIPE
    df_reg['Gap Restante'] = np.maximum(0, df_reg['Gap Atual (Munc)'] - df_reg['Capacidade Adicional'])
    
    df_reg['Mun Cobertos Projetado'] = df_reg['Total Municípios'] - df_reg['Gap Restante']
    df_reg['Cobertura %'] = np.where(
        df_reg['Total Municípios'] == 0, 
        0, 
        np.minimum(100, (df_reg['Mun Cobertos Projetado'] / df_reg['Total Municípios']) * 100)
    )

    # =====================================================================
    # 3. CARDS DE INDICADORES
    # =====================================================================
    total_municipios = df_equipes_territorio['Município'].nunique() if 'Município' in df_equipes_territorio.columns else 217
    total_obras = len(df_notas_validas)
    
    mun_livres_projetado = df_reg['Gap Restante'].sum()
    mun_cobertos_projetado = total_municipios - mun_livres_projetado
    cobertura_projetada = (mun_cobertos_projetado / total_municipios * 100) if total_municipios > 0 else 0

    def kpi_card(title, value, icon, color):
        return f"""
        <div style="background-color: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-left: 6px solid {color}; height: 100%; border: 1px solid #f0f2f6;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <p style="margin:0; font-size: 11px; color: #6c757d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">{title}</p>
                <span style="font-size: 20px;">{icon}</span>
            </div>
            <h2 style="margin: 10px 0 0 0; color: #1e1e1e; font-size: 34px; font-weight: 800;">{value}</h2>
        </div>
        """
        
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(kpi_card("Total Municípios", f"{total_municipios}", "🗺️", "#3b82f6"), unsafe_allow_html=True) 
    c2.markdown(kpi_card("Mun. Cobertos", f"{int(mun_cobertos_projetado)}", "✅", "#10b981"), unsafe_allow_html=True) 
    c3.markdown(kpi_card("Mun. Livres (Gap)", f"{int(mun_livres_projetado)}", "⚠️", "#f59e0b"), unsafe_allow_html=True) 
    c4.markdown(kpi_card("Cobertura", f"{cobertura_projetada:.1f}%", "🎯", "#8b5cf6"), unsafe_allow_html=True) 
    c5.markdown(kpi_card("Obras (Geral)", f"{total_obras}", "🏗️", "#ef4444"), unsafe_allow_html=True) 
    st.markdown("<br><br>", unsafe_allow_html=True)

    # =====================================================================
    # 4. TABELA UNIFICADA INTERATIVA E GRÁFICO ROSCA (DONUT)
    # =====================================================================
    st.markdown("<h4 style='color: #1A4F7C;'>🛠️ Simulação de Contratações por Regional</h4>", unsafe_allow_html=True)
    st.info("Insira o número de Equipes Atuais na sua operação e preveja a cobertura no campo 'Novos Levantadores'. (Pressione ENTER após digitar)")
    
    df_display = df_reg[['REGIONAL', 'Total_Obras', 'Equipes Atuais', 'Gap Atual (Munc)', 'Novos Levantadores', 'Gap Restante', 'Cobertura %']].copy()
    df_display.rename(columns={'Total_Obras': 'Total Obras (Geral)'}, inplace=True)
    
    total_mun_estado = df_reg['Total Municípios'].sum()
    gap_atual_total = df_display['Gap Atual (Munc)'].sum()
    gap_restante_total = df_display['Gap Restante'].sum()
    
    mun_cobertos_estado = total_mun_estado - gap_restante_total
    cobertura_total_pond = 0 if total_mun_estado == 0 else min(100, (mun_cobertos_estado / total_mun_estado) * 100)
    
    linha_total = pd.DataFrame([{
        'REGIONAL': 'TOTAL ESTADO',
        'Total Obras (Geral)': df_display['Total Obras (Geral)'].sum(),
        'Equipes Atuais': df_display['Equipes Atuais'].sum(),
        'Gap Atual (Munc)': gap_atual_total,
        'Novos Levantadores': df_display['Novos Levantadores'].sum(),
        'Gap Restante': gap_restante_total,
        'Cobertura %': cobertura_total_pond
    }])
    
    df_display = pd.concat([df_display, linha_total], ignore_index=True)
    
    col_tabela, col_grafico = st.columns([2.6, 1.2]) 
    
    with col_tabela:
        edited_df = st.data_editor(
            df_display,
            column_config={
                "REGIONAL": st.column_config.TextColumn("Regional", disabled=True),
                "Total Obras (Geral)": st.column_config.NumberColumn("Total Obras", disabled=True),
                "Equipes Atuais": st.column_config.NumberColumn("✏️ Eq. Atuais", min_value=0, step=1),
                "Gap Atual (Munc)": st.column_config.NumberColumn("Gap Inicial", disabled=True),
                "Novos Levantadores": st.column_config.NumberColumn("✏️ Novos", min_value=0, step=1),
                "Gap Restante": st.column_config.NumberColumn("Gap Final", disabled=True),
                "Cobertura %": st.column_config.ProgressColumn("Cobertura", format="%.1f%%", min_value=0, max_value=100),
            },
            hide_index=True,
            use_container_width=True,
            key="simulador_editor"
        )
        
        # -------------------------------------------------------------
        # BOTÃO SALVAR CENÁRIO DE EQUIPES COM PROTEÇÃO DE SENHA
        # -------------------------------------------------------------
        st.markdown("<br>", unsafe_allow_html=True)
        col_btn1, col_btn2 = st.columns([1.5, 3])
        with col_btn1.popover("💾 Salvar Equipes como Padrão", use_container_width=True):
            st.markdown("**🔒 Autenticação Necessária**")
            st.info("Esses números serão carregados automaticamente no próximo login.")
            
            user_auth = st.text_input("Usuário", placeholder="Ex: ADMIN")
            pass_auth = st.text_input("Senha", type="password")
            
            if st.button("Confirmar e Gravar", type="primary", use_container_width=True):
                # O botão tenta gravar usando a memória RAM de st.session_state.sim_atuais
                if save_equipes_base_simulador(st.session_state.sim_atuais, user_auth, pass_auth):
                    st.success("✅ Cenário salvo com sucesso!")
                else:
                    st.error("❌ Usuário ou Senha incorretos.")

    with col_grafico:
        # Gráfico Rosca/Donut das Regionais (Excluindo a linha de Total)
        df_plot = df_display[df_display['REGIONAL'] != 'TOTAL ESTADO'].copy()
        
        fig = px.pie(
            df_plot,
            values='Cobertura %',
            names='REGIONAL',
            hole=0.45,
            color_discrete_sequence=px.colors.sequential.Blues_r
        )
        
        # Força o Rótulo (Label) a mostrar a "% de Cobertura real" e não o tamanho da fatia da pizza
        fig.update_traces(
            texttemplate='<b>%{label}</b><br>%{value:.1f}%',
            textposition='outside',
            hovertemplate='<b>%{label}</b><br>Cobertura: %{value:.1f}%<extra></extra>'
        )
        
        fig.update_layout(
            title=dict(text="Cobertura Projetada", font=dict(size=14, color="#1A4F7C"), x=0.5),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=40, b=10),
            showlegend=False,
            height=300
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Loop de Atualização em Tempo Real 
    needs_rerun = False
    for index, row in edited_df.iterrows():
        reg = row['REGIONAL']
        if reg == 'TOTAL ESTADO': continue
            
        atuais = row['Equipes Atuais']
        novos = row['Novos Levantadores']
        
        if st.session_state.sim_atuais.get(reg) != atuais:
            st.session_state.sim_atuais[reg] = atuais
            needs_rerun = True
            
        if st.session_state.sim_novos.get(reg) != novos:
            st.session_state.sim_novos[reg] = novos
            needs_rerun = True
            
    if needs_rerun:
        st.rerun()

    st.markdown("<hr style='margin: 40px 0;'>", unsafe_allow_html=True)

    # =====================================================================
    # 5. GESTOR OFICIAL DE MUNICÍPIOS E LEVANTADORES (Planilha ao Vivo)
    # =====================================================================
    st.markdown("<h4 style='color: #1A4F7C;'>📍 Gestor de Atribuição de Território</h4>", unsafe_allow_html=True)
    st.markdown("Redistribua os 217 municípios do Maranhão atribuindo-os aos Levantadores reais ou deixando-os na fila (SEM LEVANTADOR). Ao salvar, **o Painel principal do sistema é atualizado instantaneamente.**")
    
    col_mun = 'Município' if 'Município' in df_equipes_territorio.columns else 'MUNICIPIO'
    
    opcoes_levs = ["SEM LEVANTADOR"] + sorted([str(x) for x in df_notas['LEVANTADOR'].unique() if pd.notna(x) and x.strip() != '' and str(x).upper() != 'SEM LEVANTADOR'])
    
    territorio_editado = st.data_editor(
        df_equipes_territorio,
        column_config={
            col_lev: st.column_config.SelectboxColumn(
                "Levantador Responsável",
                help="Escolha quem vai cobrir este município",
                options=opcoes_levs,
                required=True
            ),
            col_reg_eq: st.column_config.TextColumn("Regional", disabled=True),
            col_mun: st.column_config.TextColumn("Município", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        height=500,
        key="territorio_editor"
    )
    
    col_save, _, _ = st.columns([3, 5, 2])
    if col_save.button("💾 Salvar Novo Mapa de Território", type="primary", use_container_width=True):
        if st.session_state.perfil_usuario == "LEITURA":
            st.error("Acesso Negado: O seu perfil é apenas leitura.")
        else:
            save_base_levantadores(territorio_editado)
            st.success("✅ Territórios atualizados! O Painel Executivo já está refletindo o novo mapa.")
            st.rerun()

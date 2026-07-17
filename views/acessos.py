import streamlit as st
import pandas as pd
from database import get_session, Usuario, hash_senha

def view_acessos():
    if st.session_state.perfil_usuario != "ADMIN": st.error("Restrito."); return
    st.markdown("### 🔐 Controle de Acesso (ORM SQLAlchemy)")
    
    session = get_session()
    usuarios = session.query(Usuario).all()
    
    data = [{"username": u.username, "role": u.role, "Apagar": False} for u in usuarios]
    df_usr = pd.DataFrame(data)
    
    ed_usr = st.data_editor(df_usr, hide_index=True, use_container_width=True, 
                            column_config={"username": st.column_config.TextColumn(disabled=True), 
                                           "role": st.column_config.SelectboxColumn(options=["ADMIN", "LEITURA"])})
    
    if st.button("Salvar Permissões", type="primary"):
        for _, r in ed_usr.iterrows():
            usuario = session.query(Usuario).filter_by(username=r['username']).first()
            if r['Apagar'] and r['username'] != st.session_state.usuario_logado:
                session.delete(usuario)
            else:
                usuario.role = r['role']
        session.commit()
        session.close()
        st.rerun()

    # [Manter aqui a lógica de "Nova Conta" ajustada para session.add]
    with st.form("n_usr"):
        u = st.text_input("Usuário").upper()
        p = st.text_input("Senha", type="password")
        rol = st.selectbox("Perfil", ["LEITURA", "ADMIN"])
        if st.form_submit_button("Criar"):
            session.add(Usuario(username=u, password=hash_senha(p), role=rol))
            session.commit()
            session.close()
            st.rerun()

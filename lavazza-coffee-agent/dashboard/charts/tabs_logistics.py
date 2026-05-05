"""tabs_logistics.py — Render tab Porti & Trasporti (AIS + Comex transport modes)."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ._config import COLORS
from ._data_mongo import _mongo_ports, _mongo_comex
from ._data_sim import _sim_ports


def render_ports_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Tab congestione portuale: AIS snapshot + Comex transport modes."""
    port_data = _mongo_ports(country)
    is_simulated = port_data is None
    if is_simulated:
        port_data = _sim_ports()
        st.info("ℹ️ Dati AIS non disponibili in MongoDB — dati simulati. "
                "Avvia il workflow n8n **Port Congestion** per dati reali.")

    comex = _mongo_comex(country)

    total = port_data["total_anchored"]
    congested = port_data["congested_count"]
    top = port_data.get("top_congested_port")

    col1, col2, col3 = st.columns(3)
    col1.metric("Navi Ancorate Totali", total,
                help="Numero di navi ferme/ancorate nelle zone di attesa portuali (AIS snapshot).")
    col2.metric("Porti con Code", congested)
    if top and top.get("anchored_vessels_count", 0) > 0:
        col3.metric("Porto Più Congestionato",
                    top.get("port_name", "—"),
                    f"{top.get('anchored_vessels_count', 0)} navi")
    else:
        col3.metric("Congestione Porto Più Alto", "—", "Nessuna coda rilevata")

    if total == 0:
        st.success("✅ Nessuna coda rilevata nei porti monitorati.")
    elif total < 3:
        st.warning(f"⚠️ Leggera congestione: {total} navi ancorate.")
    elif total < 8:
        st.warning(f"⚠️ Congestione moderata: {total} navi ancorate in {congested} porto/i.")
    else:
        st.error(f"🔴 Congestione elevata: {total} navi ancorate — rischio ritardo esportazioni.")

    try:
        ports_list = port_data.get("ports", [])
        if ports_list:
            df_ports = pd.DataFrame(ports_list)
            name_col = next((c for c in ["port_name", "port", "name"] if c in df_ports.columns), None)
            anc_col = next((c for c in ["anchored_vessels_count", "anchored", "vessels"] if c in df_ports.columns), None)
            if name_col and anc_col:
                df_ports[anc_col] = pd.to_numeric(df_ports[anc_col], errors="coerce").fillna(0)
                df_ports = df_ports.sort_values(anc_col, ascending=False)
                bar_colors = [COLORS["danger"] if v >= 6 else COLORS["warning"] if v >= 3
                              else COLORS["safe"] if v > 0 else "#CCCCCC"
                              for v in df_ports[anc_col]]
                fig_ports = go.Figure(go.Bar(
                    x=df_ports[name_col], y=df_ports[anc_col],
                    marker_color=bar_colors,
                    text=df_ports[anc_col].astype(int),
                    textposition="outside",
                ))
                fig_ports.update_layout(
                    height=360, margin=dict(l=0, r=0, t=20, b=0),
                    yaxis=dict(title="Navi Ancorate", dtick=1),
                    xaxis=dict(title="Porto"),
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                fig_ports.add_hline(y=3, line_dash="dash", line_color=COLORS["warning"],
                                    annotation_text="Soglia moderata (3)")
                fig_ports.add_hline(y=6, line_dash="dash", line_color=COLORS["danger"],
                                    annotation_text="Soglia elevata (6)")
                st.plotly_chart(fig_ports, use_container_width=True, key=f"{key_prefix}_pc_24")
                st.caption(
                    "Numero di navi in attesa/ancorate per porto (snapshot AIS). "
                    "Verde = libero; arancio = moderato (≥3); rosso = elevato (≥6). "
                    "Code significative aumentano i tempi di spedizione di 1–3 giorni per nave."
                )

            sog_col = next((c for c in ["average_sog", "sog", "avg_sog"] if c in df_ports.columns), None)
            if sog_col:
                df_sog = df_ports[[name_col, sog_col]].copy()
                df_sog[sog_col] = pd.to_numeric(df_sog[sog_col], errors="coerce").fillna(0)
                fig_sog = px.bar(df_sog, x=name_col, y=sog_col,
                                 color=sog_col, color_continuous_scale="RdYlGn",
                                 labels={name_col: "Porto", sog_col: "SOG medio (nodi)"},
                                 title="Velocità Media SOG per Porto (nodi)")
                fig_sog.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_sog, use_container_width=True, key=f"{key_prefix}_pc_25")
                st.caption("SOG (Speed Over Ground): navi che si muovono lentamente (<1 nodo) indicano attesa attiva.")
    except Exception as e:
        st.warning(f"Errore grafico porti: {e}")

    if comex:
        tm = comex.get("transport_modes_latest") or (
            (comex.get("transport_series") or [{}])[-1].get("breakdown", [])
        )
        if tm:
            st.divider()
            st.markdown("### Modalità Trasporto Export — Comex Stat")
            try:
                df_tm = pd.DataFrame(tm)
                via_col = next((c for c in ["via", "transport_mode", "mode"] if c in df_tm.columns), None)
                fob_col = next((c for c in ["fob_usd", "share_fob_pct"] if c in df_tm.columns), None)
                kg_col = next((c for c in ["kg", "share_kg_pct"] if c in df_tm.columns), None)
                if via_col and (fob_col or kg_col):
                    metric_col = fob_col or kg_col
                    df_tm[metric_col] = pd.to_numeric(df_tm[metric_col], errors="coerce").fillna(0)
                    fig_tm = px.pie(df_tm, values=metric_col, names=via_col,
                                    hole=0.4,
                                    color_discrete_sequence=px.colors.qualitative.Pastel,
                                    title="Ripartizione per Modalità Trasporto")
                    fig_tm.update_layout(height=340, margin=dict(l=0, r=0, t=50, b=0))
                    st.plotly_chart(fig_tm, use_container_width=True, key=f"{key_prefix}_pc_26")
                    st.caption("Il trasporto marittimo domina le esportazioni di caffè brasiliano. "
                               "Fonte: Comex Stat, modalità di trasporto (via).")
            except Exception as e:
                st.warning(f"Errore grafico transport modes: {e}")

    summary = port_data.get("summary_en", "")
    if summary:
        with st.expander("📋 Riepilogo Snapshot AIS"):
            st.caption(summary)
            sigs = port_data.get("signals", [])
            if sigs:
                st.markdown("**Segnali rilevati:** " + ", ".join(f"`{s}`" for s in sigs))

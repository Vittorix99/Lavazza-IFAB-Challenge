"""tabs_environment.py — Render tab Clima/ENSO, Incendi, Precipitazioni."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ._config import COLORS, MONTH_NAMES
from ._data_sim import _make_climate, _states_prod_df
from ._loader import _load


def render_enso_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_1: ONI + SOI + heatmap."""
    oni_series = _load("oni", country, use_api)
    soi_series = _load("soi", country, use_api)

    def _safe_delta(s):
        return s.iloc[-1] - s.iloc[-2] if len(s) >= 2 else None

    latest_oni = oni_series.iloc[-1]
    latest_soi = soi_series.iloc[-1]
    oni_delta = _safe_delta(oni_series)
    soi_delta = _safe_delta(soi_series)

    if latest_oni >= 0.5:
        phase, color = "🔴 EL NIÑO", "red"
        advice = "Rischio siccità al Nord/Amazzonia; Piogge eccessive al Sud."
        if latest_soi <= -7:
            advice += " (⚠️ EVENTO ACCOPPIATO CONFERMATO)"
    elif latest_oni <= -0.5:
        phase, color = "🔵 LA NIÑA", "blue"
        advice = "Rischio siccità al Sud; Forti piogge al Nord."
        if latest_soi >= 7:
            advice += " (⚠️ EVENTO ACCOPPIATO CONFERMATO)"
    else:
        phase, color = "🟢 NEUTRALE", "green"
        advice = "Nessuna anomalia ENSO grave attiva."

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ONI (Indice Oceanico)", f"{latest_oni:.2f} °C",
              f"{oni_delta:+.2f} °C" if oni_delta is not None else None, delta_color="inverse")
    c2.metric("SOI (Indice Atmosferico)", f"{latest_soi:.2f}",
              f"{soi_delta:+.2f}" if soi_delta is not None else None)
    c3.markdown(
        f"**Fase Attuale:**<br><span style='color:{color}; font-size:1.4em; font-weight:bold;'>{phase}</span>",
        unsafe_allow_html=True,
    )
    c4.info(f"**Impatto Agronomico:** {advice}")

    if not use_api:
        st.info(
            "ℹ️ **SOI (Indice Atmosferico):** non è memorizzato nel database MongoDB. "
            "In modalità MongoDB viene mostrato un valore stimato/simulato. "
            "Per dati SOI reali, seleziona **API Diretta** nella barra laterale."
        )

    colA, colB = st.columns(2)
    try:
        with colA:
            st.markdown("#### Indice ONI (Oceanico)")
            oni_recent = oni_series.tail(36)
            x_vals = [f"{idx[0]}-{str(idx[1]).zfill(2)}" for idx in oni_recent.index]
            y_vals = oni_recent.values.tolist()

            fig_oni = go.Figure()
            fig_oni.add_trace(go.Scatter(
                x=x_vals + x_vals[::-1],
                y=[max(v, 0.5) for v in y_vals] + [0.5] * len(x_vals),
                fill="toself", fillcolor="rgba(220,50,50,0.25)",
                line=dict(width=0), hoverinfo="skip", showlegend=False,
            ))
            fig_oni.add_trace(go.Scatter(
                x=x_vals + x_vals[::-1],
                y=[min(v, -0.5) for v in y_vals] + [-0.5] * len(x_vals),
                fill="toself", fillcolor="rgba(50,100,220,0.25)",
                line=dict(width=0), hoverinfo="skip", showlegend=False,
            ))
            fig_oni.add_trace(go.Scatter(x=x_vals, y=y_vals, mode="lines+markers", name="ONI",
                                         line=dict(color="black", width=1.5), marker=dict(size=4)))
            fig_oni.add_hline(y=0.5, line_dash="dash", line_color="red",
                              annotation_text="El Niño (+0.5)")
            fig_oni.add_hline(y=-0.5, line_dash="dash", line_color="blue",
                              annotation_text="La Niña (-0.5)")
            fig_oni.update_yaxes(title_text="Anomalia Termica (°C)")
            fig_oni.update_xaxes(title_text="Periodo")
            fig_oni.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_oni, use_container_width=True, key=f"{key_prefix}_pc_1")
            st.caption("L'Oceanic Niño Index (ONI) misura le anomalie della temperatura superficiale del mare nel Pacifico centrale. Valori sopra +0.5°C indicano condizioni El Niño; sotto -0.5°C indicano La Niña.")

        with colB:
            st.markdown("#### Indice SOI (Atmosferico)")
            soi_recent = soi_series.tail(36)
            x_soi = [f"{idx[0]}-{str(idx[1]).zfill(2)}" for idx in soi_recent.index]
            bar_colors = ["blue" if val >= 0 else "red" for val in soi_recent.values]
            fig_soi = go.Figure(data=[go.Bar(x=x_soi, y=soi_recent.values,
                                             marker_color=bar_colors)])
            fig_soi.add_hline(y=7,  line_dash="dash", line_color="blue",
                              annotation_text="La Niña (+7)")
            fig_soi.add_hline(y=-7, line_dash="dash", line_color="red",
                              annotation_text="El Niño (-7)")
            fig_soi.update_yaxes(title_text="Indice SOI (adimensionale)")
            fig_soi.update_xaxes(title_text="Periodo")
            fig_soi.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_soi, use_container_width=True, key=f"{key_prefix}_pc_2")
            st.caption("Il Southern Oscillation Index (SOI) misura le differenze di pressione atmosferica nel Pacifico. Valori fortemente positivi confermano La Niña; valori fortemente negativi confermano El Niño.")

        st.markdown("#### Mappa Termica ONI Storica (10 Anni)")
        oni_10yr = oni_series.tail(120).reset_index()
        oni_10yr.columns = ["Year", "Month", "ONI"]
        oni_10yr["Year"] = oni_10yr["Year"].astype(int)
        oni_10yr["Month"] = oni_10yr["Month"].astype(int)
        pivot_oni = oni_10yr.pivot_table(index="Month", columns="Year", values="ONI", aggfunc="mean")
        pivot_oni = pivot_oni.sort_index(axis=1).reindex(range(1, 13))
        pivot_oni.index = [MONTH_NAMES[i - 1] for i in pivot_oni.index]
        fig_heat = px.imshow(pivot_oni, text_auto=".1f", aspect="auto",
                             color_continuous_scale="RdBu_r", color_continuous_midpoint=0)
        fig_heat.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0),
                               coloraxis_colorbar=dict(title="ONI (°C)"))
        st.plotly_chart(fig_heat, use_container_width=True, key=f"{key_prefix}_pc_3")
        st.caption("Valori ONI mensili su 10 anni. Celle rosse = mesi El Niño; celle blu = La Niña.")

    except Exception as e:
        st.warning(f"Errore visualizzazione ENSO: {e}")


def render_fires_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """
    Replica di render_tab_2.
    Il choropleth matplotlib/geopandas è sostituito con Plotly scatter_mapbox.
    """
    fires = _load("fires", country, use_api)
    states_prod = _states_prod_df()

    try:
        st.markdown("#### Rilevamenti Incendi NASA FIRMS — Ultimi 5 Giorni")
        if not fires.empty and "latitude" in fires.columns:
            fires_map = fires.copy()
            fires_map["frp"] = pd.to_numeric(fires_map.get("frp", 10), errors="coerce").fillna(10)
            fires_map["Intensità"] = fires_map["frp"].apply(
                lambda v: "Alta (>50 MW)" if v > 50 else "Media (10–50 MW)" if v >= 10 else "Bassa (<10 MW)"
            )
            color_map = {
                "Alta (>50 MW)":    "#B23A2E",
                "Media (10–50 MW)": "#C6842D",
                "Bassa (<10 MW)":   "#888888",
            }
            fig_map = px.scatter_mapbox(
                fires_map,
                lat="latitude", lon="longitude",
                color="Intensità",
                size="frp",
                size_max=18,
                opacity=0.80,
                color_discrete_map=color_map,
                mapbox_style="carto-positron",
                zoom=3,
                center={"lat": -15, "lon": -52},
                hover_data={"frp": True, "latitude": False, "longitude": False},
            )
            fig_map.update_layout(height=460, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_map, use_container_width=True, key=f"{key_prefix}_pc_4")
            st.caption(
                "Rilevamenti incendi satellite NASA VIIRS degli ultimi 5 giorni. "
                "Punti colorati per intensità FRP (Fire Radiative Power in MW). "
                "Ingrandisci per vedere le sovrapposizioni con le zone produttrici."
            )

            with st.expander("📖 Come leggere la mappa - Legenda FRP", expanded=False):
                col_l1, col_l2, col_l3 = st.columns(3)
                with col_l1:
                    st.markdown("**Punti Grigi (FRP < 10 MW)**")
                    st.caption("Focolai di bassa intensità: fuochi agricoli controllati. Impatto agronomico limitato.")
                with col_l2:
                    st.markdown("**Punti Arancio (FRP 10–50 MW)**")
                    st.caption("Incendi significativi. Rischio per le piantagioni nelle vicinanze.")
                with col_l3:
                    st.markdown("**Punti Rossi (FRP > 50 MW)**")
                    st.caption("Incendi di alta intensità. Impatto diretto certo sul raccolto in corso.")
        else:
            st.info("Nessun dato di incendio disponibile.")
    except Exception as e:
        st.warning(f"Errore mappa incendi: {e}")

    oni = _load("oni", country, use_api)
    dates = pd.date_range(end=pd.Timestamp.today() + pd.offsets.MonthEnd(0),
                          periods=24, freq="ME")
    climate = _make_climate(pd.Series(dates), oni)

    try:
        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Conteggio Mensile Incendi (Ultimi 24 Mesi)")
            fig_ts = px.line(
                climate, x="date", y="wildfire_count",
                markers=True,
                color_discrete_sequence=[COLORS["danger"]],
                labels={"wildfire_count": "Numero Incendi (focolai/mese)", "date": "Data"},
            )
            fig_ts.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_ts, use_container_width=True, key=f"{key_prefix}_pc_5")
            st.caption("Conteggio mensile stimato dei focolari. I picchi si verificano nella stagione secca (giugno–settembre).")

        with colB:
            st.markdown("#### Hotspot per Macro-Regione")
            if not fires.empty and "latitude" in fires.columns:
                fires_c = fires.copy()

                def _lat_region(row):
                    lat, lon = row["latitude"], row["longitude"]
                    if lat > -4:             return "Nord"
                    elif lat > -15 and lon > -44: return "Nord-Est"
                    elif lat > -20 and lon < -52: return "Centro-Ovest"
                    elif lat > -25:          return "Sud-Est"
                    else:                    return "Sud"

                fires_c["macro_region"] = fires_c.apply(_lat_region, axis=1)
                reg_counts = fires_c["macro_region"].value_counts().reset_index()
                reg_counts.columns = ["Regione", "Conteggio"]
                fig_bar = px.bar(reg_counts, x="Regione", y="Conteggio", color="Regione",
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_bar.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_bar, use_container_width=True, key=f"{key_prefix}_pc_6")
                st.caption("Rilevamenti incendi aggregati per macro-regione geografica del Brasile.")
            else:
                st.info("Nessun incendio disponibile per aggregazione regionale.")
    except Exception as e:
        st.warning(f"Errore grafico incendi: {e}")


def render_climate_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_6: deficit pluviometrico mensile + per stato."""
    import numpy as np

    states_mock = _load("conab", country, use_api)
    oni = _load("oni", country, use_api)
    dates = pd.date_range(end=pd.Timestamp.today() + pd.offsets.MonthEnd(0),
                          periods=24, freq="ME")
    climate = _make_climate(pd.Series(dates), oni)

    with st.expander("📖 Cos'è il Deficit Pluviometrico?", expanded=True):
        st.markdown("""
**Formula:**
> Deficit (%) = ((Pioggia_media_storica − Pioggia_osservata) / Pioggia_media_storica) × 100

| Deficit | Impatto |
|---------|---------|
| < 10%  | 🟢 Normale |
| 10–20% | 🟠 Stress moderato |
| > 20%  | 🔴 Stress severo — rischio calo resa |

**Periodi critici:** ottobre–novembre (fioritura) e dicembre–gennaio (sviluppo frutto).
        """)

    try:
        from ._config import _SEED
        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Deficit Pluviometrico Mensile (Ultimi 24 Mesi)")
            recent = climate.tail(24).copy()

            def _color(v):
                return COLORS["safe"] if v < 10 else COLORS["warning"] if v <= 20 else COLORS["danger"]

            bar_colors = recent["rainfall_deficit_pct"].apply(_color).tolist()
            recent["rolling_12"] = recent["rainfall_deficit_pct"].rolling(12, min_periods=1).mean()
            fig = go.Figure()
            fig.add_trace(go.Bar(x=recent["date"], y=recent["rainfall_deficit_pct"],
                                 marker_color=bar_colors, name="Deficit %"))
            fig.add_trace(go.Scatter(x=recent["date"], y=recent["rolling_12"],
                                     mode="lines", line=dict(color="black", width=3),
                                     name="Media Mobile 12 Mesi"))
            fig.add_hline(y=10, line_dash="dot", line_color=COLORS["warning"],
                          annotation_text="Soglia stress moderato (10%)",
                          annotation_position="top left")
            fig.add_hline(y=20, line_dash="dot", line_color=COLORS["danger"],
                          annotation_text="Soglia stress severo (20%)",
                          annotation_position="top left")
            fig.update_layout(
                height=420, margin=dict(l=0, r=0, t=30, b=0),
                yaxis=dict(title="Deficit Pluviometrico (%)", ticksuffix="%",
                           range=[0, max(recent["rainfall_deficit_pct"].max() * 1.15, 25)]),
                xaxis=dict(title="Mese"),
                legend=dict(orientation="h", y=1.05, x=0),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_pc_16")
            st.caption("Verde < 10% = normale; arancio 10–20% = stress moderato; rosso > 20% = stress severo. Valori derivati dal modello ENSO-ONI.")

        with colB:
            st.markdown("#### Deficit Pluviometrico Medio per Stato")
            if states_mock is not None and not states_mock.empty:
                rng = np.random.default_rng(_SEED + 10)
                sp = states_mock.copy()
                sp["avg_deficit"] = rng.uniform(4.0, 25.0, len(sp))
                sp = sp.sort_values("avg_deficit", ascending=True)
                figH = px.bar(sp, x="avg_deficit", y="state", orientation="h",
                              color="avg_deficit", color_continuous_scale="RdYlGn_r",
                              hover_data={"avg_deficit": ":.1f"},
                              labels={"avg_deficit": "Deficit (%)", "state": "Stato"})
                figH.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0),
                                   xaxis=dict(title="Deficit Annuo Medio (%)", ticksuffix="%"),
                                   coloraxis_colorbar=dict(title="Deficit (%)"))
                st.plotly_chart(figH, use_container_width=True, key=f"{key_prefix}_pc_17")
                st.caption("Deficit pluviometrico annuo medio (%) per stato produttore. Rosso = più critico.")
    except Exception as e:
        st.warning(f"Errore grafico precipitazioni: {e}")

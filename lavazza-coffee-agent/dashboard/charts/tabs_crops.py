"""tabs_crops.py — Render tab Produttività Raccolti e IBGE+Comex Export."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ._config import COLORS
from ._loader import _load


def render_yields_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_5: USDA stacked bars, esportazioni/scorte, bubble chart, FAOSTAT, pie."""
    usda = _load("usda", country, use_api)
    faostat_df = _load("faostat", country, use_api)
    states_mock = _load("conab", country, use_api)

    if states_mock is not None:
        st.caption("📋 Dati CONAB: tabella stati da ultimo report CONAB (MongoDB). "
                   "Per dati aggiornati ri-eseguire il workflow n8n CONAB.")

    with st.expander("📊 FAOSTAT Dati Storici a Lungo Termine (1990–presente)"):
        if faostat_df is not None and not faostat_df.empty and "Year" in faostat_df.columns:
            try:
                fao_plot = faostat_df.copy()
                area_col = (next((c for c in fao_plot.columns
                                  if "area" in c.lower() and "harvest" in c.lower()), None)
                            or next((c for c in fao_plot.columns if "area" in c.lower()), None))
                prod_col = next((c for c in fao_plot.columns if "production" in c.lower()), None)
                year_col = "Year" if "Year" in fao_plot.columns else fao_plot.columns[0]
                if prod_col:
                    fig_fao = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_fao.add_trace(go.Bar(x=fao_plot[year_col], y=fao_plot[prod_col],
                                             name="Produzione (t)",
                                             marker_color="#4A2F1D", opacity=0.75),
                                      secondary_y=False)
                    if area_col:
                        fig_fao.add_trace(go.Scatter(x=fao_plot[year_col], y=fao_plot[area_col],
                                                     name="Superficie Raccolta (ha)",
                                                     line=dict(color="#3E7B58", width=2.5)),
                                          secondary_y=True)
                    fig_fao.update_yaxes(title_text="Produzione (t)", secondary_y=False)
                    fig_fao.update_yaxes(title_text="Superficie Raccolta (ha)", secondary_y=True)
                    fig_fao.update_xaxes(title_text="Anno")
                    fig_fao.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0),
                                          plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_fao, use_container_width=True, key=f"{key_prefix}_pc_11")
                    st.caption("Fonte: FAOSTAT QCL, Brasile (area=21), Caffè verde (item=656). "
                               "I cicli lunghi riflettono il pattern biennale anni-on/off.")
            except Exception as e:
                st.warning(f"Errore grafico FAOSTAT: {e}")
        else:
            st.info("Dati FAOSTAT non disponibili.")

    try:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Produzione Totale Brasiliana di Caffè per Anno")
            figP = go.Figure()
            figP.add_trace(go.Bar(x=usda["year"], y=usda["arabica_bags"],
                                  name="Arabica", marker_color=COLORS["arabica"]))
            figP.add_trace(go.Bar(x=usda["year"], y=usda["robusta_bags"],
                                  name="Robusta", marker_color=COLORS["robusta"]))
            figP.update_layout(barmode="stack", height=380,
                               margin=dict(l=0, r=0, t=10, b=0),
                               yaxis=dict(title="Sacchi da 60 kg", tickformat=".2s"))
            st.plotly_chart(figP, use_container_width=True, key=f"{key_prefix}_pc_12")
            st.caption("Produzione totale in sacchi da 60 kg, suddivisa Arabica/Robusta. Il Brasile alterna anni di alta e bassa produzione in un ciclo biennale. Fonte: USDA PSD.")

        with c2:
            st.markdown("#### Volumi Annui Esportazioni vs Scorte Finali")
            figE = make_subplots(specs=[[{"secondary_y": True}]])
            total_exp = usda["export_ara"].fillna(0) + usda["export_rob"].fillna(0)
            total_inv = usda["inventory_ara"].fillna(0) + usda["inventory_rob"].fillna(0)
            figE.add_trace(go.Scatter(x=usda["year"], y=total_exp, name="Esportazioni Totali",
                                      mode="lines+markers",
                                      line=dict(color="#2ca02c")), secondary_y=False)
            figE.add_trace(go.Scatter(x=usda["year"], y=total_inv, name="Scorte",
                                      mode="lines",
                                      line=dict(color="#1f77b4", dash="dash")), secondary_y=True)
            figE.update_yaxes(title_text="Esportazioni (sacchi 60 kg)", secondary_y=False,
                              tickformat=".2s")
            figE.update_yaxes(title_text="Scorte Finali (sacchi 60 kg)", secondary_y=True,
                              tickformat=".2s")
            figE.update_xaxes(title_text="Anno")
            figE.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figE, use_container_width=True, key=f"{key_prefix}_pc_13")
            st.caption("Quando le esportazioni aumentano mentre le scorte scendono, la filiera logistica si assottiglia — indicatore anticipatore della pressione sui prezzi.")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### Efficienza Resa vs Volume Produzione — Top 10 Regioni")
            if states_mock is not None and not states_mock.empty:
                top10 = states_mock.nlargest(10, "production_bags").copy()
                figS = px.scatter(
                    top10, x="yield", y="production_bags",
                    color="state", size="production_bags", size_max=55,
                    text="state",
                    labels={"yield": "Resa (sacchi/ettaro)",
                            "production_bags": "Produzione Totale (sacchi da 60 kg)",
                            "state": "Stato"},
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                figS.update_traces(textposition="top center", textfont=dict(size=10),
                                   marker=dict(opacity=0.85, line=dict(width=1, color="white")))
                figS.update_layout(height=480, margin=dict(l=0, r=0, t=20, b=0),
                                   plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
                                   yaxis=dict(tickformat=".2s",
                                              title="Produzione Totale (sacchi da 60 kg)"),
                                   xaxis=dict(title="Resa (sacchi/ettaro)"))
                st.plotly_chart(figS, use_container_width=True, key=f"{key_prefix}_pc_14")
                st.caption("Le 10 principali regioni produttrici brasiliane. Ogni bolla = uno stato; dimensione = volume; asse X = resa per ettaro.")

        with c4:
            st.markdown("#### Quota di Mercato Arabica / Robusta (Ultimo Anno)")
            latest = usda.iloc[-1]
            figD = px.pie(
                values=[latest["arabica_bags"], latest["robusta_bags"]],
                names=["Arabica", "Robusta"], hole=0.5,
                color_discrete_sequence=[COLORS["arabica"], COLORS["robusta"]],
            )
            figD.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figD, use_container_width=True, key=f"{key_prefix}_pc_15")
            st.caption("Quota Arabica vs Robusta nell'ultimo anno. Il Brasile è storicamente ~70-75% Arabica, ma la quota Robusta cresce per la sua resistenza alla siccità.")

    except Exception as e:
        st.warning(f"Errore grafici produttività: {e}")


def render_ibge_comex_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Produzione per stato (IBGE) + export Brasile (Comex Stat)."""
    ibge = _load("ibge", country, use_api)
    comex = _load("comex", country, use_api)

    st.markdown("### IBGE SIDRA — Produzione per Stato")
    if ibge is not None and not ibge.empty:
        period = ibge["period_label"].iloc[0] if "period_label" in ibge.columns else ""
        if period:
            st.caption(f"Periodo di riferimento: **{period}**")

        try:
            states_only = ibge[ibge["code"] != "BR"].copy()
            brasil_row = ibge[ibge["code"] == "BR"]

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Produzione per Stato — Arabica vs Robusta (Canephora)")
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["arabica_t"],
                    name="Arabica", marker_color=COLORS["arabica"],
                ))
                fig_bar.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["canephora_t"],
                    name="Canephora (Robusta)", marker_color=COLORS["robusta"],
                ))
                fig_bar.update_layout(
                    barmode="group", height=360,
                    margin=dict(l=0, r=0, t=20, b=0),
                    yaxis=dict(title="Produzione (tonnellate)", tickformat=".2s"),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig_bar, use_container_width=True, key=f"{key_prefix}_pc_18")
                st.caption("Fonte IBGE SIDRA LSPA, tavola 6588. MG domina arabica; ES è il principale produttore di canephora.")

            with col2:
                st.markdown("#### Resa Media per Stato (kg/ha)")
                fig_yield = go.Figure()
                fig_yield.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["arabica_yield"],
                    name="Arabica kg/ha", marker_color=COLORS["arabica"], opacity=0.85,
                ))
                fig_yield.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["canephora_yield"],
                    name="Canephora kg/ha", marker_color=COLORS["robusta"], opacity=0.85,
                ))
                fig_yield.update_layout(
                    barmode="group", height=360,
                    margin=dict(l=0, r=0, t=20, b=0),
                    yaxis=dict(title="Resa (kg/ha)"),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig_yield, use_container_width=True, key=f"{key_prefix}_pc_19")
                st.caption("Resa media in kg per ettaro. ES ha la resa canephora più alta; RO ha bassa resa arabica ma volumi canephora in crescita.")

            if not brasil_row.empty:
                ara_tot = float(brasil_row["arabica_t"].iloc[0])
                can_tot = float(brasil_row["canephora_t"].iloc[0])
                total_tot = ara_tot + can_tot
                col3, col4 = st.columns(2)
                with col3:
                    st.markdown("#### Mix Arabica / Canephora — Brasile")
                    fig_pie = px.pie(
                        values=[ara_tot, can_tot],
                        names=["Arabica", "Canephora"],
                        hole=0.5,
                        color_discrete_sequence=[COLORS["arabica"], COLORS["robusta"]],
                    )
                    fig_pie.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0))
                    st.plotly_chart(fig_pie, use_container_width=True, key=f"{key_prefix}_pc_20")
                    st.caption(f"Totale Brasile: {total_tot:,.0f} t  "
                               f"({ara_tot/total_tot*100:.0f}% Arabica, "
                               f"{can_tot/total_tot*100:.0f}% Canephora)")
        except Exception as e:
            st.warning(f"Errore grafici IBGE: {e}")
    else:
        st.info("Dati IBGE non disponibili in MongoDB. Avviare il workflow n8n IBGE SIDRA.")

    st.divider()

    st.markdown("### Comex Stat — Export Caffè Brasile")
    if comex:
        try:
            recent_df = comex.get("recent_series")
            dest_list = comex.get("destinations", [])
            pm = comex.get("product_mix", {})
            dm = comex.get("derived_metrics", {})

            if dm:
                m1, m2, m3 = st.columns(3)
                mom_kg = dm.get("mom_exports_kg_pct", 0)
                yoy_kg = dm.get("yoy_exports_kg_pct", 0)
                price_yoy = dm.get("avg_price_yoy_pct", 0) or dm.get("avg_price_mom_pct", 0)
                m1.metric("Export kg MoM", f"{mom_kg:+.1f}%",
                          delta_color="normal" if mom_kg >= 0 else "inverse")
                m2.metric("Export kg YoY", f"{yoy_kg:+.1f}%",
                          delta_color="normal" if yoy_kg >= 0 else "inverse")
                m3.metric("Prezzo medio YoY", f"{price_yoy:+.1f}%",
                          delta_color="normal" if price_yoy >= 0 else "inverse")

            col1, col2 = st.columns(2)
            with col1:
                if recent_df is not None and not recent_df.empty and "total_exports_fob_usd" in recent_df.columns:
                    st.markdown("#### Valore Export Mensile (USD FOB)")
                    fig_exp = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_exp.add_trace(
                        go.Bar(x=recent_df["period"], y=recent_df["total_exports_fob_usd"],
                               name="FOB USD", marker_color=COLORS["highlight"], opacity=0.8),
                        secondary_y=False,
                    )
                    if "total_exports_kg" in recent_df.columns:
                        fig_exp.add_trace(
                            go.Scatter(x=recent_df["period"], y=recent_df["total_exports_kg"],
                                       name="Kg", mode="lines+markers",
                                       line=dict(color=COLORS["arabica"], width=2)),
                            secondary_y=True,
                        )
                    fig_exp.update_yaxes(title_text="USD FOB", secondary_y=False, tickformat=".2s")
                    fig_exp.update_yaxes(title_text="Kg esportati", secondary_y=True, tickformat=".2s")
                    fig_exp.update_xaxes(tickangle=-45)
                    fig_exp.update_layout(height=380, margin=dict(l=0, r=0, t=20, b=40),
                                          legend=dict(orientation="h", y=1.05))
                    st.plotly_chart(fig_exp, use_container_width=True, key=f"{key_prefix}_pc_21")
                    st.caption("Export mensile caffè brasiliano in valore (barre, USD FOB) e volume (linea, kg). Fonte: Comex Stat.")

            with col2:
                if dest_list:
                    st.markdown("#### Top Destinazioni Export (Ultimo Mese)")
                    dest_df = pd.DataFrame(dest_list[:8])
                    val_col = next((c for c in dest_df.columns if "fob" in c.lower() or "value" in c.lower()), None)
                    name_col = next((c for c in dest_df.columns if "country" in c.lower() or "destination" in c.lower() or "dest" in c.lower()), None)
                    if val_col and name_col:
                        dest_df = dest_df.sort_values(val_col, ascending=True)
                        fig_dest = px.bar(dest_df, x=val_col, y=name_col, orientation="h",
                                          color_discrete_sequence=[COLORS["arabica"]],
                                          labels={val_col: "USD FOB", name_col: "Paese"})
                        fig_dest.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
                        st.plotly_chart(fig_dest, use_container_width=True, key=f"{key_prefix}_pc_22")
                        st.caption("Principali mercati di destinazione del caffè brasiliano. USA e Germania guidano storicamente le importazioni.")

            if pm:
                def _extract_mix_share(val) -> float:
                    if isinstance(val, dict):
                        return float(val.get("share_kg_pct") or val.get("kg") or 0)
                    try:
                        return float(val or 0)
                    except (TypeError, ValueError):
                        return 0.0

                green_v   = _extract_mix_share(pm.get("green",   0))
                roasted_v = _extract_mix_share(pm.get("roasted", 0))
                soluble_v = _extract_mix_share(pm.get("soluble", 0))

                if green_v + roasted_v + soluble_v > 0:
                    st.markdown("#### Mix Prodotto Esportato")
                    labels = ["Caffè Verde", "Tostato", "Solubile"]
                    values = [green_v, roasted_v, soluble_v]
                    fig_pm = px.pie(values=values, names=labels, hole=0.4,
                                    color_discrete_sequence=["#4A2F1D", "#C6842D", "#3E7B58"])
                    fig_pm.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
                    st.plotly_chart(fig_pm, use_container_width=True, key=f"{key_prefix}_pc_23")
                    st.caption("Il caffè verde (non tostato) domina le esportazioni brasiliane — ~78%. La quota solubile è in lenta crescita.")

        except Exception as e:
            st.warning(f"Errore grafici Comex: {e}")
    else:
        st.info("Dati Comex non disponibili in MongoDB. Avviare il workflow n8n Comex Stat.")

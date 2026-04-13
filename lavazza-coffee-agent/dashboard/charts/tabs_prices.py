"""tabs_prices.py — Render tab Prezzi di Mercato e Fertilizzanti."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.db import get_latest_doc  # noqa: E402

from ._config import COLORS
from ._data_mongo import _mongo_fertilizers
from ._loader import _load


def render_prices_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_4: arabica/robusta, spread, base-100+FX z-score, annuale."""
    prices = _load("prices", country, use_api)
    if prices.empty:
        st.warning("Dati prezzi non disponibili.")
        return

    try:
        fx_now = float(prices["fx_brl_per_eur"].iloc[-1]) if not prices.empty else 0.0
        st.metric("Tasso di Cambio Attuale BRL/EUR", f"R$ {fx_now:.2f}",
                  help="BRL per 1 EUR (da BCB PTAX / yfinance).")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Prezzi Arabica & Robusta (EUR/kg)")
            figA = make_subplots(specs=[[{"secondary_y": True}]])
            figA.add_trace(go.Scatter(x=prices["date"], y=prices["arabica_eur_kg"],
                                      name="Arabica (€)", line=dict(color=COLORS["arabica"])),
                           secondary_y=False)
            figA.add_trace(go.Scatter(x=prices["date"], y=prices["robusta_eur_kg"],
                                      name="Robusta (€)", line=dict(color=COLORS["robusta"])),
                           secondary_y=True)
            figA.update_yaxes(title_text="Arabica (EUR/kg)", secondary_y=False)
            figA.update_yaxes(title_text="Robusta (EUR/kg)", secondary_y=True)
            figA.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figA, use_container_width=True, key=f"{key_prefix}_pc_7")
            st.caption("Prezzi storici Arabica e Robusta in EUR/kg. Fonte: World Bank Pink Sheet / simulato.")

        with c2:
            st.markdown("#### Spread Arabica vs Robusta con Media Mobile a 3 Mesi")
            pc = prices.copy()
            pc["spread"] = pc["arabica_eur_kg"] - pc["robusta_eur_kg"]
            pc["ma_3"] = pc["spread"].rolling(window=3).mean()
            figS = go.Figure()
            figS.add_trace(go.Bar(x=pc["date"], y=pc["spread"],
                                  name="Differenziale Prezzi",
                                  marker_color="#8c564b", opacity=0.6))
            figS.add_trace(go.Scatter(x=pc["date"], y=pc["ma_3"],
                                      mode="lines", name="Media Mobile 3 Mesi",
                                      line=dict(color="red", width=2)))
            figS.update_yaxes(title_text="Differenziale (EUR/kg)")
            figS.update_xaxes(title_text="Data")
            figS.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figS, use_container_width=True, key=f"{key_prefix}_pc_8")
            st.caption("Premio di prezzo dell'Arabica sull'Robusta in EUR/kg. Barre = differenziale mensile; linea rossa = media mobile 3 mesi.")

        st.markdown("#### Prezzo Arabica: BRL/kg vs EUR/kg a Confronto")
        px_c = prices[["date", "arabica_brl_kg", "arabica_eur_kg", "fx_brl_per_eur"]].copy().reset_index(drop=True)
        px_c["brl_idx"] = (px_c["arabica_brl_kg"] / px_c["arabica_brl_kg"].iloc[0]) * 100
        px_c["eur_idx"] = (px_c["arabica_eur_kg"] / px_c["arabica_eur_kg"].iloc[0]) * 100
        px_c["fx_roll_mean"] = px_c["fx_brl_per_eur"].rolling(12, min_periods=3).mean()
        px_c["fx_roll_std"]  = px_c["fx_brl_per_eur"].rolling(12, min_periods=3).std()
        px_c["fx_zscore"] = (px_c["fx_brl_per_eur"] - px_c["fx_roll_mean"]) \
                            / px_c["fx_roll_std"].replace(0, np.nan)
        bar_colors_fx = ["#3E7B58" if (z == z and z > 1) else "#BDBDBD"
                         for z in px_c["fx_zscore"].fillna(0)]

        figFX = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.65, 0.35], vertical_spacing=0.08,
            subplot_titles=("Andamento Prezzi Normalizzati (Base 100)",
                            "Z-Score FX BRL/EUR - Rolling 12 Mesi"),
        )
        dates_list = px_c["date"].tolist()
        brl_vals   = px_c["brl_idx"].tolist()
        eur_vals   = px_c["eur_idx"].tolist()

        for i in range(len(dates_list) - 1):
            eur_adv = eur_vals[i] < brl_vals[i]
            fill_col = "rgba(62,123,88,0.18)" if eur_adv else "rgba(178,58,46,0.12)"
            figFX.add_trace(go.Scatter(
                x=[dates_list[i], dates_list[i + 1], dates_list[i + 1], dates_list[i]],
                y=[brl_vals[i],   brl_vals[i + 1],   eur_vals[i + 1],   eur_vals[i]],
                fill="toself", fillcolor=fill_col,
                mode="lines", line=dict(width=0, color=fill_col),
                hoverinfo="skip", showlegend=False,
            ), row=1, col=1)

        figFX.add_trace(go.Scatter(
            x=px_c["date"], y=px_c["brl_idx"],
            name="Arabica BRL/kg (Base 100)",
            line=dict(color="#1A5EA8", width=2),
        ), row=1, col=1)
        figFX.add_trace(go.Scatter(
            x=px_c["date"], y=px_c["eur_idx"],
            name="Arabica EUR/kg (Base 100)",
            line=dict(color="#4A2F1D", width=2, dash="dot"),
        ), row=1, col=1)
        figFX.add_trace(go.Bar(
            x=px_c["date"], y=px_c["fx_zscore"],
            marker_color=bar_colors_fx, name="Z-Score FX BRL/EUR",
        ), row=2, col=1)
        figFX.add_hline(y=1,  line_dash="dash", line_color="#3E7B58",
                        annotation_text="+1σ EUR forte", row=2, col=1)
        figFX.add_hline(y=0,  line_dash="dot",  line_color="#AAAAAA", row=2, col=1)
        figFX.add_hline(y=-1, line_dash="dash", line_color="#B23A2E",
                        annotation_text="−1σ", row=2, col=1)
        figFX.update_yaxes(title_text="Indice (Base 100)", row=1, col=1)
        figFX.update_yaxes(title_text="Z-Score",           row=2, col=1)
        figFX.update_xaxes(title_text="Data",              row=2, col=1)
        figFX.update_layout(height=560, margin=dict(l=0, r=0, t=50, b=0),
                            plot_bgcolor="rgba(0,0,0,0)",
                            legend=dict(orientation="h", y=1.06, x=0),
                            hovermode="x unified")
        st.plotly_chart(figFX, use_container_width=True, key=f"{key_prefix}_pc_9")
        st.caption(
            "📊 Pannello superiore: andamento normalizzato (Base 100) del prezzo Arabica in BRL/kg (blu) "
            "e EUR/kg (marrone tratteggiato). 🟢 Zone verdi = EUR forte sul BRL (favorevole all'acquisto europeo). "
            "Pannello inferiore: Z-score rolling 12 mesi del cambio BRL/EUR. Barre verdi (Z > +1σ) = finestre storicamente favorevoli."
        )

        st.markdown("#### Prezzo Medio Annuo Arabica vs Media Decennale")
        pr_annual = prices.copy()
        pr_annual["year"] = pd.to_datetime(pr_annual["date"]).dt.year
        annual_avg = pr_annual.groupby("year")["arabica_eur_kg"].mean().reset_index()
        annual_avg.columns = ["year", "avg_price"]
        overall_mean = annual_avg["avg_price"].mean()
        fig_ann = go.Figure()
        fig_ann.add_trace(go.Bar(x=annual_avg["year"], y=annual_avg["avg_price"],
                                 name="Prezzo Medio Annuo", marker_color=COLORS["arabica"]))
        fig_ann.add_hline(y=overall_mean, line_dash="dash", line_color="grey",
                          annotation_text=f"Media 10 anni: {overall_mean:.2f} €/kg")
        fig_ann.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0),
                               yaxis_title="EUR/kg", xaxis_title="Anno")
        st.plotly_chart(fig_ann, use_container_width=True, key=f"{key_prefix}_pc_10")
        st.caption("Prezzo medio annuo Arabica per anno vs. media del periodo. Gli anni sopra la media seguono spesso shock di offerta (siccità, gelate).")

    except Exception as e:
        st.warning(f"Errore grafici prezzi: {e}")


def render_fertilizers_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """
    Prezzi fertilizzanti (DAP, Urea, Potash/MOP).
    MongoDB mode: legge fertilizer_series dal documento WB_PINK_SHEET.
    API mode: scarica direttamente l'Excel WB Pink Sheet.
    """
    fert_df = _load("fertilizers", country, use_api)
    if fert_df is not None and "potash_usd_t" in fert_df.columns and "mop_usd_t" not in fert_df.columns:
        fert_df = fert_df.rename(columns={"potash_usd_t": "mop_usd_t"})

    if not use_api:
        wb_doc = get_latest_doc("raw_prices", "WB_PINK_SHEET", country)
        if wb_doc and wb_doc.get("fertilizer_available"):
            st.success("✅ Dati fertilizzanti caricati da MongoDB (WB Pink Sheet — workflow n8n).")
        else:
            st.info("ℹ️ Fertilizzanti non ancora in MongoDB — il workflow n8n WB Pink Sheet deve girare "
                    "almeno una volta con la nuova versione per popolare `fertilizer_series`. "
                    "Attualmente visualizzazione simulata.")
    else:
        st.success("✅ Dati fertilizzanti caricati dall'API World Bank Pink Sheet (Excel live).")

    if fert_df is not None and not fert_df.empty:
        latest = fert_df.iloc[-1]
        prev = fert_df.iloc[-2] if len(fert_df) >= 2 else latest
        cols = [c for c in ["dap_usd_t", "urea_usd_t", "mop_usd_t"] if c in fert_df.columns]
        labels = {"dap_usd_t": "DAP (USD/t)", "urea_usd_t": "Urea (USD/t)", "mop_usd_t": "MOP/Potassio (USD/t)"}
        metric_cols = st.columns(len(cols))
        for mc, col in zip(metric_cols, cols):
            val = float(latest.get(col, 0) or 0)
            delta = float((latest.get(col, 0) or 0) - (prev.get(col, 0) or 0))
            mc.metric(labels.get(col, col), f"${val:,.0f}", f"{delta:+.0f} $/t MoM")

    if fert_df is None:
        st.warning("Dati fertilizzanti non disponibili.")
        return

    try:
        avail_cols = [c for c in ["dap_usd_t", "urea_usd_t", "mop_usd_t"] if c in fert_df.columns]
        col_labels = {"dap_usd_t": "DAP", "urea_usd_t": "Urea", "mop_usd_t": "MOP/Potassio"}
        colors_fert = {"dap_usd_t": "#4A2F1D", "urea_usd_t": "#1A5EA8", "mop_usd_t": "#3E7B58"}

        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Prezzi Fertilizzanti (USD/t) — Ultimi 10 Anni")
            fig_fert = go.Figure()
            for col in avail_cols:
                fig_fert.add_trace(go.Scatter(
                    x=fert_df["date"], y=fert_df[col],
                    name=col_labels.get(col, col),
                    line=dict(color=colors_fert.get(col, "#999"), width=2),
                    mode="lines",
                ))
            fig_fert.update_layout(
                height=400, margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(title="USD / tonnellata metrica"),
                legend=dict(orientation="h", y=1.05),
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_fert, use_container_width=True, key=f"{key_prefix}_pc_27")
            st.caption(
                "**DAP** (fosfato diammonico) è il fertilizzante principale per la fioritura del caffè. "
                "**Urea** è la fonte di azoto più economica. "
                "**MOP** (cloreto de potássio) supporta la qualità del chicco."
            )

        with colB:
            if len(avail_cols) >= 2:
                st.markdown("#### Variazione YoY Prezzi Fertilizzanti (%)")
                fert_yoy = fert_df.copy()
                for col in avail_cols:
                    fert_yoy[f"{col}_yoy"] = fert_yoy[col].pct_change(12) * 100
                fig_yoy = go.Figure()
                for col in avail_cols:
                    yoy_col = f"{col}_yoy"
                    if yoy_col in fert_yoy.columns:
                        fig_yoy.add_trace(go.Bar(
                            x=fert_yoy["date"], y=fert_yoy[yoy_col],
                            name=col_labels.get(col, col),
                            opacity=0.75,
                        ))
                fig_yoy.add_hline(y=0, line_dash="dot", line_color="#999")
                fig_yoy.update_layout(
                    barmode="group", height=400,
                    margin=dict(l=0, r=0, t=10, b=0),
                    yaxis=dict(title="Variazione YoY (%)", ticksuffix="%"),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig_yoy, use_container_width=True, key=f"{key_prefix}_pc_28")
                st.caption("Variazione annuale (YoY) dei prezzi fertilizzanti. "
                           "Aumenti sostenuti (>20% YoY) impattano i margini dei produttori brasiliani.")

        prices_df = _load("prices", country, use_api)
        if prices_df is not None and not prices_df.empty and avail_cols:
            st.markdown("#### Costo Fertilizzanti vs Prezzo Arabica — Pressione sui Margini")
            try:
                fert_idx = fert_df.copy()
                for col in avail_cols:
                    fert_idx[col] = pd.to_numeric(fert_idx[col], errors="coerce")
                fert_idx["fert_composite"] = fert_idx[avail_cols].mean(axis=1)
                fert_idx["date"] = pd.to_datetime(fert_idx["date"])
                prices_m = prices_df.copy()
                prices_m["date"] = pd.to_datetime(prices_m["date"])
                merged = pd.merge_asof(
                    prices_m.sort_values("date"),
                    fert_idx[["date", "fert_composite"]].sort_values("date"),
                    on="date", direction="nearest", tolerance=pd.Timedelta(days=45)
                ).dropna(subset=["fert_composite"])
                if not merged.empty:
                    merged["ara_idx"] = (merged["arabica_eur_kg"] / merged["arabica_eur_kg"].iloc[0]) * 100
                    # USD/t → EUR/kg: dividi per usd_per_eur (reale da ECB/yfinance) e per 1000
                    has_rate = "usd_per_eur" in merged.columns and merged["usd_per_eur"].notna().any()
                    if not has_rate:
                        st.info("ℹ️ Grafico pressione margini non disponibile: tasso USD/EUR mancante.")
                    else:
                        fert_eur_kg = merged["fert_composite"] / (merged["usd_per_eur"] * 1000)
                        merged["fert_idx"] = (fert_eur_kg / fert_eur_kg.iloc[0]) * 100
                        fig_margin = make_subplots(specs=[[{"secondary_y": True}]])
                        fig_margin.add_trace(go.Scatter(
                            x=merged["date"], y=merged["ara_idx"],
                            name="Arabica (Base 100)", line=dict(color=COLORS["arabica"], width=2),
                        ), secondary_y=False)
                        fig_margin.add_trace(go.Scatter(
                            x=merged["date"], y=merged["fert_idx"],
                            name="Fertilizzanti Composito (Base 100)",
                            line=dict(color=COLORS["danger"], width=2, dash="dot"),
                        ), secondary_y=True)
                        fig_margin.update_yaxes(title_text="Arabica (Base 100)", secondary_y=False)
                        fig_margin.update_yaxes(title_text="Fertilizzanti (Base 100)", secondary_y=True)
                        fig_margin.update_layout(
                            height=400, margin=dict(l=0, r=0, t=10, b=0),
                            legend=dict(orientation="h", y=1.05),
                            plot_bgcolor="rgba(0,0,0,0)",
                        )
                        st.plotly_chart(fig_margin, use_container_width=True, key=f"{key_prefix}_pc_29")
                        st.caption(
                            "Confronto normalizzato (Base 100) tra prezzo arabica e costo composito fertilizzanti. "
                            "Quando i fertilizzanti crescono più velocemente dell'arabica, i margini dei produttori si comprimono."
                        )
            except Exception:
                pass
    except Exception as e:
        st.warning(f"Errore grafici fertilizzanti: {e}")

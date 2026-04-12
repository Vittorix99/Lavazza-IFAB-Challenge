import streamlit as st
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import requests
import io
import asyncio
import websockets
import json
import time
import nest_asyncio

# Permette l'esecuzione di loop asincroni in ambienti che ne hanno già uno (come le dashboard o Jupyter)
nest_asyncio.apply()

# ==========================================
# CONFIGURAZIONE PAGINA
# ==========================================
st.set_page_config(page_title="Dashboard Dati Brasile", layout="wide")
st.title("Dashboard Brasile — Incendi, Clima e Porti")

tab1, tab2, tab3 = st.tabs(["Incendi & Caffè", "ENSO / El Niño", "Traffico Porti (Live)"])

# ==========================================
# TAB 1: INCENDI E CAFFÈ
# ==========================================
with tab1:
    st.header("Incendi attivi e produzione di caffè in Brasile")

    st.markdown("""
**Come leggere la mappa:**
- **Gradiente (Verde/Viola):** volume di produzione caffè per Stato (milioni di sacchi). Gli Stati grigi non producono caffè.
- **Punti caldi:** incendi ad alto FRP (Fire Radiative Power > 50 MW), colorati per intensità. Fuochi minori in grigio semitrasparente.
- Se i focolai caldi si sovrappongono alle zone produttive (es. Minas Gerais, Espírito Santo), il rischio coltura è elevato.

**Nota — Coffee Regions (analisi agente):** la visualizzazione usa dati di produzione aggregati per Stato.
L'agente ambiente (environment_agent) arricchisce ogni rilevamento NASA FIRMS con i confini GeoJSON
dei **comuni produttori di caffè** (MongoDB `coffee_regions`, livello L2) tramite query `$geoIntersects`.
I campi `coffee_zone_detections` e `coffee_zone_ratio` indicano quanti fuochi cadono in comuni
produttori — questa informazione è disponibile nel report giornaliero e nel chatbot.
    """)

    @st.cache_data(ttl=3600)
    def fetch_fire_and_coffee_data():
        MAP_KEY = '63fb02bde23144ea120a3123f959bf4c'
        SOURCE = 'VIIRS_SNPP_NRT'
        DAYS = '5'
        BBOX = '-75,-35,-33,6'
        
        # Dati NASA FIRMS
        url = f'https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{BBOX}/{DAYS}'
        response = requests.get(url)
        fires_df = pd.read_csv(io.StringIO(response.text))
        fires_gdf = gpd.GeoDataFrame(fires_df, geometry=gpd.points_from_xy(fires_df.longitude, fires_df.latitude), crs="EPSG:4326")
        
        # Confini mappa Brasile
        geojson_url = 'https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson'
        brazil_states = gpd.read_file(geojson_url)
        
        # Dati Produzione Caffè
        coffee_data = {
            'sigla': ['MG', 'ES', 'SP', 'BA', 'RO', 'PR', 'RJ', 'GO', 'MT'],
            'Arabica': [28.0, 3.0, 5.4, 1.2, 0.0, 0.5, 0.3, 0.2, 0.0],
            'Robusta': [0.3, 10.5, 0.0, 2.2, 2.8, 0.0, 0.0, 0.0, 0.2]
        }
        coffee_df = pd.DataFrame(coffee_data)
        brazil_map = brazil_states.merge(coffee_df, on='sigla', how='left')
        brazil_map['Arabica'] = brazil_map['Arabica'].replace(0, np.nan)
        brazil_map['Robusta'] = brazil_map['Robusta'].replace(0, np.nan)
        
        fires_in_brazil = gpd.sjoin(fires_gdf, brazil_states, how="inner", predicate="intersects")
        return brazil_map, fires_in_brazil, DAYS

    with st.spinner("Scaricamento dei dati satellitari NASA in corso..."):
        try:
            brazil_map, fires_in_brazil, DAYS = fetch_fire_and_coffee_data()
            
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
            fig.patch.set_facecolor('none') # Rende lo sfondo trasparente
            
            # Filtro incendi per gradiente: evidenzia solo quelli ad alto FRP (FRP > 50)
            threshold = 50
            large_fires = fires_in_brazil[fires_in_brazil['frp'] > threshold]
            small_fires = fires_in_brazil[fires_in_brazil['frp'] <= threshold]

            # Mappa 1: ARABICA
            ax1.set_title('Produzione Arabica & Incendi Maggiori', fontsize=15, color='white' if st.get_option("theme.base") == "dark" else 'black')
            brazil_map.plot(column='Arabica', ax=ax1, cmap='Greens', edgecolor='white', linewidth=0.5, legend=True, missing_kwds={'color': '#e0e0e0'})
            # Traccia incendi piccoli in grigio (basso impatto)
            ax1.scatter(small_fires.geometry.x, small_fires.geometry.y, color='grey', s=3, alpha=0.2, edgecolors='none')
            # Traccia grandi incendi con colormap hot (gradiente basato su FRP)
            ax1.scatter(large_fires.geometry.x, large_fires.geometry.y, c=large_fires['frp'], cmap='hot', s=np.sqrt(large_fires['frp'])*3, alpha=0.9, edgecolors='black', linewidth=0.3)
            ax1.axis('off')

            # Mappa 2: ROBUSTA
            ax2.set_title('Produzione Robusta & Incendi Maggiori', fontsize=15, color='white' if st.get_option("theme.base") == "dark" else 'black')
            brazil_map.plot(column='Robusta', ax=ax2, cmap='Purples', edgecolor='white', linewidth=0.5, legend=True, missing_kwds={'color': '#e0e0e0'})
            ax2.scatter(small_fires.geometry.x, small_fires.geometry.y, color='grey', s=3, alpha=0.2, edgecolors='none')
            ax2.scatter(large_fires.geometry.x, large_fires.geometry.y, c=large_fires['frp'], cmap='hot', s=np.sqrt(large_fires['frp'])*3, alpha=0.9, edgecolors='black', linewidth=0.3)
            ax2.axis('off')

            plt.tight_layout()
            st.pyplot(fig)
        except Exception as e:
            st.error(f"Errore durante il recupero dei dati degli incendi: {e}")



# ==========================================
# TAB 2: EL NIÑO / LA NIÑA (ENSO)
# ==========================================
with tab2:
    st.header("Indici ENSO — ONI e SOI")
    
    st.markdown("""
**ONI (Oceanic Niño Index):** anomalia temperatura superficiale Pacifico equatoriale. Indicatore primario globale.
**SOI (Southern Oscillation Index):** differenza di pressione atmosferica Tahiti–Darwin. Risposta atmosferica all'ONI.

**Impatti in Brasile:**
- **El Niño (ONI > 0.5 / SOI < -7):** siccità Nord/Amazzonia, rischio incendi; piogge eccessive al Sud.
- **La Niña (ONI < -0.5 / SOI > +7):** piovosità al Nord, siccità al Sud con danno colture.
- Quando ONI e SOI superano entrambe le soglie (evento accoppiato), gli impatti agricoli sono più severi e prevedibili.
    """)

    @st.cache_data(ttl=86400) # La cache dura 24h: protegge dalle chiamate API eccessive (i dati NOAA si aggiornano mensilmente)
    def fetch_enso_data():
        # Indice ONI (Oceanico)
        url_oni = "https://psl.noaa.gov/data/correlation/oni.data"
        resp_oni = requests.get(url_oni)
        lines = resp_oni.text.split('\n')
        data_lines = [line for line in lines if len(line.split()) >= 13 and line.split()[0].isdigit() and int(line.split()[0]) >= 1950]
        cols = ['Year', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        df_oni = pd.DataFrame([l.split()[:13] for l in data_lines], columns=cols).set_index('Year').astype(float)
        df_oni[df_oni < -90] = np.nan # Rimuove i "filler" della NOAA (spesso -99.90 o -99.99) per mesi non ancora registrati
        return df_oni.stack()

    @st.cache_data(ttl=86400)
    def fetch_soi_data():
        # Indice SOI (Atmosferico)
        url_soi = "https://psl.noaa.gov/data/correlation/soi.data"
        resp_soi = requests.get(url_soi)
        lines = resp_soi.text.split('\n')
        data_lines = [line for line in lines if len(line.split()) >= 13 and line.split()[0].isdigit() and int(line.split()[0]) >= 1950]
        cols = ['Year', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        df_soi = pd.DataFrame([l.split()[:13] for l in data_lines], columns=cols).set_index('Year').astype(float)
        df_soi[df_soi < -90] = np.nan # Rimuove valori fittizi
        return df_soi.stack()

    with st.spinner("Scaricamento e analisi degli indici climatici NOAA più recenti in corso..."):
        try:
            oni_series = fetch_enso_data()
            soi_series = fetch_soi_data()
            
            # Estrae gli ultimissimi dati reali registrati
            latest_oni = oni_series.iloc[-1]
            latest_oni_period = oni_series.index[-1]
            
            latest_soi = soi_series.iloc[-1]
            latest_soi_period = soi_series.index[-1]

            # Determina Livello di Allerta basato sull'ONI (indicatore primario globale)
            if latest_oni >= 0.5:
                phase, color = "EL NIÑO", "red"
                advice = "Rischio siccità Nord/Amazzonia; Rischio inondazioni al Sud."
                if latest_soi <= -7:
                    advice += " (⚠️ Evento atmosferico accoppiato: impatti forti confermati)"
            elif latest_oni <= -0.5:
                phase, color = "LA NIÑA", "blue"
                advice = "Danni alle colture al Sud (siccità); Molto piovoso al Nord."
                if latest_soi >= 7:
                    advice += " (⚠️ Evento atmosferico accoppiato: impatti forti confermati)"
            else:
                phase, color = "NEUTRALE", "green"
                advice = "Nessuna anomalia climatica drastica in corso."

            # Metriche principali
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Ultimo Aggiornamento", f"{latest_oni_period[0]} - {latest_oni_period[1]}")
            # Aggiungo i delta per far vedere il trend rispetto al mese precedente
            col2.metric("Indice ONI (Oceanico)", f"{latest_oni} °C", delta=f"{round(latest_oni - oni_series.iloc[-2], 2)} °C", delta_color="inverse")
            col3.metric("Indice SOI (Atmosferico)", f"{latest_soi}", delta=f"{round(latest_soi - soi_series.iloc[-2], 2)}", delta_color="normal")
            col4.markdown(f"**Fase Attuale:**<br><span style='color:{color}; font-size:1.4em; font-weight:bold;'>{phase}</span>", unsafe_allow_html=True)
            
            st.info(f"**Previsione Impatto Agricolo in Brasile:** {advice}")

            st.divider()

            # Crea Layout a due colonne per i grafici
            fig_col1, fig_col2 = st.columns(2)

            # --- GRAFICO 1: ONI ---
            with fig_col1:
                st.subheader("Indice ONI (Oceanico)")
                fig_oni, ax_oni = plt.subplots(figsize=(8, 4))
                fig_oni.patch.set_facecolor('none')
                latest_oni_years = oni_series.tail(36) # Mostra gli ultimi 3 anni
                
                ax_oni.plot(range(len(latest_oni_years)), latest_oni_years.values, color='black', lw=1.5, marker='o', markersize=4)
                ax_oni.axhline(y=0.5, color='red', linestyle='--', label='Soglia El Niño (+0.5)')
                ax_oni.axhline(y=-0.5, color='blue', linestyle='--', label='Soglia La Niña (-0.5)')
                ax_oni.axhline(y=0, color='gray', linestyle='-', alpha=0.5)
                
                # Colora in rosso l'area di El Niño e in blu quella di La Niña
                ax_oni.fill_between(range(len(latest_oni_years)), 0.5, np.maximum(latest_oni_years.values, 0.5), where=(latest_oni_years.values >= 0.5), color='red', alpha=0.3)
                ax_oni.fill_between(range(len(latest_oni_years)), -0.5, np.minimum(latest_oni_years.values, -0.5), where=(latest_oni_years.values <= -0.5), color='blue', alpha=0.3)
                
                ax_oni.set_xticks(range(len(latest_oni_years)))
                ax_oni.set_xticklabels([f"{idx[0]}-{idx[1]}" for idx in latest_oni_years.index], rotation=90, fontsize=7)
                ax_oni.legend(loc='upper left', fontsize=8)
                st.pyplot(fig_oni)
                st.caption("L'ONI misura l'anomalia termica dell'Oceano Pacifico. Valori positivi indicano riscaldamento (El Niño), negativi raffreddamento (La Niña).")

            # --- GRAFICO 2: SOI ---
            with fig_col2:
                st.subheader("Indice SOI (Atmosferico)")
                fig_soi, ax_soi = plt.subplots(figsize=(8, 4))
                fig_soi.patch.set_facecolor('none')
                latest_soi_years = soi_series.tail(36) # Allinea al grafico ONI
                
                # Grafico a barre (standard meteorologico per l'indice SOI)
                colors = ['blue' if val >= 0 else 'red' for val in latest_soi_years.values]
                ax_soi.bar(range(len(latest_soi_years)), latest_soi_years.values, color=colors, alpha=0.7)
                ax_soi.axhline(y=7, color='blue', linestyle='--', label='Soglia La Niña (+7)')
                ax_soi.axhline(y=-7, color='red', linestyle='--', label='Soglia El Niño (-7)')
                ax_soi.axhline(y=0, color='black', linestyle='-', linewidth=1)
                
                ax_soi.set_xticks(range(len(latest_soi_years)))
                ax_soi.set_xticklabels([f"{idx[0]}-{idx[1]}" for idx in latest_soi_years.index], rotation=90, fontsize=7)
                ax_soi.legend(loc='upper left', fontsize=8)
                st.pyplot(fig_soi)
                st.caption("Il SOI mostra la risposta dell'atmosfera. Barre BLU forti confermano La Niña, barre ROSSE forti confermano El Niño. Se in contrasto con l'ONI, l'evento climatico è debole.")

        except Exception as e:
            st.error(f"Errore durante l'aggiornamento dei dati ENSO: {e}")


# ==========================================
# TAB 3: PORTI LIVE (CICLO PERPETUO)
# ==========================================
with tab3:
    st.header("Monitoraggio Navale — Porti (Live AIS)")

    st.warning(
        "NOTA DEMO: i dati si riferiscono a hub portuali globali (Singapore, Rotterdam, Los Angeles) "
        "anziché ai porti brasiliani, per via della copertura frammentata dei servizi AIS gratuiti in Sud America."
    )

    st.markdown("""
- Ascolto WebSocket AIS globale. Filtro attivo: solo navi cargo (codici AIS 70-79).
- Le navi trasmettono posizione ogni 10s ma anagrafica ogni 6 min: alcune imbarcazioni impiegano qualche minuto per essere classificate come cargo.
    """)

    API_KEY = "23dff2542eb48c414c4c0213de19b29dd4deaa30"
    
    # Bounding Boxes per i porti selezionati
    PORTS = {
        "Port of Singapore": [[1.10, 103.55], [1.35, 104.10]],
        "Port of Rotterdam": [[51.90, 3.90], [52.00, 4.20]],
        "Port of Los Angeles": [[33.65, -118.30], [33.80, -118.15]]
    }

    def get_port_zone(lat, lon):
        if lat is None or lon is None: 
            return None
        for port_name, box in PORTS.items():
            if box[0][0] <= lat <= box[1][0] and box[0][1] <= lon <= box[1][1]:
                return port_name
        return None

    # INIZIALIZZA LE MEMORIE DI STREAMLIT
    if 'tracked_vessels' not in st.session_state:
        st.session_state.tracked_vessels = {}
    if 'ship_types' not in st.session_state:
        st.session_state.ship_types = {}

    async def listen_ports_for_ns():
        try:
            async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
                subscribe_message = {
                    "APIKey": API_KEY,
                    "BoundingBoxes": list(PORTS.values()),
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
                }
                await websocket.send(json.dumps(subscribe_message))
                
                start_time = time.time()
                # 30 secondi di ascolto per dare tempo ai pacchetti di arrivare
                while time.time() - start_time < 30:
                    try:
                        message_json = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        message = json.loads(message_json)
                        msg_type = message.get("MessageType")
                        
                        if msg_type == "ShipStaticData":
                            data = message["Message"]["ShipStaticData"]
                            mmsi = data.get("UserID")
                            ship_type = data.get("Type", 0)
                            st.session_state.ship_types[mmsi] = ship_type
                            
                        elif msg_type == "PositionReport":
                            data = message["Message"]["PositionReport"]
                            mmsi = data.get("UserID")
                            lat, lon = data.get("Latitude"), data.get("Longitude")
                            sog = data.get("Sog", 0) 
                            status = data.get("NavigationalStatus", 99)
                            
                            port = get_port_zone(lat, lon)
                            if port:
                                st.session_state.tracked_vessels[mmsi] = {
                                    "port": port, 
                                    "sog": sog, 
                                    "status": status,
                                    "last_seen": time.time()
                                }
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        pass
        except Exception:
            pass

    # UI Placeholder
    live_placeholder = st.empty()

    with live_placeholder.container():
        
        # 1. ASCOLTO DATI IN BACKGROUND
        asyncio.run(listen_ports_for_ns())

        # 2. SPAZZINO (Rimuove navi non viste da 15 minuti / 900 secondi)
        current_time = time.time()
        for mmsi in list(st.session_state.tracked_vessels.keys()):
            if current_time - st.session_state.tracked_vessels[mmsi]["last_seen"] > 900:
                del st.session_state.tracked_vessels[mmsi]
                if mmsi in st.session_state.ship_types:
                    del st.session_state.ship_types[mmsi]

        # 3. CALCOLO METRICHE GLOBALI (Il contatore generale in alto)
        tot_vessels = len(st.session_state.tracked_vessels)
        tot_cargo_known = sum(1 for t in st.session_state.ship_types.values() if 70 <= t <= 79)
        
        # 4. CALCOLO METRICHE SPECIFICHE PER PORTO
        results = {port: {"cargo_sosta": 0, "cargo_transito": 0, "totali_sconosciute": 0} for port in PORTS.keys()}
        
        for mmsi, v in st.session_state.tracked_vessels.items():
            port = v["port"]
            ship_type = st.session_state.ship_types.get(mmsi, 0)
            
            # Se è confermata come Cargo (70-79) la dividiamo per velocità/stato
            if 70 <= ship_type <= 79:
                if v["sog"] < 1.0 or v["status"] in [1, 5]:
                    results[port]["cargo_sosta"] += 1
                else:
                    results[port]["cargo_transito"] += 1
            else:
                # Se non sappiamo ancora cos'è, la mettiamo in "attesa di anagrafica"
                results[port]["totali_sconosciute"] += 1

        # 5. RENDER DELL'INTERFACCIA
        st.info(f"In ascolto AIS... Navi rilevate: {tot_vessels} | Cargo confermate: {tot_cargo_known}")
        st.success(f"Ultimo aggiornamento: {time.strftime('%H:%M:%S')} — prossimo ciclo tra 30s")
        
        cols = st.columns(len(PORTS))
        
        for i, (port_name, counts) in enumerate(results.items()):
            with cols[i]:
                st.markdown(f"**{port_name}**")
                st.metric("Cargo in Transito", counts["cargo_transito"])
                st.metric("Cargo in Sosta", counts["cargo_sosta"])
                st.caption(f"In attesa di classificazione: {counts['totali_sconosciute']}")
        
        time.sleep(2)
        st.rerun()
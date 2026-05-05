"""
llm_analyzer.py — Analizzatore schema-agnostico con Claude Haiku.

DESIGN PRINCIPLE:
  Nessun campo MongoDB è hardcodato qui o negli agenti che usano questa funzione.
  Haiku legge i documenti, capisce da solo cosa contengono (ONI index, fire count,
  prezzi arabica, volumi export, ...) e produce segnali strutturati.

  Aggiungere una nuova fonte = aggiungere un connettore n8n che salva in MongoDB.
  Il codice Python non cambia.

Usato da: environment_agent, prices_agent, crops_agent, geo_agent.
"""

import json
import os
import re

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Contesti per area — descrivono a Haiku il dominio di rischio
# ---------------------------------------------------------------------------

_AREA_CONTEXT = {
    "environment": {
        "description": (
            "Condizioni climatiche e ambientali che influenzano la produzione di caffè in Brasile: "
            "anomalie ENSO (El Niño / La Niña / neutro), incendi nelle aree agricole, siccità, "
            "precipitazioni anomale nelle regioni produttrici (Minas Gerais, São Paulo, Espírito Santo, Bahia)."
        ),
        "score_scale": (
            "0-20: condizioni ottimali, nessuna perturbazione\n"
            "21-40: lievi anomalie, impatto trascurabile sulla produzione\n"
            "41-60: stress idrico o incendi moderati, attenzione consigliata\n"
            "61-80: perturbazioni significative, potenziale impatto su raccolto\n"
            "81-100: emergenza climatica — danni certi alla produzione"
        ),
    },
    "prices": {
        "description": (
            "Prezzi commodity caffè arabica e robusta sui mercati internazionali, "
            "tassi di cambio BRL/USD ed EUR/BRL che determinano il costo di approvvigionamento "
            "per un torrefattore europeo (Lavazza). "
            "Arabica alto = costo materia prima elevato. BRL debole = instabilità macro. "
            "EUR forte su BRL = vantaggio acquisti per Lavazza."
        ),
        "score_scale": (
            "0-20: prezzi stabili e favorevoli, acquisti convenienti\n"
            "21-40: leggera pressione, situazione gestibile con hedging normale\n"
            "41-60: prezzi elevati, hedging attivo consigliato\n"
            "61-80: prezzi storicamente alti, forte impatto sui margini\n"
            "81-100: shock prezzi — emergenza acquisti, massimi storici"
        ),
    },
    "crops": {
        "description": (
            "Produzione, stock, export e outlook della filiera caffè brasiliana: "
            "previsioni raccolto CONAB, bilanci USDA (produzione/consumo/stock/export), "
            "dati IBGE produzione agricola, Comex Stat export per volume e valore, "
            "FAOSTAT dati storici. "
            "Stock-to-use basso = rischio discontinuità. Produzione alta = mercato abbondante."
        ),
        "score_scale": (
            "0-30: supply abbondante, nessun rischio — ottimo per acquisti\n"
            "31-50: leggero stress, produzione nella norma con qualche attenzione\n"
            "51-70: rischio moderato (calo produzione, export in discesa, stock bassi)\n"
            "71-100: rischio elevato (crisi produzione, export collassato, stock minimi)"
        ),
    },
    "geo": {
        "description": (
            "Rischi geopolitici, commerciali e logistici che possono disturbare la supply chain "
            "del caffè brasiliano verso l'Europa: accordi/dazi commerciali UE-Mercosur, "
            "congestione portuale, tensioni diplomatiche, stabilità politica brasiliana, "
            "sanzioni, proteste, eventi che impattano logistica/export."
        ),
        "score_scale": (
            "0-20: scenario stabile, nessun rischio commerciale significativo\n"
            "21-40: tensioni minori, impatto trascurabile\n"
            "41-60: rischio moderato (dazi, tensioni, proteste locali)\n"
            "61-80: rischio elevato (sanzioni, crisi politica, blocchi logistici)\n"
            "81-100: emergenza — guerra commerciale, embargo, collasso istituzionale"
        ),
    },
}

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Sei un analista specializzato nella supply chain del caffè arabica brasiliano per Lavazza (torrefattore europeo).

Il tuo compito: leggere documenti di dati (qualsiasi schema, qualsiasi fonte) e estrarre segnali di rischio strutturati.

Regole fondamentali:
- NON fare assunzioni sui nomi dei campi: leggi il documento e capisci cosa contiene.
- Se un documento ha campi che non conosci, interpretali dal contesto e dai valori.
- Focalizzati SOLO sui segnali rilevanti per la supply chain del caffè.
- Sii concreto: cita valori numerici specifici nei "fact".
- Rispondi SEMPRE e SOLO con JSON valido, zero testo fuori dal JSON.
"""

_USER_TEMPLATE = """\
AREA DI ANALISI: {area}
DOMINIO: {description}
PAESE: {country}

=== DOCUMENTI DA ANALIZZARE ===
{docs_text}

=== ISTRUZIONI ===
Leggi ogni documento, identifica i dati rilevanti (qualunque siano i nomi dei campi),
e produci segnali di rischio per la supply chain caffè brasiliana.

Scala di riferimento per lo score di quest'area:
{score_scale}

Rispondi con questo JSON esatto:
{{
  "signals": [
    {{
      "source": "<valore del campo 'source' nel documento>",
      "area": "{area}",
      "fact": "<fatto chiave con valori numerici, max 120 caratteri>",
      "direction": "<positive|negative|neutral>",
      "intensity": "<low|medium|high>",
      "explanation": "<perché questo fatto impatta la supply caffè, max 200 caratteri>"
    }}
  ],
  "summary": "<sintesi rischio {area} in 2-3 frasi con i dati più rilevanti>",
  "score": <numero float 0-100 secondo la scala fornita>
}}

Genera 1 segnale per documento (2 se il documento è molto ricco).
Se un dato è neutro o irrilevante per il caffè, usa direction=neutral e intensity=low.
"""


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def _prepare_doc_text(doc: dict) -> str:
    """
    Prepara il testo di un documento per il prompt.
    Rimuove solo _id e _chart_fields (tecnici). Tutto il resto va al modello.
    Tronca array/dict molto grandi per non esplodere il context window.
    """
    result = {}
    for k, v in doc.items():
        if k in ("_id", "_chart_fields"):
            continue
        text_repr = str(v)
        if len(text_repr) > 600:
            # tronca preservando inizio (i dati più recenti sono tipicamente all'inizio)
            result[k] = text_repr[:600] + " ...[troncato]"
        else:
            result[k] = v
    return json.dumps(result, ensure_ascii=False, indent=2)


def analyze_with_haiku(
    docs: list[dict],
    area: str,
    country: str = "BR",
) -> dict | None:
    """
    Analizza una lista di documenti MongoDB con Claude Haiku.

    Completamente schema-agnostico: Haiku legge il documento e capisce
    da solo cosa contiene. Non viene hardcodato nessun nome di campo.

    Args:
        docs:    lista di documenti MongoDB (qualsiasi schema)
        area:    "environment" | "prices" | "crops" | "geo"
        country: codice paese (default "BR")

    Returns:
        {
          "signals": [...],   # lista segnali strutturati
          "summary": str,     # sintesi testuale
          "score": float      # 0-100
        }
        None in caso di errore API.
    """
    if not docs:
        return None

    ctx = _AREA_CONTEXT.get(area, {
        "description": f"Analisi dati area {area} per la supply chain caffè Brasile.",
        "score_scale": "0-100: rischio crescente",
    })

    # costruisci il testo dei documenti
    doc_parts = []
    for doc in docs:
        source = doc.get("source", "unknown")
        doc_parts.append(f"--- Documento: {source} ---\n{_prepare_doc_text(doc)}")

    docs_text = "\n\n".join(doc_parts)

    user_message = _USER_TEMPLATE.format(
        area=area,
        description=ctx["description"],
        country=country,
        docs_text=docs_text,
        score_scale=ctx["score_scale"],
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        # rimuovi eventuali code fence
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)

    except (anthropic.APIError, json.JSONDecodeError, IndexError) as e:
        print(f"[llm_analyzer] Errore Haiku (area={area}): {e}")
        return None

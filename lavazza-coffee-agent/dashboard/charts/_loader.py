"""_loader.py — Funzione _load(): orchestrazione MongoDB → API → Simulato."""

from ._data_sim import (
    _sim_oni, _sim_soi, _sim_fires, _sim_prices, _sim_usda, _sim_faostat,
    _sim_conab, _sim_ibge, _sim_comex, _sim_fertilizers,
)
from ._data_mongo import (
    _mongo_oni, _mongo_fires, _mongo_prices, _mongo_fertilizers,
    _mongo_usda, _mongo_faostat, _mongo_conab, _mongo_ibge, _mongo_comex,
)
from ._data_api import (
    _api_oni, _api_soi, _api_fires, _api_prices, _api_usda, _api_faostat, _api_fertilizers,
)


def _load(name: str, country: str = "BR", use_api: bool = False):
    """
    Carica dati per 'name' con due modalità distinte:

    use_api=False (MongoDB):  MongoDB → Simulato
    use_api=True  (API):      API     → Simulato

    La modalità API NON usa MongoDB: mostra sempre dati live dalle fonti esterne.
    Fonti senza API diretta (conab, ibge, comex) usano sempre MongoDB → Simulato.
    """
    def _first(*fns):
        """Chiama le funzioni in ordine e restituisce il primo risultato non-None."""
        for fn in fns:
            try:
                result = fn()
                if result is not None:
                    return result
            except Exception:
                pass
        return None

    if name == "oni":
        if use_api:
            return _first(_api_oni, _sim_oni)
        else:
            return _first(lambda: _mongo_oni(country), _sim_oni)

    if name == "soi":
        # SOI non è in MongoDB — API o simulato
        if use_api:
            return _first(_api_soi, _sim_soi)
        else:
            return _sim_soi()

    if name == "fires":
        if use_api:
            return _first(_api_fires, _sim_fires)
        else:
            return _first(lambda: _mongo_fires(country), _sim_fires)

    if name == "prices":
        if use_api:
            return _first(_api_prices, _sim_prices)
        else:
            return _first(lambda: _mongo_prices(country), _sim_prices)

    if name == "usda":
        if use_api:
            return _first(_api_usda, _sim_usda)
        else:
            return _first(lambda: _mongo_usda(country), _sim_usda)

    if name == "faostat":
        if use_api:
            return _first(_api_faostat, _sim_faostat)
        else:
            return _first(lambda: _mongo_faostat(country), _sim_faostat)

    if name == "fertilizers":
        if use_api:
            return _first(_api_fertilizers, _sim_fertilizers)
        else:
            return _first(lambda: _mongo_fertilizers(country), _sim_fertilizers)

    # Le fonti seguenti non hanno API diretta: sempre MongoDB → Simulato
    if name == "conab":
        return _first(lambda: _mongo_conab(country), _sim_conab)

    if name == "ibge":
        return _first(lambda: _mongo_ibge(country), _sim_ibge)

    if name == "comex":
        return _first(lambda: _mongo_comex(country), _sim_comex)

    raise ValueError(f"Dataset sconosciuto: {name}")

# data_sources organization

This folder is organized by category:

- `colture/`
  - `conab/`
  - `faostat/`
  - `usda/`
  - `Conab_pdf_download.ipynb`
- `prices/`
  - `world_bank/`
- `geo/`
  - `gdelt/`
  - `port_livedata.ipynb`
- `environment/`
  - `El_Niño.ipynb`
  - `Fire_data_Brazil.ipynb`
- `requirements.txt` shared dependencies for data source scripts

Python scripts now use paths relative to their own file location, so this structure is stable if folders are moved again.

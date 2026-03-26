import faostat
import pandas as pd
from datetime import datetime
import numpy as np

my_token = 'eyJraWQiOiJVSFE2dmwrekFTaGRpSGpsOFFSK0d2ZW13RWIzSjZNdytYNTRURXZtNUNJPSIsImFsZyI6IlJTMjU2In0.eyJzdWIiOiJiOTNiN2JjNS0zYTNkLTQ4ZjctODM1OS02NDBjYTBhNjc5NzEiLCJpc3MiOiJodHRwczpcL1wvY29nbml0by1pZHAuZXUtd2VzdC0xLmFtYXpvbmF3cy5jb21cL2V1LXdlc3QtMV9iTkVMTk9DMnYiLCJ2ZXJzaW9uIjoyLCJjbGllbnRfaWQiOiIyY3NsdHNpZ2FvODVpdmhwNm9qcDFhaWM3byIsIm9yaWdpbl9qdGkiOiJiN2IzNTY3ZC00MjFjLTQ4MzYtYTdiMC1lNmJmMTRiMjY4OWIiLCJldmVudF9pZCI6Ijg5NzgxOTg4LWNjNmYtNDgxNC1iZDg2LWQ0ZDQ5ZjY1NjVjZSIsInRva2VuX3VzZSI6ImFjY2VzcyIsInNjb3BlIjoiYXdzLmNvZ25pdG8uc2lnbmluLnVzZXIuYWRtaW4gcGhvbmUgb3BlbmlkIHByb2ZpbGUgZW1haWwiLCJhdXRoX3RpbWUiOjE3NzQ0Nzk1MDgsImV4cCI6MTc3NDQ4MzEwOCwiaWF0IjoxNzc0NDc5NTA4LCJqdGkiOiJkMGE0NWU3Ni0yYzk3LTRiMGMtODFiNS05ZDg2MTE5NzM2ZGIiLCJ1c2VybmFtZSI6IkZyYW5jZXNjbyJ9.QRYsb04HRxNF1jlUngGAyLN7mZLkS7UhhIBUYEYStWaMjUuMlPWUqbFFa0s5IvwcqgC1BRPWSf6L8eTXKoaY6E7wvEJGX3uGj4dUC9YLutkkQD3cbUGF8vFBHfZBx3Anj3v9JSwHKFevYSsH4rxv8SJSoYV06ta-PtR2FGinVbnYEOaY7VG86Bd3VPRAQuTG1aL5iWRnOTibkevX1kRbDBjY1AFW7-XxT-gpGUNe_0jDXGFZUviOnKK4nL29KqU2sCotumrqi61u-dydFHbPq-w-ybCUJyC0ApwZvMk4F33zuk8Kqf8uXxiBZ7VKB2RCuG2YG3MzRZXJowIyLCI2eA'

faostat.set_requests_args(token = my_token)


mypars = {'area':'21',
          'element':[2312, 2413, 2510, 2111, 2313],
          'item':'656'}
df = faostat.get_data_df('QCL', pars=mypars)

# 1. PIVOT DEI DATI
# Trasformiamo la colonna 'Element' in intestazioni di colonna
df_pivot = df.pivot_table(
    index='Year', 
    columns='Element', 
    values='Value', 
    aggfunc='first'
).reset_index()

# 2. CREAZIONE DEL DATAFRAME PER MONGODB
df_mongo = pd.DataFrame()

# PRIMA inseriamo i dati reali, così Pandas crea le righe
df_mongo['season'] = df_pivot['Year'].astype(str)
df_mongo['production_mt'] = df_pivot['Production']
df_mongo['yield_kgha'] = df_pivot['Yield']

# ORA inseriamo i valori fissi. Dato che la tabella ha le righe, 
# Pandas riempirà tutte le celle correttamente.
df_mongo['region'] = None  
df_mongo['country'] = 'BR'
df_mongo['export_mt'] = None
df_mongo['source'] = 'faostat'
df_mongo['collected_at'] = datetime.now()

# Riordino le colonne in base al tuo schema
mongo_schema_cols = [
    'region', 'country', 'season', 'production_mt', 
    'yield_kgha', 'export_mt', 'source', 'collected_at'
]
df_mongo = df_mongo[mongo_schema_cols]

# 3. PULIZIA PER MONGODB (Sostituisco NaN con None)
df_mongo = df_mongo.replace({np.nan: None})

print("Anteprima dei dati da inserire:")
print(df_mongo) # Mostra gli ultimi anni per verifica
import glob
import os
import pandas as pd

#lectura del ultimo archivo en la carpeta
archivos = glob.glob("data\\raw\\dian\\*.xlsx")
ultimo_archivo = max(archivos, key=os.path.getmtime)
print(f"Leyendo archivo: {ultimo_archivo}")

df = pd.read_excel(ultimo_archivo)

#Filtrado de columnas
df = df[["Tipo de documento","Fecha Emisión","NIT Emisor","Nombre Emisor","Prefijo","Folio","CUFE/CUDE","Total"]]
df["Factura"] = df["Prefijo"].fillna("").astype(str) + df["Folio"].fillna("").astype(str)
print(df.head())

#ajuste de tipos de datos
df["NIT Emisor"] = df["NIT Emisor"].astype(str)
df["Fecha Emisión"] = pd.to_datetime(df["Fecha Emisión"], format="%d-%m-%Y")

df_bd = pd.read_parquet("data\\staging\\dian.parquet")

df_final = pd.concat([df_bd, df], ignore_index=True)
df_final = df_final.drop_duplicates(subset=["CUFE/CUDE"], keep="last")

print("dian actualizado")
#Guardar como parquet
df_final.to_parquet("data\\staging\\dian.parquet", index=False)
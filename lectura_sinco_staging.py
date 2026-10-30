import glob
import os
import pandas as pd

#lectura del ultimo archivo en la carpeta
archivos = glob.glob("data\\raw\\sinco\\*.xlsx")
ultimo_archivo = max(archivos, key=os.path.getmtime)
print(f"Leyendo archivo: {ultimo_archivo}")

df = pd.read_excel(ultimo_archivo)

print(df.dtypes)
#Filtrado de datos: se excluyen las facturas con documento contable pero sin fecha de contabilización (anuladas)
anuladas = df["Documento Contable"].notna() & df["Fecha contabilización documento contable"].isna()
df = df[~anuladas]

if df.empty:
    print("No hay facturas que cumplan el filtro; no se actualiza el staging.")
    raise SystemExit


#Ajuste en columnas
df = df[["No. Factura","Proveedor","Fecha factura","Fecha radicado","Obra","Documento ADPRO","Documento Contable","Actividad","Responsable","Valor Total", "Radicado", "Estado"]]
df[["Nombre_tercero", "NIT_tercero"]] = df["Proveedor"].str.rsplit(" - ", n=1, expand=True)
df["Nombre_tercero"] = df["Nombre_tercero"].str.strip()
df["NIT_tercero"] = df["NIT_tercero"].str.strip()
print(df.head())



#ajuste de tipos de datos
df["Valor Total"] = df["Valor Total"].str.replace(",", "").astype(float)
df["Fecha factura"] = pd.to_datetime(df["Fecha factura"].str.slice(0, 10), format="%d/%m/%Y")
df["Fecha radicado"] = pd.to_datetime(df["Fecha radicado"].str.slice(0, 10), format="%d/%m/%Y")

df_bd = pd.read_parquet("data\\staging\\sinco.parquet")

df_final = pd.concat([df_bd, df], ignore_index=True)
df_final = df_final.drop_duplicates(subset=["Proveedor", "No. Factura", "Radicado"], keep="last")

#se excluyen los radicados cancelados; se filtra después de quitar duplicados para que
#un radicado que se cancela en un archivo nuevo también salga del staging
df_final = df_final[df_final["Estado"] != "Cancelada"]

print("Sinco actualizado")

#Guardar como parquet
df_final.to_parquet("data\\staging\\sinco.parquet", index=False)
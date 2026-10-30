import pandas as pd
import numpy as np

#lectura de archivos
df_dian = pd.read_parquet("data\\staging\\dian.parquet")
df_dian.columns = ["Tipo_documento","Fecha","NIT_tercero","Nombre_tercero","Prefijo","Folio","CUFE/CUDE","Total", "Factura"]


df_sinco = pd.read_parquet("data\\staging\\sinco.parquet")
df_sinco.columns = ["Factura","Proveedor","Fecha","Fecha_radicado","Obra","Documento_ADPRO","Documento_Contable","Actividad","Responsable", "Total","Radicado" , "Estado_radicado", "Nombre_tercero", "NIT_tercero"]

#Aguas de la Prosperidad: en SINCO se radica como 020000 + folio y en DIAN es SPD + folio
aguas_prosperidad = (df_sinco["NIT_tercero"] == "901122927") & df_sinco["Factura"].str.startswith("020000", na=False)
df_sinco.loc[aguas_prosperidad, "Factura"] = "SPD" + df_sinco.loc[aguas_prosperidad, "Factura"].str[6:]

#Combinación de los dataframes
df = pd.merge(df_dian, df_sinco, how="outer", on=["Factura", "NIT_tercero"], suffixes=("_dian", "_sinco"))


#Creación de columna de final
df["Fecha"] = df["Fecha_dian"].fillna(df["Fecha_sinco"])
df["Nombre_tercero"] = df["Nombre_tercero_dian"].fillna(df["Nombre_tercero_sinco"])


#nuevas columnas
df["estado"] = np.where(df["Total_dian"] == df["Total_sinco"], True, False)
df["NIT_factura"] =   df["NIT_tercero"].fillna("").astype(str)+ "_" + df["Factura"].fillna("").astype(str)

#limpieza de columnas
df = df[["NIT_factura","Fecha",  "Nombre_tercero","NIT_tercero","Factura",  "Total_dian", "Total_sinco","Radicado", "Fecha_radicado", "Obra","Documento_ADPRO","Documento_Contable","Actividad","Responsable","estado","Tipo_documento", "Estado_radicado"]]


#df de no conciliados
df_no_conciliados_enDian = df[(df["estado"] == False)&(df["Total_dian"].notnull())]

# Exportación del dataframe final
df.to_csv("data\\analytics\\conciliacion_detallas.csv", index=False)
df_no_conciliados_enDian.to_csv("data\\analytics\\conciliacion_no_conciliados_Dian.csv", index=False)
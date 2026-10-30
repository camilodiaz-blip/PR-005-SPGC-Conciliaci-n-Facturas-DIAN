"""
Conciliación de cajas menores
=============================
Se corre después de conciliacion.py. Complementa data/analytics/conciliacion_detallas.csv
con el detalle de las cajas menores (data/staging/caja_menor_reembolsos.parquet):

1. Las facturas DIAN que vienen dentro de una caja menor y no tienen datos SINCO toman el
   valor de la línea de caja menor (Total_sinco) y los datos del radicado en SINCO
   (Radicado, Estado_radicado, Documento_Contable, ...). estado admite diferencia de 1 peso.
2. Se quitan las líneas SINCO del custodio de la caja (CM...), porque quedan reemplazadas por
   su detalle; solo cuando la caja cuadra con el valor del radicado.
3. Se sobrescriben conciliacion_detallas.csv y conciliacion_no_conciliados_Dian.csv sin
   cambiar su estructura.

Se puede correr varias veces: las filas ya completadas no se vuelven a tocar.
"""

import pandas as pd

DETALLE = "data\\analytics\\conciliacion_detallas.csv"
NO_CONCILIADOS = "data\\analytics\\conciliacion_no_conciliados_Dian.csv"
TOLERANCIA = 1

# se lee todo como texto para no cambiar el formato del archivo final
df = pd.read_csv(DETALLE, dtype=str, keep_default_na=False)
columnas = list(df.columns)

caja = pd.read_parquet("data\\staging\\caja_menor_reembolsos.parquet")
caja["NIT_factura"] = caja["nit"] + "_" + caja["numero_factura"]

sinco = pd.read_parquet("data\\staging\\sinco.parquet")
radicados = sinco[sinco["Radicado"].isin(caja["radicado"])].drop_duplicates("Radicado", keep="last")
radicados = radicados.set_index("Radicado")

# ------------------------------------------------- control de cada caja menor
suma_caja = caja.groupby("radicado")["total"].sum()
control = pd.DataFrame({"suma_caja": suma_caja, "valor_sinco": radicados["Valor Total"]})
control["cuadra"] = (control["suma_caja"] - control["valor_sinco"]).abs() <= TOLERANCIA

sin_sinco = control[control["valor_sinco"].isna()].index.tolist()
no_cuadran = control[control["valor_sinco"].notna() & ~control["cuadra"]].index.tolist()
if sin_sinco:
    print(f"Radicados de caja menor que no están en SINCO: {sin_sinco}")
if no_cuadran:
    print(f"Cajas que no cuadran con SINCO (se dejan las líneas CM): {no_cuadran}")

# --------------------------- 1. completar facturas DIAN que vienen en una caja
lineas = caja[caja["radicado"].isin(radicados.index)].drop_duplicates("NIT_factura", keep="last")
lineas = lineas.set_index("NIT_factura")

completar = (df["NIT_factura"].isin(lineas.index) & (df["Total_dian"] != "")
             & (df["Total_sinco"] == "") & (df["Radicado"] == ""))

for i in df.index[completar]:
    linea = lineas.loc[df.at[i, "NIT_factura"]]
    radicado = radicados.loc[linea["radicado"]]

    df.at[i, "Total_sinco"] = str(float(linea["total"]))
    df.at[i, "Radicado"] = linea["radicado"]
    df.at[i, "Fecha_radicado"] = radicado["Fecha radicado"].strftime("%Y-%m-%d") \
        if pd.notna(radicado["Fecha radicado"]) else ""
    df.at[i, "Obra"] = radicado["Obra"] if pd.notna(radicado["Obra"]) else ""
    df.at[i, "Documento_ADPRO"] = radicado["Documento ADPRO"] if pd.notna(radicado["Documento ADPRO"]) else ""
    df.at[i, "Documento_Contable"] = radicado["Documento Contable"] if pd.notna(radicado["Documento Contable"]) else ""
    df.at[i, "Actividad"] = radicado["Actividad"] if pd.notna(radicado["Actividad"]) else ""
    df.at[i, "Responsable"] = radicado["Responsable"] if pd.notna(radicado["Responsable"]) else ""
    df.at[i, "Estado_radicado"] = radicado["Estado"] if pd.notna(radicado["Estado"]) else ""
    df.at[i, "estado"] = str(abs(float(df.at[i, "Total_dian"]) - float(linea["total"])) <= TOLERANCIA)

# ------------------------------------------ 2. quitar las líneas CM del custodio
custodio = {(r, row["NIT_tercero"] + "_" + row["No. Factura"])
            for r, row in radicados.iterrows() if r in control.index[control["cuadra"]]}
quitar = [(r, k) in custodio for r, k in zip(df["Radicado"], df["NIT_factura"])]
quitar = pd.Series(quitar, index=df.index) & (df["Total_dian"] == "")

df = df[~quitar]

# --------------------------------------------------------------------- guarda
df = df[columnas]
df.to_csv(DETALLE, index=False)
df[(df["estado"] == "False") & (df["Total_dian"] != "")].to_csv(NO_CONCILIADOS, index=False)

completadas = df[completar[df.index]]
en_dian = df.loc[df["Total_dian"] != "", "NIT_factura"]
print(f"Facturas DIAN completadas con caja menor: {len(completadas)} "
      f"({(completadas['estado'] == 'True').sum()} conciliadas)")
print(f"Líneas CM del custodio quitadas: {quitar.sum()}")
print(f"Líneas de caja menor sin factura en DIAN: {(~caja['NIT_factura'].isin(en_dian)).sum()}")
print("Conciliación actualizada")

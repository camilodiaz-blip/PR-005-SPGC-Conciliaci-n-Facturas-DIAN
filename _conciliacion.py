"""
02 - Cruce
==========
Toma los parquet de staging y busca cada factura conciliada con la DIAN
dentro del libro contable.

Se prueban tres llaves, de la más fuerte a la más débil:
    1  número de factura == documento_tercero, el NIT coincide y el valor también
    2  número de factura == documento_tercero  y  el NIT coincide
    3  NIT del emisor  y  valor idéntico al saldo de una partida
Si ninguna cruza, queda como sin rastro.

Salida:
    cruce_dian_libro_contable.csv  (una sola hoja, una fila por factura)
"""

from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
STAGING = BASE / "data" / "staging"
ANALYTICS = BASE / "data" / "analytics"
ANALYTICS.mkdir(parents=True, exist_ok=True)
SALIDA = ANALYTICS / "cruce_dian_libro_contable.csv"

facturas = pd.read_parquet(STAGING / "facturas_dian.parquet")
libro = pd.read_parquet(STAGING / "libro_contable.parquet")

# solo interesan los terceros que facturan: reduce el libro de 82k a unas pocas filas
nits_facturados = set(facturas["nit"])
libro = libro[libro["nit"].isin(nits_facturados)]


def agrupar(llaves, sufijo):
    """Resume el libro por llave: comprobantes, fechas de registro y valor contable."""
    return (
        libro.groupby(llaves)
        .agg(
            cp=("CP", lambda s: "; ".join(str(x) for x in sorted(set(s)))),
            registro=("fecha", lambda s: "; ".join(sorted(set(s.dt.strftime("%Y-%m-%d"))))),
            valor=("saldo", "sum"),
        )
        .reset_index()
        .rename(columns={"cp": f"cp_{sufijo}", "registro": f"registro_{sufijo}", "valor": f"valor_{sufijo}"})
    )


# llave 1: documento + NIT + valor     llave 2: documento + NIT     llave 3: NIT + valor
por_completo = agrupar(["doc_norm", "nit", "valor_int"], "completo")
por_documento = agrupar(["doc_norm", "nit"], "doc")
por_valor = agrupar(["nit", "valor_int"], "val")

cruce = (
    facturas.merge(por_completo, on=["doc_norm", "nit", "valor_int"], how="left")
    .merge(por_documento, on=["doc_norm", "nit"], how="left")
    .merge(por_valor, on=["nit", "valor_int"], how="left")
)

# se prefiere la coincidencia más fuerte: completo > documento > valor
cruce["DocumentoContable_CP"] = (
    cruce["cp_completo"].fillna(cruce["cp_doc"]).fillna(cruce["cp_val"]).fillna("")
)
cruce["FechaRegistro"] = (
    cruce["registro_completo"].fillna(cruce["registro_doc"]).fillna(cruce["registro_val"]).fillna("")
)
cruce["ValorContable"] = cruce["valor_completo"].fillna(cruce["valor_doc"]).fillna(cruce["valor_val"])

cruce["Cruce"] = "4-sin rastro"
cruce.loc[cruce["cp_val"].notna(), "Cruce"] = "3-NIT y valor"
cruce.loc[cruce["cp_doc"].notna(), "Cruce"] = "2-documento y NIT"
cruce.loc[cruce["cp_completo"].notna(), "Cruce"] = "1-documento, NIT, valor"

detalle = (
    cruce.rename(
        columns={
            "fecha": "FechaDocumento",
            "nit": "IdentificacionEmisor",
        }
    )[
        [
            "TipoDocumento",
            "NumeroDocumento",
            "FechaDocumento",
            "NombreEmisor",
            "IdentificacionEmisor",
            "ValorTotal",
            "ValorContable",
            "FormaPago",
            "Cruce",
            "DocumentoContable_CP",
            "FechaRegistro",
        ]
    ]
    .sort_values(["Cruce", "FechaDocumento"], ascending=[True, False])
)

print(detalle["Cruce"].value_counts().sort_index().to_string())
con_cp = detalle["DocumentoContable_CP"] != ""
print(f"\nCon documento contable: {con_cp.sum():,}  (${detalle.loc[con_cp, 'ValorTotal'].sum():,.2f})")

# ------------------------------------------------------------------------ csv
detalle.to_csv(SALIDA, index=False, encoding="utf-8-sig")

print(f"\nInforme: {SALIDA}")
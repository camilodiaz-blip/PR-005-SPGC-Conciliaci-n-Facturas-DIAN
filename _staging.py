"""
01 - Staging
============
Lee los archivos originales, los limpia y los guarda como parquet.
No hace ningún cruce: solo deja los datos listos para usar.

Salidas en staging/:
    facturas_dian.parquet   documentos conciliados con la DIAN (todos los tipos), ya filtrados
    libro_contable.parquet  partidas del libro, con fecha y llaves normalizadas
"""

import re
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
ENTRADA = BASE / "data" / "raw"
STAGING = BASE / "data" / "staging"
STAGING.mkdir(parents=True, exist_ok=True)


def norm(texto):
    """Deja solo letras y dígitos en mayúscula: 'FE-123 ' -> 'FE123'."""
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper()) if pd.notna(texto) else ""


# --------------------------------------------------- facturas conciliadas DIAN
(archivo_docs,) = ENTRADA.glob("DocumentosConciliados*.xlsx")
docs = pd.read_excel(archivo_docs)

facturas = docs[docs["ConciliadoDIAN"] == "SI"].copy()

facturas["nit"] = facturas["IdentificacionEmisor"].astype(str).str.strip()
facturas["doc_norm"] = facturas["NumeroDocumento"].map(norm)
facturas["fecha"] = pd.to_datetime(facturas["FechaDocumento"]).dt.normalize()
facturas["valor_int"] = facturas["ValorTotal"].round().astype("int64")
facturas["NombreEmisor"] = facturas["NombreEmisor"].astype(str).str.strip().str.upper()

facturas = facturas[
    [
        "TipoDocumento",
        "NumeroDocumento",
        "doc_norm",
        "fecha",
        "NombreEmisor",
        "nit",
        "ValorTotal",
        "valor_int",
        "FormaPago",
    ]
]

# ------------------------------------------------------------- libro contable
libro = pd.read_parquet(ENTRADA / "caja_menor.parquet")

libro["nit"] = libro["numero_identificacion_tercero"].astype(str).str.strip()
libro["doc_norm"] = libro["documento_tercero"].map(norm)
libro["fecha"] = pd.to_datetime(
    dict(year=libro["anio"], month=libro["mes"], day=libro["dia"]), errors="coerce"
)
libro["valor_int"] = libro["saldo"].round().astype("int64")
libro["descripcion_tercero"] = libro["descripcion_tercero"].astype(str).str.strip().str.upper()

libro = libro[
    [
        "fecha",
        "nit",
        "descripcion_tercero",
        "cuenta_contable",
        "CP",
        "documento_tercero",
        "doc_norm",
        "saldo",
        "valor_int",
        "concepto",
    ]
]

# ---------------------------------------------------------------------- guarda
facturas.to_parquet(STAGING / "facturas_dian.parquet", index=False)
libro.to_parquet(STAGING / "libro_contable.parquet", index=False)

print(f"facturas_dian.parquet  : {len(facturas):>8,} facturas")
print(f"libro_contable.parquet : {len(libro):>8,} partidas")
print(f"Guardado en {STAGING}")
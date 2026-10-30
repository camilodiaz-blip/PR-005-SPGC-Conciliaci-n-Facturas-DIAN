"""
Lectura de reembolsos de caja menor
===================================
Lee los archivos de data/raw/caja_menor (Excel .xls/.xlsx y PDF), toma la tabla del
formato "REEMBOLSO DE CAJA MENOR" y guarda una fila por factura, con el NIT y el
número de factura normalizados igual que en DIAN (data/staging/dian.parquet).

Los archivos ya leídos quedan en el control y no se vuelven a leer. Si un archivo
cambia (mismo nombre, contenido distinto) o quedó con error, se vuelve a leer.

Salidas en data/staging/:
    caja_menor_reembolsos.parquet          una fila por factura
    caja_menor_reembolsos_control.parquet  un registro por archivo leído
"""

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pdfplumber
import xlrd

BASE = Path(__file__).resolve().parent
ENTRADA = BASE / "data" / "raw" / "caja_menor"
STAGING = BASE / "data" / "staging"
SALIDA = STAGING / "caja_menor_reembolsos.parquet"
CONTROL = STAGING / "caja_menor_reembolsos_control.parquet"
DIAN = STAGING / "dian.parquet"

# texto que se escribe antes del número de factura y que no hace parte de él
RUIDO_FACTURA = r"^(FACTURA( ELECTRONICA)?( DE VENTA)?|VENTA|FV NO|NO|N)\b[\s.:°º]*"


# ------------------------------------------------------------------ limpieza
def texto(valor):
    """Celda a texto, sin el '.0' que deja Excel en los números."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return " ".join(str(valor).split())


def norm_nit(valor):
    """'899.999.007-0' -> '899999007' (sin dígito de verificación, como DIAN)."""
    nit = re.split(r"[-_]", texto(valor))[0]
    return re.sub(r"\D", "", nit)


def norm_factura(valor):
    """'. FBOD 7173' -> 'FBOD7173';  'VENTA N: 402B314545' -> '402B314545'."""
    t = texto(valor).upper().strip(" .")
    t = re.sub(RUIDO_FACTURA, "", t)
    return re.sub(r"[^A-Z0-9]", "", t)


def norm_valor(valor):
    """'$ 77.000,00' -> 77000.0  (en Excel el valor ya llega como número)."""
    if isinstance(valor, (int, float)):
        return float(valor)
    t = texto(valor).split(" O")[0].replace("$", "").replace(" ", "")
    t = t.split(",")[0].replace(".", "")
    return float(t) if t.isdigit() else None


def norm_fecha(valor, modo_fecha=0):
    """Fecha serial de Excel o texto ('2-oct-26', '21/10/2026'); NaT si no se entiende."""
    if isinstance(valor, float) and valor > 0:
        return pd.Timestamp(xlrd.xldate_as_datetime(valor, modo_fecha))
    meses = {"ene": "jan", "abr": "apr", "ago": "aug", "dic": "dec"}
    t = texto(valor).lower()
    for es, en in meses.items():
        t = t.replace(es, en)
    return pd.to_datetime(t, dayfirst=True, errors="coerce", format="mixed")


def hash_archivo(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# ------------------------------------------------------------------- lectura
def leer_excel(ruta):
    """Devuelve (filas, numero_reembolso, total_reembolso) de la hoja con el formato."""
    libro = xlrd.open_workbook(ruta)
    for hoja in libro.sheets():
        celdas = [[texto(v) for v in hoja.row_values(r)] for r in range(hoja.nrows)]
        encabezado = next((i for i, f in enumerate(celdas) if "No. DE COMPROBANTE" in f), None)
        if encabezado is None:
            continue

        col = {nombre: celdas[encabezado].index(nombre) for nombre in
               ["FECHA", "No. DE COMPROBANTE", "NIT", "BENEFICIARIO", "VALOR TOTAL"]}
        numero = next((next((x for x in f[i + 1:] if x), "") for f in celdas[:encabezado]
                       for i, v in enumerate(f) if v.startswith("REEMBOLSO DE CAJA MENOR")), "")

        filas, total = [], None
        for r in range(encabezado + 1, hoja.nrows):
            fila = hoja.row_values(r)
            if any(texto(v).startswith("TOTAL CAJA MENOR") for v in fila):
                total = next((float(v) for v in fila if isinstance(v, float)), None)
                break
            if not texto(fila[col["NIT"]]) and not texto(fila[col["No. DE COMPROBANTE"]]):
                continue
            filas.append({
                "fecha_factura": norm_fecha(fila[col["FECHA"]], libro.datemode),
                "comprobante": texto(fila[col["No. DE COMPROBANTE"]]),
                "nit_original": texto(fila[col["NIT"]]),
                "beneficiario": texto(fila[col["BENEFICIARIO"]]),
                "total": norm_valor(fila[col["VALOR TOTAL"]]) if texto(fila[col["VALOR TOTAL"]]) else None,
            })
        return filas, numero, total

    raise ValueError("No se encontró la tabla del formato de reembolso")


def leer_pdf(ruta):
    """Devuelve (filas, numero_reembolso, total_reembolso) de la tabla de la página 1."""
    with pdfplumber.open(ruta) as pdf:
        tablas = pdf.pages[0].extract_tables()
    celdas = [[texto(v) for v in fila] for tabla in tablas for fila in tabla]

    encabezado = next((i for i, f in enumerate(celdas) if "No. DE COMPROBANTE" in f), None)
    if encabezado is None:
        raise ValueError("No se encontró la tabla del formato de reembolso en la página 1")
    col = {nombre: celdas[encabezado].index(nombre) for nombre in
           ["FECHA", "No. DE COMPROBANTE", "NIT", "BENEFICIARIO", "TOTAL"]}

    numero, total, filas = "", None, []
    for f in celdas:
        if f and f[0].startswith("REEMBOLSO DE CAJA MENOR"):
            numero = f[-1]
        if f and f[0].startswith("TOTAL CAJA MENOR"):
            total = norm_valor(f[1])

    for f in celdas[encabezado + 1:]:
        if f[0] in ("Responsable:", "Autoriza:") or f[0].startswith("TOTAL CAJA MENOR"):
            break
        if len(f) <= col["TOTAL"] or (not f[col["NIT"]] and not f[col["No. DE COMPROBANTE"]]):
            continue
        filas.append({
            "fecha_factura": norm_fecha(f[col["FECHA"]]),
            "comprobante": f[col["No. DE COMPROBANTE"]],
            "nit_original": f[col["NIT"]],
            "beneficiario": f[col["BENEFICIARIO"]],
            "total": norm_valor(f[col["TOTAL"]]),
        })
    return filas, numero, total


# -------------------------------------------------------- archivos pendientes
control = pd.read_parquet(CONTROL) if CONTROL.exists() else pd.DataFrame(
    columns=["radicado", "archivo", "hash", "fecha_lectura", "numero_reembolso",
             "lineas", "suma_lineas", "total_reembolso", "estado", "detalle"])
datos = pd.read_parquet(SALIDA) if SALIDA.exists() else pd.DataFrame()

leidos = {(a, h) for a, h, e in control[["archivo", "hash", "estado"]].itertuples(index=False)
          if e != "ERROR"}
archivos = sorted(p for p in ENTRADA.iterdir()
                  if p.suffix.lower() in (".xls", ".xlsx", ".pdf") and not p.name.startswith("~$"))
pendientes = [(p, hash_archivo(p)) for p in archivos]
pendientes = [(p, h) for p, h in pendientes if (p.name, h) not in leidos]

print(f"Archivos en carpeta: {len(archivos)} | ya leídos: {len(archivos) - len(pendientes)} "
      f"| por leer: {len(pendientes)}")
if not pendientes:
    raise SystemExit

# facturas DIAN por NIT, para dejar el número igual al de DIAN
facturas_dian = set()
if DIAN.exists():
    dian = pd.read_parquet(DIAN, columns=["NIT Emisor", "Factura"])
    facturas_dian = set(zip(dian["NIT Emisor"].astype(str), dian["Factura"].map(norm_factura)))


def factura_como_dian(nit, numero):
    """Si el número no está en DIAN tal cual, prueba quitando un prefijo digitado de más
    ('FV1212100433377' -> '1212100433377'). Devuelve (numero, encontrado_en_dian)."""
    if (nit, numero) in facturas_dian:
        return numero, True
    for corte in range(1, 4):
        if len(numero) - corte >= 4 and (nit, numero[corte:]) in facturas_dian:
            return numero[corte:], True
    return numero, False


# ------------------------------------------------------------------- proceso
hoy = pd.Timestamp(date.today())
nuevas_filas, nuevos_control = [], []

for ruta, firma in pendientes:
    radicado = ruta.stem
    registro = {"radicado": radicado, "archivo": ruta.name, "hash": firma,
                "fecha_lectura": pd.Timestamp(datetime.now()), "numero_reembolso": "",
                "lineas": 0, "suma_lineas": None, "total_reembolso": None,
                "estado": "ERROR", "detalle": ""}
    try:
        lector = leer_pdf if ruta.suffix.lower() == ".pdf" else leer_excel
        filas, numero, total = lector(ruta)

        for fila in filas:
            nit = norm_nit(fila["nit_original"])
            es_cuenta_cobro = "CUENTA DE COBRO" in fila["comprobante"].upper()
            numero_factura, en_dian = factura_como_dian(nit, norm_factura(fila["comprobante"]))
            nuevas_filas.append({
                "fecha_lectura": hoy,
                "radicado": radicado,
                "nit": nit,
                "numero_factura": numero_factura,
                "total": fila["total"],
                "fecha_factura": fila["fecha_factura"],
                "beneficiario": fila["beneficiario"].upper(),
                "tipo_soporte": "Cuenta de cobro" if es_cuenta_cobro else "Factura",
                "en_dian": en_dian,
                "comprobante_original": fila["comprobante"],
                "nit_original": fila["nit_original"],
                "numero_reembolso": numero,
                "tipo_archivo": ruta.suffix.lower().lstrip("."),
            })

        suma = round(sum(f["total"] or 0 for f in filas), 2)
        cuadra = total is not None and abs(suma - total) < 1
        registro.update(numero_reembolso=numero, lineas=len(filas), suma_lineas=suma,
                        total_reembolso=total, estado="OK" if cuadra else "NO CUADRA",
                        detalle="" if cuadra else f"Suma líneas {suma:,.0f} vs total {total}")
    except Exception as error:
        registro["detalle"] = f"{type(error).__name__}: {error}"

    nuevos_control.append(registro)
    print(f"  {ruta.name:<25} {registro['estado']:<10} {registro['lineas']:>3} líneas  "
          f"{registro['detalle']}")

# ------------------------------------------------------------------- guarda
nuevos = pd.DataFrame(nuevas_filas)
releidos = {r["radicado"] for r in nuevos_control}

# si un archivo se vuelve a leer, sus filas anteriores se reemplazan
if not datos.empty:
    datos = datos[~datos["radicado"].isin(releidos)]
datos = pd.concat([datos, nuevos], ignore_index=True)
control = pd.concat([control[~control["radicado"].isin(releidos)], pd.DataFrame(nuevos_control)],
                    ignore_index=True)

datos.to_parquet(SALIDA, index=False)
control.to_parquet(CONTROL, index=False)

print(f"Caja menor actualizada: {len(nuevos)} líneas nuevas, {len(datos)} en total "
      f"({nuevos['en_dian'].sum() if len(nuevos) else 0} encontradas en DIAN)")

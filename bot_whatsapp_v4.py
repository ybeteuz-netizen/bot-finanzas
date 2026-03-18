from flask import Flask, request
import requests
import sqlite3
from datetime import datetime, timedelta
import re
import threading
import time

app = Flask(__name__)

TOKEN = "EAAXw03hKjCIBQxkUeSGu7qJ1sInz0kjUTndWY52wflNnpCdeapSt2BiO8XUbdq4RK9ruHdZAKDHDxDhFyDvUGNzxm76ZBIJHTdD5iE3Wysc51DIG0P6BgB2higpmbxzN2mx7FWVdbkFKZClYu7uPrgKDDEFxYSZCrQwDxZBt4A0aGF02iQYtXKSF5d1F9HwZDZD"
PHONE_ID = "951141324760103"
VERIFY_TOKEN = "mi_token_seguro_123"
DB_PATH = "finanzas.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            telefono TEXT NOT NULL,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            concepto TEXT NOT NULL,
            monto REAL NOT NULL,
            metodo TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gastos_fijos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telefono TEXT NOT NULL,
            nombre TEXT NOT NULL,
            monto REAL NOT NULL,
            dia INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS presupuestos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telefono TEXT NOT NULL,
            categoria TEXT NOT NULL,
            monto REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_db()


PAYMENT_METHODS = {
    "efectivo": "Efectivo",
    "cash": "Efectivo",
    "bbva": "BBVA",
    "amex": "AMEX",
    "transferencia": "Transferencia",
    "debito": "Debito",
    "credito": "Credito",
    "tarjeta": "Tarjeta",
}


def enviar_mensaje(numero, texto):
    url = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": texto}
    }

    r = requests.post(url, headers=headers, json=data)
    print("Respuesta de Meta:", r.status_code, r.text)


def inferir_categoria(concepto):
    c = concepto.lower()
    reglas = {
        "Transporte": ["uber", "didi", "gasolina", "caseta", "estacionamiento", "taxi", "metro", "camion"],
        "Comida": ["super", "emet", "soriana", "costco", "walmart", "restaurante", "cafeteria", "cafe", "comida", "despensa", "snacks", "mercado", "oxxo"],
        "Salud": ["farmacia", "doctor", "medicina", "hospital", "dentista", "analisis", "laboratorio"],
        "Casa": ["renta", "mantenimiento", "hogar", "limpieza", "mueble", "amazon", "decoracion"],
        "Servicios": ["agua", "luz", "gas", "internet", "telefono", "telmex", "izzi", "cfe", "recarga", "spotify", "netflix"],
        "Ocio": ["cine", "bar", "salida", "viaje", "juego"],
        "Deudas": ["prestamo", "deuda", "mensualidad", "interes"],
        "Mascotas": ["petco", "veterinaria", "croquetas", "mascota"],
        "Ropa": ["zara", "nike", "adidas", "hm", "ropa"],
    }
    for categoria, palabras in reglas.items():
        if any(p in c for p in palabras):
            return categoria
    return "Otros"


def guardar_movimiento(telefono, tipo, categoria, concepto, monto, metodo=""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO movimientos (fecha, telefono, tipo, categoria, concepto, monto, metodo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        telefono,
        tipo,
        categoria,
        concepto,
        float(monto),
        metodo
    ))
    conn.commit()
    movimiento_id = cur.lastrowid
    conn.close()
    return movimiento_id


def obtener_ultimo(telefono):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("""
        SELECT * FROM movimientos
        WHERE telefono = ?
        ORDER BY id DESC
        LIMIT 1
    """, (telefono,)).fetchone()
    conn.close()
    return row


def borrar_ultimo(telefono):
    row = obtener_ultimo(telefono)
    if not row:
        return None

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM movimientos WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return row


def borrar_por_id(telefono, movimiento_id):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("""
        SELECT * FROM movimientos
        WHERE telefono = ? AND id = ?
    """, (telefono, movimiento_id)).fetchone()

    if not row:
        conn.close()
        return None

    cur.execute("DELETE FROM movimientos WHERE id = ?", (movimiento_id,))
    conn.commit()
    conn.close()
    return row


def format_row(row):
    return (
        f"ID: {row['id']}\n"
        f"Tipo: {row['tipo']}\n"
        f"Categoria: {row['categoria']}\n"
        f"Concepto: {row['concepto']}\n"
        f"Monto: ${float(row['monto']):,.2f}\n"
        f"Metodo: {row['metodo'] or '-'}"
    )


def get_range(periodo):
    ahora = datetime.now()

    if periodo == "hoy":
        inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        fin = inicio + timedelta(days=1)

    elif periodo == "semana":
        inicio = (ahora - timedelta(days=ahora.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        fin = inicio + timedelta(days=7)

    elif periodo == "semana_pasada":
        inicio_semana_actual = (ahora - timedelta(days=ahora.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        fin = inicio_semana_actual
        inicio = fin - timedelta(days=7)

    elif periodo == "mes":
        inicio = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if inicio.month == 12:
            fin = inicio.replace(year=inicio.year + 1, month=1)
        else:
            fin = inicio.replace(month=inicio.month + 1)

    elif periodo == "total":
        inicio = None
        fin = None

    else:
        inicio = None
        fin = None

    return inicio, fin


def agregar_fijo(telefono, nombre, monto, dia):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gastos_fijos (telefono, nombre, monto, dia)
        VALUES (?, ?, ?, ?)
    """, (telefono, nombre, monto, dia))
    conn.commit()
    conn.close()


def ver_fijos(telefono):
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT * FROM gastos_fijos
        WHERE telefono = ?
        ORDER BY dia, nombre
    """, (telefono,)).fetchall()
    conn.close()

    if not rows:
        return "No tienes gastos fijos."

    texto = "Gastos fijos\n\n"
    for r in rows:
        texto += f"ID {r['id']} · {r['nombre']} · ${float(r['monto']):,.2f} · dia {r['dia']}\n"

    return texto.strip()


def agregar_presupuesto(telefono, categoria, monto):
    conn = get_conn()
    cur = conn.cursor()

    existente = cur.execute("""
        SELECT id FROM presupuestos
        WHERE telefono = ? AND lower(categoria) = lower(?)
    """, (telefono, categoria)).fetchone()

    if existente:
        cur.execute("""
            UPDATE presupuestos
            SET monto = ?
            WHERE id = ?
        """, (monto, existente["id"]))
    else:
        cur.execute("""
            INSERT INTO presupuestos (telefono, categoria, monto)
            VALUES (?, ?, ?)
        """, (telefono, categoria, monto))

    conn.commit()
    conn.close()


def ver_presupuestos(telefono):
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT * FROM presupuestos
        WHERE telefono = ?
        ORDER BY categoria
    """, (telefono,)).fetchall()
    conn.close()

    if not rows:
        return "No tienes presupuestos."

    texto = "Presupuestos\n\n"
    for r in rows:
        texto += f"{r['categoria']} → ${float(r['monto']):,.2f}\n"

    return texto.strip()


def calcular_fijos_pendientes(telefono):
    conn = get_conn()
    cur = conn.cursor()

    fijos = cur.execute("""
        SELECT * FROM gastos_fijos
        WHERE telefono = ?
    """, (telefono,)).fetchall()

    pendientes = 0

    for f in fijos:
        existe = cur.execute("""
            SELECT 1 FROM movimientos
            WHERE telefono = ?
              AND LOWER(concepto) LIKE LOWER(?)
              AND strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
            LIMIT 1
        """, (telefono, f"%{f['nombre']}%")).fetchone()

        if not existe:
            pendientes += float(f["monto"])

    conn.close()
    return pendientes


def revisar_presupuesto(telefono, categoria):
    conn = get_conn()
    cur = conn.cursor()

    presupuesto = cur.execute("""
        SELECT monto FROM presupuestos
        WHERE telefono = ? AND categoria = ?
    """, (telefono, categoria)).fetchone()

    if not presupuesto:
        conn.close()
        return None

    total = cur.execute("""
        SELECT COALESCE(SUM(monto), 0) as total
        FROM movimientos
        WHERE telefono = ?
          AND categoria = ?
          AND tipo = 'gasto'
          AND strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
    """, (telefono, categoria)).fetchone()["total"]

    conn.close()

    if total > presupuesto["monto"]:
        return (
            f"⚠️ Te pasaste del presupuesto en {categoria}\n"
            f"Gastado: ${float(total):,.2f}\n"
            f"Presupuesto: ${float(presupuesto['monto']):,.2f}"
        )

    return None


def revisar_fijos(telefono):
    hoy = datetime.now().day

    conn = get_conn()
    cur = conn.cursor()

    fijos = cur.execute("""
        SELECT * FROM gastos_fijos
        WHERE telefono = ?
    """, (telefono,)).fetchall()

    alertas = []

    for f in fijos:
        if hoy >= int(f["dia"]):
            existe = cur.execute("""
                SELECT 1 FROM movimientos
                WHERE telefono = ?
                  AND LOWER(concepto) LIKE LOWER(?)
                  AND strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
                LIMIT 1
            """, (telefono, f"%{f['nombre']}%")).fetchone()

            if not existe:
                alertas.append(f"⚠️ No has registrado: {f['nombre']} (dia {f['dia']})")

    conn.close()

    if alertas:
        return "\n".join(alertas)

    return None


def gasto_total_periodo(telefono, periodo):
    conn = get_conn()
    cur = conn.cursor()

    inicio, fin = get_range(periodo)

    if periodo == "total":
        total = cur.execute("""
            SELECT COALESCE(SUM(monto), 0) AS total
            FROM movimientos
            WHERE telefono = ?
              AND tipo = 'gasto'
        """, (telefono,)).fetchone()["total"]
    else:
        total = cur.execute("""
            SELECT COALESCE(SUM(monto), 0) AS total
            FROM movimientos
            WHERE telefono = ?
              AND tipo = 'gasto'
              AND fecha >= ?
              AND fecha < ?
        """, (telefono, inicio.isoformat(), fin.isoformat())).fetchone()["total"]

    conn.close()
    return float(total)


def promedio_diario_mes(telefono):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT substr(fecha, 1, 10) AS dia, SUM(monto) AS total
        FROM movimientos
        WHERE telefono = ?
          AND tipo = 'gasto'
          AND strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
        GROUP BY substr(fecha, 1, 10)
    """, (telefono,)).fetchall()

    conn.close()

    if not rows:
        return 0.0

    suma = sum(float(r["total"]) for r in rows)
    dias = len(rows)
    return suma / dias if dias else 0.0


def gasto_hoy(telefono):
    return gasto_total_periodo(telefono, "hoy")


def comparar_semana(telefono):
    actual = gasto_total_periodo(telefono, "semana")
    pasada = gasto_total_periodo(telefono, "semana_pasada")

    if pasada == 0 and actual == 0:
        return None

    if pasada == 0 and actual > 0:
        return f"📈 Esta semana llevas ${actual:,.2f} en gastos. No hay referencia de la semana pasada."

    diferencia = actual - pasada
    porcentaje = (diferencia / pasada) * 100 if pasada else 0

    if diferencia > 0:
        return f"📈 Esta semana gastaste ${abs(diferencia):,.2f} más que la semana pasada ({porcentaje:,.1f}% arriba)."
    elif diferencia < 0:
        return f"📉 Esta semana gastaste ${abs(diferencia):,.2f} menos que la semana pasada ({abs(porcentaje):,.1f}% abajo)."

    return "📊 Esta semana vas igual que la pasada."


def patrones_inteligentes(telefono):
    mensajes = []

    hoy_total = gasto_hoy(telefono)
    promedio = promedio_diario_mes(telefono)

    if promedio > 0 and hoy_total > promedio * 1.5:
        mensajes.append(
            f"⚠️ Hoy llevas ${hoy_total:,.2f} en gastos, arriba de tu promedio diario del mes (${promedio:,.2f})."
        )

    comparacion_semana = comparar_semana(telefono)
    if comparacion_semana:
        mensajes.append(comparacion_semana)

    return "\n".join(mensajes) if mensajes else None


def recordatorio_hoy(telefono):
    conn = get_conn()
    cur = conn.cursor()

    hoy = datetime.now().strftime("%Y-%m-%d")
    row = cur.execute("""
        SELECT 1
        FROM movimientos
        WHERE telefono = ?
          AND tipo = 'gasto'
          AND substr(fecha, 1, 10) = ?
        LIMIT 1
    """, (telefono, hoy)).fetchone()

    conn.close()

    hora = datetime.now().hour

    if not row and hora >= 21:
        return "⏰ Hoy todavía no has registrado gastos."
    return None


def resumen_periodo(telefono, periodo):
    conn = get_conn()
    cur = conn.cursor()

    inicio, fin = get_range(periodo)

    if periodo == "total":
        rows = cur.execute("""
            SELECT tipo, COALESCE(SUM(monto), 0) AS total
            FROM movimientos
            WHERE telefono = ?
              AND tipo IN ('ingreso', 'gasto')
            GROUP BY tipo
        """, (telefono,)).fetchall()

        top = cur.execute("""
            SELECT categoria, SUM(monto) AS total
            FROM movimientos
            WHERE telefono = ?
              AND tipo = 'gasto'
            GROUP BY categoria
            ORDER BY total DESC
            LIMIT 5
        """, (telefono,)).fetchall()

    else:
        rows = cur.execute("""
            SELECT tipo, COALESCE(SUM(monto), 0) AS total
            FROM movimientos
            WHERE telefono = ?
              AND tipo IN ('ingreso', 'gasto')
              AND fecha >= ?
              AND fecha < ?
            GROUP BY tipo
        """, (telefono, inicio.isoformat(), fin.isoformat())).fetchall()

        top = cur.execute("""
            SELECT categoria, SUM(monto) AS total
            FROM movimientos
            WHERE telefono = ?
              AND tipo = 'gasto'
              AND fecha >= ?
              AND fecha < ?
            GROUP BY categoria
            ORDER BY total DESC
            LIMIT 5
        """, (telefono, inicio.isoformat(), fin.isoformat())).fetchall()

    conn.close()

    ingresos = 0
    gastos = 0

    for row in rows:
        if row["tipo"] == "ingreso":
            ingresos = float(row["total"])
        elif row["tipo"] == "gasto":
            gastos = float(row["total"])

    disponible_actual = ingresos - gastos
    pendientes = calcular_fijos_pendientes(telefono)
    ahorro_real = disponible_actual - pendientes

    titulo = {
        "hoy": "Resumen de hoy",
        "semana": "Resumen de la semana",
        "mes": "Resumen del mes",
        "total": "Resumen total",
    }[periodo]

    texto = (
        f"{titulo}\n\n"
        f"Ingresos: ${ingresos:,.2f}\n"
        f"Gastos registrados: ${gastos:,.2f}\n"
        f"Disponible actual: ${disponible_actual:,.2f}\n"
        f"Gastos fijos pendientes: ${pendientes:,.2f}\n"
        f"Ahorro real estimado: ${ahorro_real:,.2f}"
    )

    if top:
        texto += "\n\nTop gastos:"
        for row in top:
            texto += f"\n- {row['categoria']}: ${float(row['total']):,.2f}"

    alertas_fijos = revisar_fijos(telefono)
    if alertas_fijos:
        texto += f"\n\n{alertas_fijos}"

    patrones = patrones_inteligentes(telefono)
    if patrones and periodo in ["hoy", "semana", "mes", "total"]:
        texto += f"\n\n{patrones}"

    recordatorio = recordatorio_hoy(telefono)
    if recordatorio and periodo in ["hoy", "semana", "mes", "total"]:
        texto += f"\n\n{recordatorio}"

    return texto


def balance_actual(telefono):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT tipo, COALESCE(SUM(monto), 0) AS total
        FROM movimientos
        WHERE telefono = ?
          AND tipo IN ('ingreso', 'gasto')
        GROUP BY tipo
    """, (telefono,)).fetchall()

    conn.close()

    ingresos = 0
    gastos = 0

    for row in rows:
        if row["tipo"] == "ingreso":
            ingresos = float(row["total"])
        elif row["tipo"] == "gasto":
            gastos = float(row["total"])

    disponible_actual = ingresos - gastos
    pendientes = calcular_fijos_pendientes(telefono)
    ahorro_real = disponible_actual - pendientes

    texto = (
        "Balance actual\n\n"
        f"Ingresos: ${ingresos:,.2f}\n"
        f"Gastos registrados: ${gastos:,.2f}\n"
        f"Disponible actual: ${disponible_actual:,.2f}\n"
        f"Gastos fijos pendientes: ${pendientes:,.2f}\n"
        f"Ahorro real estimado: ${ahorro_real:,.2f}"
    )

    alertas_fijos = revisar_fijos(telefono)
    if alertas_fijos:
        texto += f"\n\n{alertas_fijos}"

    patrones = patrones_inteligentes(telefono)
    if patrones:
        texto += f"\n\n{patrones}"

    recordatorio = recordatorio_hoy(telefono)
    if recordatorio:
        texto += f"\n\n{recordatorio}"

    return texto


def extraer_monto(tokens):
    for t in tokens:
        limpio = t.replace("$", "").replace(",", "")
        try:
            return float(limpio)
        except ValueError:
            pass
    return None


def extraer_metodo(tokens):
    for t in tokens:
        if t.lower() in PAYMENT_METHODS:
            return PAYMENT_METHODS[t.lower()]
    return ""


def limpiar_tokens(tokens):
    resultado = []
    for t in tokens:
        limpio = t.lower().replace("$", "").replace(",", "")
        if limpio in PAYMENT_METHODS:
            continue
        try:
            float(limpio)
            continue
        except ValueError:
            pass
        resultado.append(t)
    return resultado


def parse_movimiento(texto):
    texto = texto.strip().lower()
    tokens = texto.split()

    if not tokens:
        return None

    m = re.match(r"^borrar\s+(\d+)$", texto)
    if m:
        return {"accion": "borrar_id", "id": int(m.group(1))}

    if texto == "borrar ultimo":
        return {"accion": "borrar_ultimo"}

    if texto == "ultimo":
        return {"accion": "ultimo"}

    if texto == "balance":
        return {"accion": "balance"}

    if texto == "resumen hoy":
        return {"accion": "resumen_hoy"}

    if texto == "resumen semana":
        return {"accion": "resumen_semana"}

    if texto == "resumen mes":
        return {"accion": "resumen_mes"}

    if texto == "resumen total":
        return {"accion": "resumen_total"}

    m = re.match(r"^fijo\s+(.+)\s+(\d+(?:\.\d+)?)\s+dia\s+(\d+)$", texto)
    if m:
        return {
            "accion": "agregar_fijo",
            "nombre": m.group(1).title(),
            "monto": float(m.group(2)),
            "dia": int(m.group(3))
        }

    if texto == "ver fijos":
        return {"accion": "ver_fijos"}

    m = re.match(r"^presupuesto\s+(.+)\s+(\d+(?:\.\d+)?)$", texto)
    if m:
        return {
            "accion": "agregar_presupuesto",
            "categoria": m.group(1).title(),
            "monto": float(m.group(2))
        }

    if texto == "ver presupuestos":
        return {"accion": "ver_presupuestos"}

    if texto in ["hola", "menu", "menú", "ayuda"]:
        return {"accion": "ayuda"}

    if "ahorro" in tokens:
        return {"accion": "ahorro_auto"}

    if "ingreso" in tokens:
        monto = extraer_monto(tokens)
        metodo = extraer_metodo(tokens)
        conceptos = [t for t in limpiar_tokens(tokens) if t != "ingreso"]
        concepto = " ".join(conceptos).strip().title() or "Ingreso"
        if monto is not None:
            return {
                "accion": "guardar",
                "tipo": "ingreso",
                "categoria": "Ingreso",
                "concepto": concepto,
                "monto": monto,
                "metodo": metodo
            }

    monto = extraer_monto(tokens)
    if monto is not None:
        metodo = extraer_metodo(tokens)
        conceptos = limpiar_tokens(tokens)
        concepto = " ".join(conceptos).strip().title() or "Gasto"
        categoria = inferir_categoria(concepto)
        return {
            "accion": "guardar",
            "tipo": "gasto",
            "categoria": categoria,
            "concepto": concepto,
            "monto": monto,
            "metodo": metodo
        }

    return {"accion": "no_entendido"}


def procesar_texto(telefono, texto):
    data = parse_movimiento(texto)

    if data["accion"] == "ayuda":
        return (
            "Control financiero listo ✅\n\n"
            "Prueba asi:\n"
            "- uber 500\n"
            "- 500 uber\n"
            "- amex uber 500\n"
            "- ingreso 70000 sueldo\n"
            "- 70000 ingreso sueldo\n"
            "- balance\n"
            "- resumen hoy\n"
            "- resumen semana\n"
            "- resumen mes\n"
            "- resumen total\n"
            "- ultimo\n"
            "- borrar ultimo\n"
            "- borrar 15\n"
            "- fijo renta 12000 dia 5\n"
            "- ver fijos\n"
            "- presupuesto comida 8000\n"
            "- ver presupuestos"
        )

    if data["accion"] == "guardar":
    guardar_movimiento(
        telefono,
        data["tipo"],
        data["categoria"],
        data["concepto"],
        data["monto"],
        data["metodo"]
    )

    mensaje = (
        f"{data['tipo'].capitalize()} registrado ✅\n"
        f"{data['categoria']} · {data['concepto']}\n"
        f"${data['monto']:,.2f}\n"
        f"Metodo: {data['metodo'] or '-'}"
    )

                alerta_presupuesto = revisar_presupuesto(telefono, data["categoria"])
        if alerta_presupuesto:
            mensaje += f"\n\n{alerta_presupuesto}"

        alerta_fijos = revisar_fijos(telefono)
        if alerta_fijos:
            mensaje += f"\n\n{alerta_fijos}"

        return mensaje

    if data["accion"] == "ultimo":
        row = obtener_ultimo(telefono)
        if not row:
            return "Todavia no hay movimientos."
        return "Ultimo movimiento\n\n" + format_row(row)

    if data["accion"] == "borrar_ultimo":
        row = borrar_ultimo(telefono)
        if not row:
            return "No hay movimientos para borrar."
        return "Ultimo movimiento borrado ✅\n\n" + format_row(row)

    if data["accion"] == "borrar_id":
        row = borrar_por_id(telefono, data["id"])
        if not row:
            return f"No encontre el movimiento con ID {data['id']}."
        return "Movimiento borrado ✅\n\n" + format_row(row)

    if data["accion"] == "balance":
        return balance_actual(telefono)

    if data["accion"] == "resumen_hoy":
        return resumen_periodo(telefono, "hoy")

    if data["accion"] == "resumen_semana":
        return resumen_periodo(telefono, "semana")

    if data["accion"] == "resumen_mes":
        return resumen_periodo(telefono, "mes")

    if data["accion"] == "resumen_total":
        return resumen_periodo(telefono, "total")

    if data["accion"] == "agregar_fijo":
        agregar_fijo(telefono, data["nombre"], data["monto"], data["dia"])
        return f"Gasto fijo agregado ✅\n{data['nombre']} · ${data['monto']:,.2f} · dia {data['dia']}"

    if data["accion"] == "ver_fijos":
        return ver_fijos(telefono)

    if data["accion"] == "agregar_presupuesto":
        agregar_presupuesto(telefono, data["categoria"], data["monto"])
        return f"Presupuesto agregado ✅\n{data['categoria']} → ${data['monto']:,.2f}"

    if data["accion"] == "ver_presupuestos":
        return ver_presupuestos(telefono)

    if data["accion"] == "ahorro_auto":
        return (
            "El ahorro ya no se registra manualmente ✅\n"
            "Ahora se calcula automaticamente como:\n"
            "Disponible actual - gastos fijos pendientes"
        )

    return (
        "No entendi ese mensaje.\n\n"
        "Ejemplos:\n"
        "- uber 500\n"
        "- 500 uber\n"
        "- ingreso 70000 sueldo\n"
        "- balance\n"
        "- resumen hoy\n"
        "- resumen semana\n"
        "- resumen mes\n"
        "- resumen total"
    )


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if token == VERIFY_TOKEN:
            return challenge, 200
        return "Token invalido", 403

    if request.method == "POST":
        data = request.json
        print("POST recibido:", data)

        try:
            cambio = data["entry"][0]["changes"][0]["value"]

            if "messages" in cambio:
                mensaje = cambio["messages"][0]
                texto = mensaje["text"]["body"]
                numero = cambio["contacts"][0]["wa_id"]

                respuesta = procesar_texto(numero, texto)
                enviar_mensaje(numero, respuesta)
            else:
                print("Evento sin mensaje, ignorado.")

        except Exception as e:
            print("Error procesando mensaje:", e)

        return "ok", 200

def recordatorio_diario_loop():
    ultima_fecha_enviada = None

    while True:
        ahora = datetime.now()
        hoy = ahora.strftime("%Y-%m-%d")

        if ahora.hour == 21 and ultima_fecha_enviada != hoy:
            print("⏰ Ejecutando recordatorio diario...", flush=True)

            conn = get_conn()
            cur = conn.cursor()

            telefonos = cur.execute("""
                SELECT DISTINCT telefono FROM movimientos
            """).fetchall()

            conn.close()

            for t in telefonos:
                telefono = t["telefono"]
                alerta = recordatorio_hoy(telefono)

                if alerta:
                    print(f"📨 Enviando recordatorio a {telefono}: {alerta}", flush=True)
                    enviar_mensaje(telefono, alerta)

            ultima_fecha_enviada = hoy

        time.sleep(30)


if __name__ == "__main__":
    print("🔥 Arrancando bot_whatsapp_v4.py", flush=True)

    hilo = threading.Thread(target=recordatorio_diario_loop)
    hilo.daemon = True
    hilo.start()

    print("✅ Hilo lanzado, arrancando Flask...", flush=True)
    app.run(host="0.0.0.0", port=5050, debug=False)

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = "finanzas_bot.db"
TZ = ZoneInfo("America/Mexico_City")

USERS = {
    "+525584290304": "Yosef",
    "+525624679160": "Rajel",
}

PAYMENT_METHODS = {
    "efectivo": "Efectivo",
    "cash": "Efectivo",
    "bbva": "BBVA",
    "amex": "AMEX",
    "transferencia": "Transferencia",
    "debito": "Débito",
    "credito": "Crédito",
    "otro": "Otro",
}

CATEGORY_RULES = {
    "Transporte": {"uber", "didi", "gasolina", "caseta", "estacionamiento", "metro", "camion", "taxi", "diesel", "casetas"},
    "Comida": {"super", "emet", "soriana", "costco", "walmart", "restaurante", "cafeteria", "cafe", "comida", "despensa", "snacks", "mercado", "oxxo"},
    "Salud": {"farmacia", "doctor", "medicina", "hospital", "consulta", "dentista", "analisis", "laboratorio"},
    "Casa": {"renta", "mantenimiento", "mueble", "limpieza", "hogar", "amazon", "decoracion"},
    "Servicios": {"luz", "agua", "gas", "internet", "telefono", "telmex", "izzi", "cfe", "recarga"},
    "Deudas": {"prestamo", "deuda", "tarjeta", "interes", "mensualidad", "pago"},
    "Ocio": {"cine", "netflix", "spotify", "salida", "bar", "viaje", "juego", "regalo"},
    "Ahorro": {"ahorro"},
    "Ingreso": {"sueldo", "nomina", "pago", "deposito", "reembolso", "venta", "ingreso", "regalo"},
}

HELP_TEXT = (
    "Comandos disponibles:\n"
    "- gasto [concepto] [monto] [metodo]\n"
    "- ingreso [concepto] [monto] [metodo]\n"
    "- ahorro [monto] [metodo]\n"
    "- [concepto] [monto] [metodo opcional]  -> lo toma como gasto\n"
    "- +[monto] [concepto opcional] [metodo opcional]  -> ingreso rapido\n"
    "- -[monto] [concepto opcional] [metodo opcional]  -> gasto rapido\n"
    "- balance\n"
    "- resumen hoy\n"
    "- resumen semana\n"
    "- resumen mes\n"
    "- gastos [categoria]\n"
    "- ultimo\n"
    "- borrar ultimo\n"
    "\nEjemplos:\n"
    "gasto uber 180 amex\n"
    "super 1250 bbva\n"
    "+3000 regalo transferencia\n"
    "-180 uber amex\n"
    "ahorro 500 bbva"
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            user_phone TEXT NOT NULL,
            user_name TEXT NOT NULL,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            concepto TEXT NOT NULL,
            monto REAL NOT NULL,
            metodo_pago TEXT NOT NULL,
            notas TEXT DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def now_local() -> datetime:
    return datetime.now(TZ)


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def titleish(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())


def extract_amount(tokens: List[str]) -> Optional[float]:
    for token in reversed(tokens):
        clean = token.replace("$", "").replace(",", "")
        if clean.startswith("+") or clean.startswith("-"):
            clean = clean[1:]
        try:
            return float(clean)
        except ValueError:
            continue
    return None


def extract_payment_method(tokens: List[str]) -> str:
    for token in reversed(tokens):
        if token in PAYMENT_METHODS:
            return PAYMENT_METHODS[token]
    return "Otro"


def is_amount_token(token: str) -> bool:
    clean = token.replace("$", "").replace(",", "")
    if clean.startswith("+") or clean.startswith("-"):
        clean = clean[1:]
    try:
        float(clean)
        return True
    except ValueError:
        return False


def infer_category(concepto: str, tipo: str = "gasto") -> str:
    words = set(concepto.split())
    if tipo == "ingreso":
        return "Ingreso"
    if tipo == "ahorro":
        return "Ahorro"
    for category, keywords in CATEGORY_RULES.items():
        if category == "Ingreso":
            continue
        if words & keywords:
            return category
    return "Otros"


def parse_quick_signed_message(text: str) -> Optional[Dict[str, Any]]:
    tokens = text.split()
    if not tokens:
        return None

    first = tokens[0]
    if not re.match(r"^[+-]\d+(\.\d+)?$", first.replace(",", "")):
        return None

    sign = first[0]
    amount = float(first[1:].replace(",", ""))
    tipo = "ingreso" if sign == "+" else "gasto"

    remaining = tokens[1:]
    metodo = extract_payment_method(remaining)
    filtered = [t for t in remaining if t not in PAYMENT_METHODS]
    concepto = " ".join(filtered).strip()

    if not concepto:
        concepto = "Ingreso rapido" if tipo == "ingreso" else "Gasto rapido"

    categoria = infer_category(concepto.lower(), tipo)
    return {
        "tipo": tipo,
        "concepto": titleish(concepto),
        "categoria": categoria,
        "monto": amount,
        "metodo_pago": metodo,
    }


def parse_movement_message(text: str) -> Optional[Dict[str, Any]]:
    text = normalize_text(text)
    tokens = text.split()
    if not tokens:
        return None

    quick_signed = parse_quick_signed_message(text)
    if quick_signed:
        return quick_signed

    first = tokens[0]
    if first not in {"gasto", "ingreso", "ahorro"}:
        return None

    if first == "ahorro":
        amount = extract_amount(tokens)
        metodo = extract_payment_method(tokens)
        filtered = [t for t in tokens[1:] if not is_amount_token(t) and t not in PAYMENT_METHODS]
        concepto = " ".join(filtered).strip() or "Ahorro"
        if amount is None:
            return None
        return {
            "tipo": "ahorro",
            "concepto": titleish(concepto),
            "categoria": "Ahorro",
            "monto": amount,
            "metodo_pago": metodo,
        }

    amount = extract_amount(tokens)
    metodo = extract_payment_method(tokens)
    if amount is None:
        return None

    filtered = []
    amount_consumed = False
    method_consumed = False
    for token in tokens[1:]:
        if not amount_consumed and is_amount_token(token):
            amount_consumed = True
            continue
        if not method_consumed and token in PAYMENT_METHODS:
            method_consumed = True
            continue
        filtered.append(token)

    if not filtered:
        concepto = "Ingreso" if first == "ingreso" else "Gasto"
    else:
        concepto = " ".join(filtered)

    categoria = infer_category(concepto, first)

    return {
        "tipo": first,
        "concepto": titleish(concepto),
        "categoria": categoria,
        "monto": amount,
        "metodo_pago": metodo,
    }


def parse_short_expense_message(text: str) -> Optional[str]:
    if text.startswith(("gasto", "ingreso", "ahorro", "+", "-")):
        return None
    if text in {"balance", "resumen hoy", "resumen semana", "resumen mes", "ultimo", "borrar ultimo", "ayuda", "help", "menu"}:
        return None
    if text.startswith("gastos "):
        return None
    if re.match(r"^[a-záéíóúñ]+(\s+[a-záéíóúñ]+){0,4}\s+\d+(\.\d+)?(\s+\w+)?$", text):
        return "gasto " + text
    return None


def save_movement(phone: str, parsed: Dict[str, Any]) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO movimientos (created_at, user_phone, user_name, tipo, categoria, concepto, monto, metodo_pago)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_local().isoformat(),
            phone,
            USERS.get(phone, "Usuario"),
            parsed["tipo"],
            parsed["categoria"],
            parsed["concepto"],
            parsed["monto"],
            parsed["metodo_pago"],
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return int(new_id)


def get_last_movement(phone: Optional[str] = None) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    if phone:
        row = cur.execute(
            """
            SELECT * FROM movimientos
            WHERE user_phone = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (phone,),
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT * FROM movimientos ORDER BY id DESC LIMIT 1"
        ).fetchone()
    conn.close()
    return row


def delete_last_movement(phone: str) -> Optional[sqlite3.Row]:
    row = get_last_movement(phone)
    if not row:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM movimientos WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return row


def _range_clause(period: str) -> Tuple[str, str]:
    now = now_local()
    if period == "hoy":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "semana":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
    elif period == "mes":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    else:
        raise ValueError("Periodo invalido")
    return start.isoformat(), end.isoformat()


def totals_for_period(period: str) -> Dict[str, float]:
    start, end = _range_clause(period)
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT tipo, COALESCE(SUM(monto), 0) as total
        FROM movimientos
        WHERE created_at >= ? AND created_at < ?
        GROUP BY tipo
        """,
        (start, end),
    ).fetchall()
    conn.close()

    totals = {"ingreso": 0.0, "gasto": 0.0, "ahorro": 0.0}
    for row in rows:
        totals[row["tipo"]] = float(row["total"])
    return totals


def category_breakdown(period: str, limit: int = 5) -> List[sqlite3.Row]:
    start, end = _range_clause(period)
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT categoria, SUM(monto) AS total
        FROM movimientos
        WHERE tipo = 'gasto' AND created_at >= ? AND created_at < ?
        GROUP BY categoria
        ORDER BY total DESC
        LIMIT ?
        """,
        (start, end, limit),
    ).fetchall()
    conn.close()
    return rows


def gastos_por_categoria(category: str) -> str:
    start, end = _range_clause("mes")
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT concepto, SUM(monto) AS total
        FROM movimientos
        WHERE tipo = 'gasto' AND lower(categoria) = lower(?)
          AND created_at >= ? AND created_at < ?
        GROUP BY concepto
        ORDER BY total DESC
        """,
        (category, start, end),
    ).fetchall()
    conn.close()

    if not rows:
        return f"No veo gastos en la categoria {category.title()} este mes."

    total = sum(float(r["total"]) for r in rows)
    lines = [f"Gastos de {category.title()} este mes", ""]
    for row in rows:
        lines.append(f"- {row['concepto']}: ${row['total']:,.2f}")
    lines.append("")
    lines.append(f"Total: ${total:,.2f}")
    return "\n".join(lines)


def format_balance() -> str:
    totals = totals_for_period("mes")
    disponible = totals["ingreso"] - totals["gasto"] - totals["ahorro"]
    return (
        "Balance al momento\n\n"
        f"Ingresos: ${totals['ingreso']:,.2f}\n"
        f"Gastos: ${totals['gasto']:,.2f}\n"
        f"Ahorro: ${totals['ahorro']:,.2f}\n"
        f"Disponible neto: ${disponible:,.2f}"
    )


def format_summary(period: str) -> str:
    totals = totals_for_period(period)
    disponible = totals["ingreso"] - totals["gasto"] - totals["ahorro"]
    title = {
        "hoy": "Resumen de hoy",
        "semana": "Resumen semanal",
        "mes": "Resumen mensual",
    }[period]
    lines = [
        title,
        "",
        f"Ingresos: ${totals['ingreso']:,.2f}",
        f"Gastos: ${totals['gasto']:,.2f}",
        f"Ahorro: ${totals['ahorro']:,.2f}",
        f"Disponible neto: ${disponible:,.2f}",
    ]

    breakdown = category_breakdown(period)
    if breakdown:
        lines.extend(["", "Top gastos:"])
        for row in breakdown:
            lines.append(f"- {row['categoria']}: ${row['total']:,.2f}")

    return "\n".join(lines)


def format_last_movement(row: sqlite3.Row) -> str:
    return (
        "Ultimo movimiento\n\n"
        f"ID: {row['id']}\n"
        f"Tipo: {titleish(row['tipo'])}\n"
        f"Categoria: {row['categoria']}\n"
        f"Concepto: {row['concepto']}\n"
        f"Monto: ${float(row['monto']):,.2f}\n"
        f"Metodo: {row['metodo_pago']}\n"
        f"Usuario: {row['user_name']}"
    )


def process_message(phone: str, incoming_text: str) -> str:
    text = normalize_text(incoming_text)

    if text in {"ayuda", "help", "menu"}:
        return HELP_TEXT

    short_version = parse_short_expense_message(text)
    if short_version:
        text = short_version

    parsed = parse_movement_message(text)
    if parsed:
        save_movement(phone, parsed)
        tipo_label = titleish(parsed["tipo"])
        return (
            "Registrado\n"
            f"{tipo_label} · {parsed['categoria']} · {parsed['concepto']}\n"
            f"Monto: ${parsed['monto']:,.2f}\n"
            f"Metodo: {parsed['metodo_pago']}\n"
            f"Usuario: {USERS.get(phone, 'Usuario')}"
        )

    if text == "balance":
        return format_balance()
    if text == "resumen hoy":
        return format_summary("hoy")
    if text == "resumen semana":
        return format_summary("semana")
    if text == "resumen mes":
        return format_summary("mes")
    if text.startswith("gastos "):
        category = incoming_text.split(" ", 1)[1].strip()
        return gastos_por_categoria(category)
    if text == "ultimo":
        row = get_last_movement(phone)
        if not row:
            return "Todavia no hay movimientos registrados."
        return format_last_movement(row)
    if text == "borrar ultimo":
        row = delete_last_movement(phone)
        if not row:
            return "No hay movimientos para borrar."
        return (
            "Ultimo movimiento borrado\n\n"
            f"{titleish(row['tipo'])} · {row['categoria']} · {row['concepto']}\n"
            f"Monto: ${float(row['monto']):,.2f}\n"
            f"Metodo: {row['metodo_pago']}"
        )

    return "No entendi ese mensaje. Escribe 'ayuda' para ver comandos."


if __name__ == "__main__":
    print("Bot financiero listo. Escribe 'salir' para terminar.\n")
    test_phone = "+5215584290304"
    while True:
        msg = input("Tu: ").strip()
        if msg.lower() == "salir":
            break
        print("Bot:", process_message(test_phone, msg))
        print()

"""Reglas de negocio: stock derivado, semáforo, FEFO y registro de movimientos.

Todas las escrituras de inventario pasan por registrar_movimiento(); las vistas
HTML y la API solo llaman aquí — una sola fuente de reglas.
"""
from datetime import date, datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Causa, Configuracion, Lote, Movimiento, Producto, Usuario

MINUTOS_INACTIVIDAD_DEFECTO = 15

# Valores iniciales de configuración; main.py los siembra si faltan (también
# al actualizar una BD de producción existente).
CONFIG_DEFECTOS = {
    "minutos_inactividad": str(MINUTOS_INACTIVIDAD_DEFECTO),
}


def _config(clave: str, session: Session | None = None) -> str | None:
    propia = session is None
    if propia:
        session = SessionLocal()
    try:
        fila = session.query(Configuracion).filter_by(clave=clave).first()
        return fila.valor if fila else None
    finally:
        if propia:
            session.close()


def minutos_inactividad(session: Session | None = None) -> float:
    """Minutos de inactividad antes del cierre de sesión automático (config admin)."""
    try:
        return float(_config("minutos_inactividad", session) or MINUTOS_INACTIVIDAD_DEFECTO)
    except ValueError:
        return MINUTOS_INACTIVIDAD_DEFECTO

# Umbrales confirmados por el doctor (Q1). Único lugar donde viven.
SEMAFORO = (
    (385, None, "VERDE"),
    (365, 384, "PRONTO_A_AMARILLO"),
    (200, 364, "AMARILLA"),
    (182, 199, "PRONTO_A_ROJO"),
    (31, 181, "ROJO"),
    (0, 30, "VENCE_EN_1_MES"),
)
ETIQUETAS_SEMAFORO = {
    "VERDE": "Verde", "PRONTO_A_AMARILLO": "Pronto cambia a amarillo",
    "AMARILLA": "Amarilla", "PRONTO_A_ROJO": "Pronto cambia a rojo",
    "ROJO": "Rojo", "VENCE_EN_1_MES": "Vence en 1 mes", "CADUCO": "Caduco",
}


class MovimientoInvalido(Exception):
    """Regla de negocio violada; el mensaje es apto para mostrarse al usuario."""


def texto_excel(valor) -> str:
    """Texto seguro para celdas de Excel: openpyxl convierte en FÓRMULA VIVA
    cualquier string que empiece con '='. Texto libre (paciente, detalle, nombres
    creados por usuarios) podría inyectar fórmulas al abrir el export (OWASP:
    CSV/Formula injection). El apóstrofo inicial fuerza texto plano en Excel."""
    s = str(valor) if valor is not None else ""
    return "'" + s if s.startswith("=") else s


def semaforo(fecha_caducidad: date, hoy: date | None = None) -> str:
    dias = (fecha_caducidad - (hoy or date.today())).days
    if dias < 0:
        return "CADUCO"
    for minimo, maximo, categoria in SEMAFORO:
        if dias >= minimo and (maximo is None or dias <= maximo):
            return categoria
    return "CADUCO"  # inalcanzable, pero explícito


def _delta_piezas():
    return case(
        (Movimiento.tipo == "ENTRADA", Movimiento.piezas),
        (Movimiento.tipo.in_(("SALIDA", "BAJA_CADUCIDAD")), -Movimiento.piezas),
        (Movimiento.tipo == "AJUSTE", Movimiento.piezas),  # con signo
        else_=0,
    )


def stock_piezas(session: Session, producto_id: int) -> int:
    delta = session.query(func.coalesce(func.sum(_delta_piezas()), 0)).filter(
        Movimiento.producto_id == producto_id,
        Movimiento.historico.is_(False),
    ).scalar()
    base = session.query(Producto.stock_base).filter_by(id=producto_id).scalar()
    return int(base) + int(delta)


def stock_piezas_todos(session: Session) -> dict[int, int]:
    """Stock de todos los productos en 2 queries (para la vista de inventario)."""
    deltas = dict(
        session.query(Movimiento.producto_id, func.sum(_delta_piezas()))
        .filter(Movimiento.historico.is_(False))
        .group_by(Movimiento.producto_id)
    )
    return {
        pid: int(base) + int(deltas.get(pid, 0))
        for pid, base in session.query(Producto.id, Producto.stock_base)
    }


def stock_en_fecha_todos(session: Session, corte: datetime) -> dict[int, int]:
    """Stock de cada producto al instante `corte` (inclusive).

    La línea base (stock_base) es la foto del Excel al migrar. Hacia atrás en el
    tiempo se RESTAN los movimientos históricos posteriores al corte; hacia
    adelante se SUMAN los movimientos nuevos hasta el corte. Así el reporte
    funciona tanto para meses del historial migrado como para meses nuevos.
    """
    hist_despues = dict(
        session.query(Movimiento.producto_id, func.sum(_delta_piezas()))
        .filter(Movimiento.historico.is_(True), Movimiento.fecha_hora > corte)
        .group_by(Movimiento.producto_id)
    )
    nuevos_hasta = dict(
        session.query(Movimiento.producto_id, func.sum(_delta_piezas()))
        .filter(Movimiento.historico.is_(False), Movimiento.fecha_hora <= corte)
        .group_by(Movimiento.producto_id)
    )
    return {
        pid: int(base) - int(hist_despues.get(pid, 0)) + int(nuevos_hasta.get(pid, 0))
        for pid, base in session.query(Producto.id, Producto.stock_base)
    }


def sumas_periodo(session: Session, desde: datetime, hasta: datetime) -> dict[int, dict]:
    """Entradas, salidas y ajustes (piezas) por producto dentro del rango.

    stock_final = stock_inicial + entradas − salidas + ajustes.
    """
    filas = (
        session.query(Movimiento.producto_id, Movimiento.tipo, func.sum(Movimiento.piezas))
        .filter(Movimiento.fecha_hora >= desde, Movimiento.fecha_hora <= hasta)
        .group_by(Movimiento.producto_id, Movimiento.tipo)
        .all()
    )
    resultado: dict[int, dict] = {}
    for pid, tipo, piezas in filas:
        r = resultado.setdefault(pid, {"entradas": 0, "salidas": 0, "ajustes": 0})
        if tipo == "ENTRADA":
            r["entradas"] += int(piezas)
        elif tipo in ("SALIDA", "BAJA_CADUCIDAD"):
            r["salidas"] += int(piezas)
        else:  # AJUSTE, con signo
            r["ajustes"] += int(piezas)
    return resultado


def lote_fefo(producto: Producto) -> Lote | None:
    """El lote con caducidad más próxima que aún tenga cajas (regla FEFO)."""
    candidatos = [l for l in producto.lotes if l.cajas > 0]
    return min(candidatos, key=lambda l: l.fecha_caducidad) if candidatos else None


def trasladar(session: Session, *, usuario: Usuario, producto_origen: Producto,
              ubicacion_destino, piezas: int = 0, cajas: int = 0,
              lote: Lote | None = None) -> tuple[Movimiento, Movimiento, Producto]:
    """Mueve existencias entre áreas en UNA operación: SALIDA en el origen y
    ENTRADA en el destino, ligadas por la causa 'Traslado entre áreas' y el
    mismo lote/caducidad. Ambas dentro de la misma transacción: quien llama
    hace commit si todo pasó, o rollback y no ocurrió nada (nunca queda una
    salida sin su entrada — stock "perdido" entre áreas).

    Si el producto no existe aún en el área destino, se replica ahí (mismo
    nombre, tipo, unidad y piezas por caja): no es un alta de catálogo nueva,
    es el mismo producto en otro lugar.
    """
    if ubicacion_destino is None or ubicacion_destino.id == producto_origen.ubicacion_id:
        raise MovimientoInvalido("Elige un área destino distinta a la actual")
    causa = session.query(Causa).filter_by(nombre="Traslado entre áreas").first()
    if causa is None:
        raise MovimientoInvalido("Falta la causa 'Traslado entre áreas' en el catálogo")

    destino = session.query(Producto).filter_by(
        nombre=producto_origen.nombre, tipo_id=producto_origen.tipo_id,
        ubicacion_id=ubicacion_destino.id).first()
    if destino is None:
        destino = Producto(
            nombre=producto_origen.nombre, tipo_id=producto_origen.tipo_id,
            ubicacion_id=ubicacion_destino.id, unidad=producto_origen.unidad,
            piezas_por_caja=producto_origen.piezas_por_caja, stock_base=0)
        session.add(destino)
        session.flush()
    elif not destino.activo:
        destino.activo = True  # volver a surtir un área lo reactiva

    salida = registrar_movimiento(
        session, usuario=usuario, producto=producto_origen, tipo="SALIDA",
        piezas=piezas, cajas=cajas, lote=lote, causa=causa,
        causa_detalle=f"Traslado a {ubicacion_destino.nombre}")
    entrada = registrar_movimiento(
        session, usuario=usuario, producto=destino, tipo="ENTRADA",
        piezas=piezas, cajas=cajas, fecha_caducidad=salida.fecha_caducidad,
        causa=causa, causa_detalle=f"Traslado desde {producto_origen.ubicacion.nombre}")
    return salida, entrada, destino


def resumen_lotes(producto: Producto, hoy: date | None = None) -> dict:
    """Cajas totales, lote más urgente y su categoría de semáforo (comparte
    la misma definición entre inventario, API y vistas)."""
    urgente = lote_fefo(producto)
    return {
        "cajas": sum(l.cajas for l in producto.lotes if l.cajas > 0),
        "urgente": urgente,
        "categoria": semaforo(urgente.fecha_caducidad, hoy) if urgente else None,
    }


def registrar_movimiento(
    session: Session, *, usuario: Usuario, producto: Producto, tipo: str,
    piezas: int = 0, cajas: int = 0, lote: Lote | None = None,
    fecha_caducidad: date | None = None, causa: Causa | None = None,
    causa_detalle: str | None = None, paciente_ref: str | None = None,
) -> Movimiento:
    if tipo not in ("ENTRADA", "SALIDA", "AJUSTE", "BAJA_CADUCIDAD"):
        raise MovimientoInvalido("Tipo de movimiento inválido")
    if producto.unidad == "caja" and piezas != 0:
        raise MovimientoInvalido(
            f"'{producto.nombre}' se controla por caja completa: no se capturan piezas")
    if tipo != "AJUSTE" and (piezas < 0 or cajas < 0):
        raise MovimientoInvalido("Piezas y cajas deben ser positivas (usa AJUSTE para corregir)")
    if piezas == 0 and cajas == 0:
        raise MovimientoInvalido("Captura al menos piezas o cajas")
    if tipo == "AJUSTE" and causa is None:
        raise MovimientoInvalido("Un AJUSTE siempre requiere causa")

    # --- efecto en cajas: siempre sobre un lote (fecha de caducidad)
    if cajas != 0:
        if tipo == "ENTRADA":
            if fecha_caducidad is None:
                raise MovimientoInvalido("Una ENTRADA de cajas requiere fecha de caducidad")
            lote = next((l for l in producto.lotes if l.fecha_caducidad == fecha_caducidad), None)
            if lote is None:
                lote = Lote(producto=producto, cajas=0, fecha_caducidad=fecha_caducidad)
                session.add(lote)
            lote.cajas += cajas
        else:  # SALIDA, BAJA_CADUCIDAD, AJUSTE tocan un lote existente
            if lote is None:
                raise MovimientoInvalido("Indica de qué lote (fecha de caducidad) salen las cajas")
            lote.cajas += cajas if tipo == "AJUSTE" else -cajas

    movimiento = Movimiento(
        fecha_hora=datetime.now(),
        producto_id=producto.id,
        tipo=tipo,
        piezas=piezas,
        cajas=cajas,
        fecha_caducidad=lote.fecha_caducidad if lote is not None else fecha_caducidad,
        causa_id=causa.id if causa else None,
        causa_detalle=(causa_detalle or "").strip() or None,
        paciente_ref=(paciente_ref or "").strip() or None,
        usuario_id=usuario.id,
        historico=False,
    )
    session.add(movimiento)

    # El INSERT va ANTES de validar: adquiere el candado de escritura de SQLite y
    # serializa las capturas concurrentes. Validar-antes-de-insertar permitiría que
    # dos salidas simultáneas pasaran ambas el chequeo (race condition check-then-act).
    # Si la validación falla, quien llama hace rollback y nada persiste.
    session.flush()
    if lote is not None:
        movimiento.lote_id = lote.id
        if lote.cajas < 0:
            raise MovimientoInvalido(
                f"El lote {lote.fecha_caducidad} no tiene cajas suficientes "
                f"(quedaría en {lote.cajas})")

    actual = stock_piezas(session, producto.id)  # ya incluye este movimiento
    if actual < 0:
        raise MovimientoInvalido(
            f"Stock insuficiente: el movimiento dejaría {actual} piezas")
    return movimiento

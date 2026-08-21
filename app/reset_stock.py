"""Deja TODAS las existencias en cero para arrancar el inventario limpio.

No borra nada: genera movimientos de AJUSTE auditados (quién, cuándo, por qué)
hasta dejar cada producto en 0 piezas y cada lote en 0 cajas. Por eso:

  - Usuarios, contraseñas y permisos: intactos.
  - Catálogo de productos, tipos, ubicaciones y causas: intacto.
  - Historial de movimientos: intacto (además queda registrado este reset).

Uso:
  python -m app.reset_stock                 -> vista previa, no cambia nada
  python -m app.reset_stock --aplicar       -> aplica (respalda antes)

Después de aplicar, el personal captura las existencias reales con ENTRADA.
"""
import socket
import sys
from datetime import date

from . import respaldo, services
from .db import SessionLocal
from .models import Causa, Lote, Movimiento, Producto, Usuario

MOTIVO = "Reset inicial de inventario"
PUERTO_APP = 8000


def _servidor_encendido() -> bool:
    """El reset debe correr con SIFAR detenido: si alguien captura mientras tanto,
    su movimiento puede perderse o dejar existencias distintas de cero."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", PUERTO_APP)) == 0


def _reset_previo(session) -> Movimiento | None:
    return (session.query(Movimiento)
            .filter(Movimiento.causa_detalle.like(f"{MOTIVO}%"))
            .order_by(Movimiento.fecha_hora.desc())
            .first())


def _usuario_sistema(session):
    """Atribuye el reset al usuario de sistema; si no existe, al primer admin."""
    u = session.query(Usuario).filter_by(nombre="Migración Excel").first()
    return u or session.query(Usuario).filter_by(rol="admin").first()


def analizar(session) -> dict:
    stocks = services.stock_piezas_todos(session)
    productos = {p.id: p for p in session.query(Producto)}

    piezas = [(productos[pid], cant) for pid, cant in stocks.items()
              if cant != 0 and pid in productos]
    lotes = session.query(Lote).filter(Lote.cajas != 0).all()
    return {
        "piezas": sorted(piezas, key=lambda x: x[0].nombre),
        "lotes": lotes,
        "total_piezas": sum(c for _, c in piezas),
        "total_cajas": sum(l.cajas for l in lotes),
    }


def aplicar(session, plan) -> list[str]:
    usuario = _usuario_sistema(session)
    if usuario is None:
        raise SystemExit("ERROR: no hay usuario para atribuir el reset.")
    causa = session.query(Causa).filter_by(nombre="Ajuste por conteo").first()
    if causa is None:
        raise SystemExit("ERROR: falta la causa 'Ajuste por conteo' en el catálogo.")
    detalle = f"{MOTIVO} {date.today():%d/%m/%Y}"

    # TODO-O-NADA: sin savepoints, en una sola transacción. Si algo falla se
    # revierte completo, para que nunca quede el inventario a medio poner en cero
    # (un corte de luz o un error dejaría la mitad vieja y la mitad en cero, sin
    # forma de distinguirlo después). Las cantidades se releen aquí y no se toma
    # la foto del plan, que pudo quedar vieja.
    try:
        for producto, _ in plan["piezas"]:
            actual = services.stock_piezas(session, producto.id)
            if actual != 0:
                services.registrar_movimiento(
                    session, usuario=usuario, producto=producto, tipo="AJUSTE",
                    piezas=-actual, causa=causa, causa_detalle=detalle)

        for lote in plan["lotes"]:
            session.refresh(lote)
            if lote.cajas != 0:
                services.registrar_movimiento(
                    session, usuario=usuario, producto=lote.producto, tipo="AJUSTE",
                    cajas=-lote.cajas, lote=lote, causa=causa, causa_detalle=detalle)
        session.commit()
    except Exception as exc:
        session.rollback()
        return [f"No se aplicó ningún cambio (todo revertido): {exc}"]
    return []


def verificar(session) -> list[str]:
    """Relee el estado y devuelve el detalle de lo que NO quedó en cero."""
    session.expire_all()
    stocks = services.stock_piezas_todos(session)
    productos = {p.id: p for p in session.query(Producto)}
    residuos = [f"'{productos[pid].nombre}': {cant} piezas"
                for pid, cant in stocks.items() if cant != 0 and pid in productos]
    residuos += [f"'{l.producto.nombre}' lote {l.fecha_caducidad}: {l.cajas} cajas"
                 for l in session.query(Lote).filter(Lote.cajas != 0)]
    return residuos


def run(aplicar_cambios: bool, forzar: bool = False) -> None:
    with SessionLocal() as session:
        plan = analizar(session)
        n_piezas, n_lotes = len(plan["piezas"]), len(plan["lotes"])
        previo = _reset_previo(session)

        print(f"Productos con piezas por poner en cero: {n_piezas} "
              f"({plan['total_piezas']} piezas en total)")
        print(f"Lotes con cajas por poner en cero:      {n_lotes} "
              f"({plan['total_cajas']} cajas en total)")
        print("Usuarios y contraseñas: NO se tocan. Historial: se conserva.")

        if previo:
            print(f"\n*** AVISO: ya se hizo un reset el {previo.fecha_hora:%d/%m/%Y a las %H:%M}.")
            print("    Si el personal ya capturó existencias reales, volver a")
            print("    ejecutarlo LAS BORRARIA. Continúe solo si está seguro.")

        if n_piezas == 0 and n_lotes == 0:
            print("\nEl inventario ya está en cero. No hay nada que hacer.")
            return

        if not aplicar_cambios:
            print("\nEjemplos de lo que se pondria en cero:")
            for producto, cantidad in plan["piezas"][:5]:
                print(f"   {producto.nombre[:52]:52s} {cantidad} -> 0 piezas")
            if n_piezas > 5:
                print(f"   ... y {n_piezas - 5} productos mas")
            print("\n(VISTA PREVIA: no se cambio nada. Para aplicar: --aplicar)")
            return

        # Con SIFAR encendido, alguien podría capturar a media operación.
        if _servidor_encendido():
            print("\nERROR: SIFAR está encendido (puerto 8000 en uso).")
            print("Cierre la ventana negra del servidor y vuelva a intentarlo.")
            sys.exit(2)

        if previo and not forzar:
            print("\nCANCELADO por seguridad: ya existe un reset previo.")
            print("Si de verdad quiere volver a poner todo en cero, ejecute:")
            print("   .venv\\Scripts\\python -m app.reset_stock --aplicar --forzar")
            sys.exit(3)

        copia = respaldo.run("respaldo")
        print(f"\nRespaldo previo creado: {copia}")
        errores = aplicar(session, plan)
        residuos = verificar(session)

        movimientos = session.query(Movimiento).filter(
            Movimiento.causa_detalle.like(f"{MOTIVO}%")).count()
        print(f"Movimientos de ajuste registrados: {movimientos}")
        if errores:
            print(f"Rechazos ({len(errores)}):")
            for e in errores:
                print(f"   ! {e}")
        if residuos:
            print(f"\nATENCION: {len(residuos)} cosas NO quedaron en cero:")
            for r in residuos[:20]:
                print(f"   - {r}")
            if len(residuos) > 20:
                print(f"   ... y {len(residuos) - 20} mas")
            print("Vuelva a ejecutar el reset para terminar, o restaure el respaldo.")
            sys.exit(1)
        print("VERIFICADO: todo el inventario quedo en CERO.")
        print("El personal ya puede capturar las existencias reales con ENTRADA.")


if __name__ == "__main__":
    run("--aplicar" in sys.argv, "--forzar" in sys.argv)

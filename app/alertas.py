from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from . import services
from .auth import require_user
from .plantillas import templates
from .db import get_session
from .models import Lote, Producto, Usuario

router = APIRouter()

DIAS_PROXIMOS = 180  # mismo horizonte que usaba la macro Proximos_Caducar


@router.get("/alertas")
def alertas(request: Request, session: Session = Depends(get_session),
            usuario: Usuario = Depends(require_user)):
    hoy = date.today()

    lotes = (
        session.query(Lote)
        .options(joinedload(Lote.producto).joinedload(Producto.ubicacion))
        .filter(Lote.cajas > 0)
        .order_by(Lote.fecha_caducidad)
        .all()
    )
    caducos = [l for l in lotes if l.fecha_caducidad < hoy]
    proximos = [l for l in lotes
                if hoy <= l.fecha_caducidad <= hoy + timedelta(days=DIAS_PROXIMOS)]

    # Descuadre piezas/cajas: con cajas llenas piezas = cajas*ppc; una caja abierta
    # baja hasta (cajas-1)*ppc. Fuera del rango ((cajas-1)*ppc, cajas*ppc] hay
    # algo que revisar. Solo avisa (nunca bloquea) y solo con datos suficientes.
    stocks = services.stock_piezas_todos(session)
    descuadres = []
    productos = (
        session.query(Producto)
        .options(joinedload(Producto.lotes), joinedload(Producto.ubicacion))
        .filter(Producto.activo.is_(True), Producto.unidad == "pieza",
                Producto.piezas_por_caja.isnot(None))
        .all()
    )
    for p in productos:
        cajas = sum(l.cajas for l in p.lotes if l.cajas > 0)
        if cajas <= 0:
            continue
        piezas = stocks.get(p.id, 0)
        maximo = cajas * p.piezas_por_caja
        minimo = (cajas - 1) * p.piezas_por_caja
        if not (minimo < piezas <= maximo):
            descuadres.append({
                "p": p, "piezas": piezas, "cajas": cajas,
                "esperado": f"entre {minimo + 1} y {maximo}",
            })

    return templates.TemplateResponse(
        request, "alertas.html",
        {
            "usuario": usuario, "hoy": hoy,
            "caducos": caducos, "proximos": proximos, "descuadres": descuadres,
            "dias": DIAS_PROXIMOS,
            "semaforo": services.semaforo, "etiquetas": services.ETIQUETAS_SEMAFORO,
        },
    )

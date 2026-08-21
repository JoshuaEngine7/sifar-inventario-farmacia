from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from . import services
from .auth import require_user
from .plantillas import templates
from .db import get_session
from .models import Producto, Tipo, Ubicacion, Usuario

router = APIRouter()


@router.get("/inventario")
def inventario(request: Request, q: str = "", tipo_id: str = "",
               ubicacion_id: str = "", inactivos: str = "",
               msg: str = "", error: str = "",
               session: Session = Depends(get_session),
               usuario: Usuario = Depends(require_user)):
    # Los selects del filtro mandan "" cuando eligen "Todos"; los query params
    # int|None NO convierten "" a None (devolvían 422), por eso se parsean a mano.
    tipo_id = int(tipo_id) if tipo_id.isdecimal() else None
    ubicacion_id = int(ubicacion_id) if ubicacion_id.isdecimal() else None
    ver_inactivos = inactivos == "1" and usuario.rol == "admin"

    consulta = (
        session.query(Producto)
        .options(joinedload(Producto.lotes), joinedload(Producto.tipo),
                 joinedload(Producto.ubicacion))
        .filter(Producto.activo.is_(not ver_inactivos))
    )
    if q.strip():
        consulta = consulta.filter(Producto.nombre.ilike(f"%{q.strip()}%"))
    if tipo_id:
        consulta = consulta.filter(Producto.tipo_id == tipo_id)
    if ubicacion_id:
        consulta = consulta.filter(Producto.ubicacion_id == ubicacion_id)

    productos = consulta.order_by(Producto.nombre).all()
    stocks = services.stock_piezas_todos(session)
    hoy = date.today()

    filas = [
        {"p": p, "stock": stocks.get(p.id, 0), **services.resumen_lotes(p, hoy)}
        for p in productos
    ]

    return templates.TemplateResponse(
        request, "inventario.html",
        {
            "usuario": usuario, "filas": filas, "q": q,
            "tipo_id": tipo_id, "ubicacion_id": ubicacion_id,
            "ver_inactivos": ver_inactivos, "msg": msg, "error": error,
            "tipos": session.query(Tipo).order_by(Tipo.nombre).all(),
            "ubicaciones": session.query(Ubicacion).order_by(Ubicacion.nombre).all(),
            "etiquetas": services.ETIQUETAS_SEMAFORO,
        },
    )

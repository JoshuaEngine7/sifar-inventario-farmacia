from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from . import services
from .auth import require_api_user
from .db import get_session
from .models import Movimiento, Producto, Usuario

router = APIRouter(prefix="/api")


@router.get("/productos")
def productos(session: Session = Depends(get_session),
              usuario: Usuario = Depends(require_api_user)):
    stocks = services.stock_piezas_todos(session)
    hoy = date.today()
    resultado = []
    for p in (session.query(Producto)
              .options(joinedload(Producto.lotes), joinedload(Producto.tipo),
                       joinedload(Producto.ubicacion))
              .filter(Producto.activo.is_(True)).order_by(Producto.nombre)):
        resumen = services.resumen_lotes(p, hoy)
        urgente = resumen["urgente"]
        resultado.append({
            "id": p.id,
            "nombre": p.nombre,
            "tipo": p.tipo.nombre,
            "ubicacion": p.ubicacion.nombre,
            "unidad": p.unidad,
            "piezas_por_caja": p.piezas_por_caja,
            "stock_piezas": stocks.get(p.id, 0),
            "cajas": resumen["cajas"],
            "caducidad_proxima": urgente.fecha_caducidad.isoformat() if urgente else None,
            "semaforo": resumen["categoria"],
        })
    return resultado


@router.get("/movimientos")
def movimientos(limite: int = 100, session: Session = Depends(get_session),
                usuario: Usuario = Depends(require_api_user)):
    # paciente_ref visible para cualquier usuario autenticado (decisión del doctor, Q6).
    filas = (
        session.query(Movimiento)
        .options(joinedload(Movimiento.producto), joinedload(Movimiento.causa),
                 joinedload(Movimiento.usuario))
        .order_by(Movimiento.fecha_hora.desc(), Movimiento.id.desc())
        .limit(min(limite, 500))
        .all()
    )
    return [{
        "id": m.id,
        "fecha_hora": m.fecha_hora.isoformat(),
        "producto": m.producto.nombre,
        "tipo": m.tipo,
        "piezas": m.piezas,
        "cajas": m.cajas,
        "fecha_caducidad": m.fecha_caducidad.isoformat() if m.fecha_caducidad else None,
        "causa": m.causa.nombre if m.causa else None,
        "causa_detalle": m.causa_detalle,
        "paciente_ref": m.paciente_ref,
        "usuario": m.usuario.nombre,
        "historico": m.historico,
    } for m in filas]

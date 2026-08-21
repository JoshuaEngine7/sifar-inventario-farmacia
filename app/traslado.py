from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from . import services
from .auth import require_user
from .db import get_session
from .models import Lote, Producto, Ubicacion, Usuario
from .plantillas import templates

router = APIRouter(prefix="/traslado")


def _render(request: Request, session: Session, usuario: Usuario,
            producto: Producto, error=None, status=200):
    # Trasladar solo tiene sentido desde un lote con existencia.
    lotes = sorted((l for l in producto.lotes if l.cajas > 0),
                   key=lambda l: l.fecha_caducidad)
    fefo = services.lote_fefo(producto)
    destinos = (session.query(Ubicacion)
                .filter(Ubicacion.id != producto.ubicacion_id)
                .order_by(Ubicacion.nombre).all())
    return templates.TemplateResponse(
        request, "traslado.html",
        {
            "usuario": usuario, "producto": producto, "lotes": lotes,
            "fefo_id": fefo.id if fefo else None, "destinos": destinos,
            "stock": services.stock_piezas(session, producto.id),
            "semaforo": services.semaforo,
            "etiquetas": services.ETIQUETAS_SEMAFORO, "hoy": date.today(),
            "error": error,
        },
        status_code=status,
    )


@router.get("/{producto_id}")
def formulario(request: Request, producto_id: int,
               session: Session = Depends(get_session),
               usuario: Usuario = Depends(require_user)):
    producto = session.get(Producto, producto_id)
    if producto is None:
        return RedirectResponse(url="/captura", status_code=302)
    return _render(request, session, usuario, producto)


@router.post("/{producto_id}")
def ejecutar(request: Request, producto_id: int,
             ubicacion_destino_id: str = Form(""),
             piezas: int = Form(0),
             cajas: int = Form(0),
             lote_id: int | None = Form(None),
             session: Session = Depends(get_session),
             usuario: Usuario = Depends(require_user)):
    producto = session.get(Producto, producto_id)
    if producto is None:
        return RedirectResponse(url="/captura", status_code=302)

    destino = (session.get(Ubicacion, int(ubicacion_destino_id))
               if ubicacion_destino_id.isdecimal() else None)
    lote = session.get(Lote, lote_id) if lote_id else None
    if lote is not None and lote.producto_id != producto.id:
        return _render(request, session, usuario, producto,
                       error="El lote no corresponde al producto", status=400)

    try:
        salida, entrada, prod_destino = services.trasladar(
            session, usuario=usuario, producto_origen=producto,
            ubicacion_destino=destino, piezas=piezas, cajas=cajas, lote=lote)
        session.commit()
    except services.MovimientoInvalido as exc:
        session.rollback()
        return _render(request, session, usuario, producto, error=str(exc), status=400)
    except (OperationalError, IntegrityError):
        session.rollback()
        return _render(request, session, usuario, producto,
                       error="El sistema está ocupado guardando otro registro; "
                             "vuelve a intentar", status=503)

    ok = (f"Traslado realizado: {piezas} piezas, {cajas} cajas → "
          f"{prod_destino.ubicacion.nombre}")
    return RedirectResponse(url=f"/captura/{producto.id}?ok={quote(ok)}", status_code=302)

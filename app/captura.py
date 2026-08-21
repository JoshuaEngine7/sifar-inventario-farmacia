from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from . import services
from .auth import require_user
from .plantillas import templates
from .db import get_session
from .models import Causa, Lote, Producto, Usuario

router = APIRouter(prefix="/captura")


@router.get("")
def buscar(request: Request, q: str = "", session: Session = Depends(get_session),
           usuario: Usuario = Depends(require_user)):
    resultados = []
    if q.strip():
        resultados = (
            session.query(Producto)
            .filter(Producto.activo.is_(True), Producto.nombre.ilike(f"%{q.strip()}%"))
            .order_by(Producto.nombre).limit(50).all()
        )
    return templates.TemplateResponse(
        request, "captura_buscar.html",
        {"usuario": usuario, "q": q, "resultados": resultados},
    )


def _render_form(request: Request, session: Session, usuario: Usuario,
                 producto: Producto, error=None, mensaje=None, status=200):
    # El desplegable ofrece TODOS los lotes: un AJUSTE puede necesitar corregir
    # uno que quedó en cero, y ese es su único camino. La tabla informativa de
    # arriba sí oculta los vacíos (`lotes_con_existencia`) para no ensuciar la
    # vista tras un reset a cero.
    lotes = sorted(producto.lotes, key=lambda l: l.fecha_caducidad)
    fefo = services.lote_fefo(producto)
    return templates.TemplateResponse(
        request, "captura_form.html",
        {
            "usuario": usuario, "producto": producto, "lotes": lotes,
            "lotes_con_existencia": [l for l in lotes if l.cajas > 0],
            "fefo_id": fefo.id if fefo else None,
            "stock": services.stock_piezas(session, producto.id),
            "causas": session.query(Causa).order_by(Causa.nombre).all(),
            "semaforo": services.semaforo,
            "etiquetas": services.ETIQUETAS_SEMAFORO,
            "hoy": date.today(),
            "error": error, "mensaje": mensaje,
        },
        status_code=status,
    )


@router.get("/{producto_id}")
def formulario(request: Request, producto_id: int, ok: str | None = None,
               session: Session = Depends(get_session),
               usuario: Usuario = Depends(require_user)):
    producto = session.get(Producto, producto_id)
    if producto is None:
        return RedirectResponse(url="/captura", status_code=302)
    return _render_form(request, session, usuario, producto, mensaje=ok)


@router.post("/{producto_id}")
def registrar(request: Request, producto_id: int,
              tipo: str = Form(...),
              piezas: int = Form(0),
              cajas: int = Form(0),
              lote_id: int | None = Form(None),
              fecha_caducidad: str = Form(""),
              causa_id: int | None = Form(None),
              causa_detalle: str = Form(""),
              paciente_ref: str = Form(""),
              session: Session = Depends(get_session),
              usuario: Usuario = Depends(require_user)):
    producto = session.get(Producto, producto_id)
    if producto is None:
        return RedirectResponse(url="/captura", status_code=302)

    lote = session.get(Lote, lote_id) if lote_id else None
    if lote is not None and lote.producto_id != producto.id:
        return _render_form(request, session, usuario, producto,
                            error="El lote no corresponde al producto", status=400)
    causa = session.get(Causa, causa_id) if causa_id else None
    fecha = None
    if fecha_caducidad.strip():
        try:
            fecha = datetime.strptime(fecha_caducidad.strip(), "%Y-%m-%d").date()
        except ValueError:
            return _render_form(request, session, usuario, producto,
                                error="Fecha de caducidad inválida (usa AAAA-MM-DD)", status=400)

    try:
        movimiento = services.registrar_movimiento(
            session, usuario=usuario, producto=producto, tipo=tipo,
            piezas=piezas, cajas=cajas, lote=lote, fecha_caducidad=fecha,
            causa=causa, causa_detalle=causa_detalle, paciente_ref=paciente_ref,
        )
        session.commit()
    except services.MovimientoInvalido as exc:
        session.rollback()
        return _render_form(request, session, usuario, producto, error=str(exc), status=400)
    except (OperationalError, IntegrityError):
        # Choque de escrituras simultáneas (SQLite ocupado, o dos ENTRADAs creando
        # el mismo lote nuevo a la vez): nada se guardó.
        session.rollback()
        return _render_form(request, session, usuario, producto,
                            error="El sistema está ocupado guardando otro registro; "
                                  "vuelve a intentar", status=503)
    ok = f"{movimiento.tipo} registrada: {movimiento.piezas} piezas, {movimiento.cajas} cajas"
    return RedirectResponse(url=f"/captura/{producto.id}?ok={quote(ok)}", status_code=302)

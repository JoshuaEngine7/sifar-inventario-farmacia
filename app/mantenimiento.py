"""Operaciones de mantenimiento para el administrador, desde la propia app.

Hoy: poner todo el inventario en cero (arranque limpio). Es una operación de una
sola vía, así que exige rol admin, confirmación escrita y avisa si ya se hizo
antes. Siempre respalda primero.
"""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from . import reset_stock, respaldo, services
from .auth import require_admin
from .db import get_session
from .models import Usuario
from .plantillas import templates

router = APIRouter(prefix="/mantenimiento")

CONFIRMACION = "PONER EN CERO"


def _contexto(session: Session, usuario: Usuario, **extra) -> dict:
    plan = reset_stock.analizar(session)
    return {
        "usuario": usuario,
        "n_piezas": len(plan["piezas"]),
        "n_lotes": len(plan["lotes"]),
        "total_piezas": plan["total_piezas"],
        "total_cajas": plan["total_cajas"],
        "ejemplos": plan["piezas"][:8],
        "previo": reset_stock._reset_previo(session),
        "confirmacion": CONFIRMACION,
        "resultado": None, "error": None,
        **extra,
    }


@router.get("/reset")
def formulario(request: Request, session: Session = Depends(get_session),
               usuario: Usuario = Depends(require_admin)):
    return templates.TemplateResponse(request, "reset.html", _contexto(session, usuario))


@router.post("/reset")
def ejecutar(request: Request, confirmacion: str = Form(""),
             entiendo_reset_previo: str = Form(""),
             session: Session = Depends(get_session),
             usuario: Usuario = Depends(require_admin)):
    if confirmacion.strip().upper() != CONFIRMACION:
        return templates.TemplateResponse(
            request, "reset.html",
            _contexto(session, usuario,
                      error=f'Para continuar hay que escribir exactamente: {CONFIRMACION}'),
            status_code=400,
        )

    # Segunda barrera cuando ya hubo un reset: para entonces el personal pudo
    # haber capturado existencias reales, y repetirlo las borraría. El aviso en
    # pantalla no basta; la regla vive aquí, en el servidor.
    if reset_stock._reset_previo(session) and entiendo_reset_previo != "si":
        return templates.TemplateResponse(
            request, "reset.html",
            _contexto(session, usuario,
                      error="Ya se hizo un reset antes. Marque también la casilla de "
                            "confirmación para aceptar que se borrarán las existencias "
                            "capturadas desde entonces."),
            status_code=400,
        )

    plan = reset_stock.analizar(session)
    if not plan["piezas"] and not plan["lotes"]:
        return templates.TemplateResponse(
            request, "reset.html",
            _contexto(session, usuario, error="El inventario ya está en cero."),
            status_code=400,
        )

    copia = respaldo.run("respaldo")
    errores = reset_stock.aplicar(session, plan)
    residuos = reset_stock.verificar(session)

    return templates.TemplateResponse(
        request, "reset.html",
        _contexto(session, usuario, resultado={
            "respaldo": copia.name,
            "ajustes": len(plan["piezas"]) + len(plan["lotes"]) - len(errores),
            "errores": errores,
            "residuos": residuos,
        }),
    )

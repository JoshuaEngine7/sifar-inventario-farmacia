from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from fastapi import HTTPException

from . import services
from .auth import require_admin, require_user
from .db import get_session
from .models import Producto, Tipo, Ubicacion, Usuario
from .plantillas import templates

router = APIRouter(prefix="/productos")


def require_creador(request: Request, session: Session = Depends(get_session)) -> Usuario:
    """Alta de productos: admin siempre; los demás solo con el permiso individual
    que otorga el admin (responsabilidad compartida — petición del doctor)."""
    usuario = require_user(request, session)
    if usuario.rol != "admin" and not usuario.puede_crear_productos:
        raise HTTPException(status_code=403,
                            detail="No tienes permiso para dar de alta productos; pídelo al administrador")
    return usuario


def _render(request: Request, session: Session, usuario: Usuario,
            error=None, valores=None, status=200):
    return templates.TemplateResponse(
        request, "producto_nuevo.html",
        {
            "usuario": usuario,
            "tipos": session.query(Tipo).order_by(Tipo.nombre).all(),
            "ubicaciones": session.query(Ubicacion).order_by(Ubicacion.nombre).all(),
            "error": error,
            "valores": valores or {},
        },
        status_code=status,
    )


@router.get("/nuevo")
def nuevo_form(request: Request, session: Session = Depends(get_session),
               usuario: Usuario = Depends(require_creador)):
    return _render(request, session, usuario)


@router.post("/nuevo")
def crear(request: Request,
          nombre: str = Form(...),
          tipo_id: str = Form(""),
          ubicacion_id: str = Form(""),
          unidad: str = Form("pieza"),
          piezas_por_caja: str = Form(""),
          session: Session = Depends(get_session),
          usuario: Usuario = Depends(require_creador)):
    # Campos numéricos como str + parseo manual: los navegadores envían ""
    # en campos vacíos y Form(int) los rechazaría con 422 (lección aprendida).
    valores = {"nombre": nombre, "tipo_id": tipo_id, "ubicacion_id": ubicacion_id,
               "unidad": unidad, "piezas_por_caja": piezas_por_caja}
    nombre = nombre.strip().upper()
    if not nombre:
        return _render(request, session, usuario, "El nombre no puede estar vacío", valores, 400)
    tipo = session.get(Tipo, int(tipo_id)) if tipo_id.isdecimal() else None
    ubicacion = session.get(Ubicacion, int(ubicacion_id)) if ubicacion_id.isdecimal() else None
    if tipo is None or ubicacion is None:
        return _render(request, session, usuario, "Elige tipo y ubicación", valores, 400)
    if unidad not in ("pieza", "caja"):
        return _render(request, session, usuario, "Unidad inválida", valores, 400)
    ppc = int(piezas_por_caja) if piezas_por_caja.strip().isdecimal() and int(piezas_por_caja) > 0 else None

    existente = session.query(Producto).filter_by(
        nombre=nombre, tipo_id=tipo.id, ubicacion_id=ubicacion.id).first()
    if existente:
        return _render(request, session, usuario,
                       f"Ya existe '{nombre}' como {tipo.nombre} en {ubicacion.nombre}",
                       valores, 400)

    producto = Producto(nombre=nombre, tipo_id=tipo.id, ubicacion_id=ubicacion.id,
                        unidad=unidad, piezas_por_caja=ppc, stock_base=0)
    session.add(producto)
    session.commit()
    # Directo a capturar su primera ENTRADA: el flujo natural cuando llega algo nuevo.
    return RedirectResponse(
        url=f"/captura/{producto.id}?ok=Producto creado. Registra su primera ENTRADA",
        status_code=302)


@router.post("/{producto_id}/toggle")
def activar_desactivar(producto_id: int, session: Session = Depends(get_session),
                       usuario: Usuario = Depends(require_admin)):
    producto = session.get(Producto, producto_id)
    if producto is None:
        return RedirectResponse(url="/inventario", status_code=302)

    if producto.activo:
        # Desactivar con existencias crearía "inventario fantasma" (stock que
        # nadie ve). Primero se le da salida/baja a lo que queda.
        piezas = services.stock_piezas(session, producto.id)
        cajas = sum(l.cajas for l in producto.lotes if l.cajas > 0)
        if piezas != 0 or cajas > 0:
            error = (f"'{producto.nombre}' aún tiene {piezas} piezas y {cajas} cajas: "
                     f"da salida o baja a las existencias antes de desactivarlo")
            return RedirectResponse(url=f"/inventario?error={quote(error)}", status_code=302)
        producto.activo = False
        mensaje = f"'{producto.nombre}' desactivado (su historial se conserva)"
        destino = "/inventario"
    else:
        producto.activo = True
        mensaje = f"'{producto.nombre}' reactivado"
        destino = "/inventario?inactivos=1"
    session.commit()
    return RedirectResponse(url=f"{destino}{'&' if '?' in destino else '?'}msg={quote(mensaje)}",
                            status_code=302)

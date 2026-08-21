import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from . import services
from .auth import hash_password, require_admin
from .plantillas import templates
from .db import get_session
from .models import ROLES, Configuracion, Usuario

router = APIRouter(prefix="/usuarios")


def _render(request: Request, session: Session, admin: Usuario, mensaje=None, error=None, status=200):
    usuarios = session.query(Usuario).order_by(Usuario.activo.desc(), Usuario.nombre).all()
    return templates.TemplateResponse(
        request, "usuarios.html",
        {"usuario": admin, "usuarios": usuarios, "roles": ROLES,
         "mensaje": mensaje, "error": error,
         "minutos": int(services.minutos_inactividad(session))},
        status_code=status,
    )


def _password_temporal() -> str:
    # Legible para dictarla en persona; se fuerza a cambiarla al primer login.
    return "Temp-" + secrets.token_hex(3)


def _es_intocable(usuario: Usuario) -> bool:
    # El usuario de sistema no se activa, resetea ni cambia de rol — la plantilla
    # oculta los botones, pero la regla debe vivir también en el servidor.
    return usuario.nombre == "Migración Excel"


@router.get("")
def listar(request: Request, session: Session = Depends(get_session),
           admin: Usuario = Depends(require_admin)):
    return _render(request, session, admin)


@router.post("")
def crear(request: Request, nombre: str = Form(...), rol: str = Form(...),
          session: Session = Depends(get_session), admin: Usuario = Depends(require_admin)):
    nombre = nombre.strip()
    if not nombre:
        return _render(request, session, admin, error="El nombre no puede estar vacío", status=400)
    if rol not in ROLES:
        return _render(request, session, admin, error="Rol inválido", status=400)
    if session.query(Usuario).filter_by(nombre=nombre).first():
        return _render(request, session, admin, error=f"Ya existe un usuario '{nombre}'", status=400)

    temporal = _password_temporal()
    session.add(Usuario(nombre=nombre, rol=rol, password_hash=hash_password(temporal),
                        debe_cambiar_password=True, activo=True))
    session.commit()
    return _render(request, session, admin,
                   mensaje=f"Usuario '{nombre}' creado. Contraseña temporal: {temporal} "
                           f"(deberá cambiarla al entrar)")


@router.post("/{usuario_id}/reset")
def resetear(request: Request, usuario_id: int, session: Session = Depends(get_session),
             admin: Usuario = Depends(require_admin)):
    objetivo = session.get(Usuario, usuario_id)
    if objetivo is None or _es_intocable(objetivo):
        return _render(request, session, admin, error="Usuario no encontrado", status=404)
    temporal = _password_temporal()
    objetivo.password_hash = hash_password(temporal)
    objetivo.debe_cambiar_password = True
    session.commit()
    return _render(request, session, admin,
                   mensaje=f"Contraseña de '{objetivo.nombre}' reseteada. Temporal: {temporal}")


@router.post("/{usuario_id}/toggle")
def activar_desactivar(request: Request, usuario_id: int,
                       session: Session = Depends(get_session),
                       admin: Usuario = Depends(require_admin)):
    objetivo = session.get(Usuario, usuario_id)
    if objetivo is None or _es_intocable(objetivo):
        return _render(request, session, admin, error="Usuario no encontrado", status=404)
    if objetivo.id == admin.id:
        return _render(request, session, admin,
                       error="No puedes desactivarte a ti mismo", status=400)
    objetivo.activo = not objetivo.activo
    session.commit()
    estado = "activado" if objetivo.activo else "desactivado"
    return _render(request, session, admin, mensaje=f"Usuario '{objetivo.nombre}' {estado}")


@router.post("/{usuario_id}/permiso-productos")
def permiso_productos(request: Request, usuario_id: int,
                      session: Session = Depends(get_session),
                      admin: Usuario = Depends(require_admin)):
    objetivo = session.get(Usuario, usuario_id)
    if objetivo is None or _es_intocable(objetivo):
        return _render(request, session, admin, error="Usuario no encontrado", status=404)
    if objetivo.rol == "admin":
        return _render(request, session, admin,
                       error="Los administradores siempre pueden crear productos", status=400)
    objetivo.puede_crear_productos = not objetivo.puede_crear_productos
    session.commit()
    estado = "puede" if objetivo.puede_crear_productos else "ya no puede"
    return _render(request, session, admin,
                   mensaje=f"'{objetivo.nombre}' {estado} dar de alta productos")


@router.post("/config")
def configurar(request: Request, minutos: str = Form(""),
               session: Session = Depends(get_session),
               admin: Usuario = Depends(require_admin)):
    if not minutos.strip().isdecimal() or not 5 <= int(minutos) <= 120:
        return _render(request, session, admin,
                       error="El cierre por inactividad debe ser entre 5 y 120 minutos",
                       status=400)
    fila = session.query(Configuracion).filter_by(clave="minutos_inactividad").first()
    if fila is None:
        fila = Configuracion(clave="minutos_inactividad", valor=minutos)
        session.add(fila)
    fila.valor = minutos.strip()
    session.commit()
    return _render(request, session, admin,
                   mensaje=f"Cierre de sesión por inactividad: {minutos} minutos")


@router.post("/{usuario_id}/rol")
def cambiar_rol(request: Request, usuario_id: int, rol: str = Form(...),
                session: Session = Depends(get_session),
                admin: Usuario = Depends(require_admin)):
    objetivo = session.get(Usuario, usuario_id)
    if objetivo is None or _es_intocable(objetivo):
        return _render(request, session, admin, error="Usuario no encontrado", status=404)
    if rol not in ROLES:
        return _render(request, session, admin, error="Rol inválido", status=400)
    if objetivo.id == admin.id and rol != "admin":
        return _render(request, session, admin,
                       error="No puedes quitarte el rol admin a ti mismo", status=400)
    objetivo.rol = rol
    session.commit()
    return _render(request, session, admin, mensaje=f"Rol de '{objetivo.nombre}' → {rol}")

import secrets
import time
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from . import services
from .db import get_session
from .plantillas import templates
from .models import Usuario

router = APIRouter()

SECRET_FILE = Path(__file__).resolve().parent.parent / ".secret_key"


def get_secret_key() -> str:
    # Persistente entre reinicios para no invalidar sesiones en cada arranque.
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))
    return SECRET_FILE.read_text().strip()


def verify_password(plain: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain.encode(), password_hash.encode())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def get_current_user(request: Request, session: Session = Depends(get_session)) -> Usuario | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    usuario = session.get(Usuario, user_id)
    if usuario is None or not usuario.activo:
        request.session.clear()
        return None
    # Cierre por inactividad (petición del doctor): si pasó más del límite sin
    # peticiones, la sesión muere en el servidor aunque el navegador siga abierto.
    ahora = time.time()
    ultimo = request.session.get("last_activity")
    if ultimo is not None and ahora - ultimo > services.minutos_inactividad(session) * 60:
        request.session.clear()
        return None
    request.session["last_activity"] = int(ahora)
    return usuario


def require_user(request: Request, session: Session = Depends(get_session)) -> Usuario:
    """Para vistas HTML: exige sesión y contraseña ya renovada."""
    usuario = get_current_user(request, session)
    if usuario is None:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if usuario.debe_cambiar_password and request.url.path != "/cambiar-password":
        raise HTTPException(status_code=302, headers={"Location": "/cambiar-password"})
    return usuario


def require_admin(request: Request, session: Session = Depends(get_session)) -> Usuario:
    usuario = require_user(request, session)
    if usuario.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return usuario


def require_api_user(request: Request, session: Session = Depends(get_session)) -> Usuario:
    """Para la API JSON: 401 en vez de redirect."""
    usuario = get_current_user(request, session)
    if usuario is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    return usuario


@router.get("/login")
def login_form(request: Request, inactividad: int = 0, session: Session = Depends(get_session)):
    usuarios = session.query(Usuario).filter_by(activo=True).order_by(Usuario.nombre).all()
    # El usuario de sistema no aparece (activo=False), pero por claridad se filtra igual.
    aviso = "Sesión cerrada automáticamente por inactividad" if inactividad else None
    return templates.TemplateResponse(
        request, "login.html", {"usuarios": usuarios, "error": None, "aviso": aviso})


@router.post("/ping")
def ping(usuario: Usuario = Depends(require_api_user)):
    # El navegador lo llama mientras hay actividad real (mouse/teclado) para
    # mantener viva la sesión del servidor aunque no se navegue.
    return Response(status_code=204)


@router.get("/logout-inactividad")
def logout_inactividad(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login?inactividad=1", status_code=302)


@router.post("/login")
def login(request: Request, nombre: str = Form(...), password: str = Form(...),
          session: Session = Depends(get_session)):
    usuario = session.query(Usuario).filter_by(nombre=nombre, activo=True).first()
    if usuario is None or not verify_password(password, usuario.password_hash):
        usuarios = session.query(Usuario).filter_by(activo=True).order_by(Usuario.nombre).all()
        return templates.TemplateResponse(
            request, "login.html",
            {"usuarios": usuarios, "error": "Usuario o contraseña incorrecta"},
            status_code=401,
        )
    request.session["user_id"] = usuario.id
    destino = "/cambiar-password" if usuario.debe_cambiar_password else "/inventario"
    return RedirectResponse(url=destino, status_code=302)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/cambiar-password")
def cambiar_password_form(request: Request, session: Session = Depends(get_session)):
    usuario = get_current_user(request, session)
    if usuario is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request, "cambiar_password.html",
        {"usuario": usuario, "error": None, "obligatorio": usuario.debe_cambiar_password},
    )


@router.post("/cambiar-password")
def cambiar_password(request: Request, actual: str = Form(...), nueva: str = Form(...),
                     confirmacion: str = Form(...), session: Session = Depends(get_session)):
    usuario = get_current_user(request, session)
    if usuario is None:
        return RedirectResponse(url="/login", status_code=302)

    error = None
    if not verify_password(actual, usuario.password_hash):
        error = "La contraseña actual no coincide"
    elif len(nueva) < 8:
        error = "La contraseña nueva debe tener al menos 8 caracteres"
    elif nueva != confirmacion:
        error = "La confirmación no coincide"
    elif nueva == actual:
        error = "La contraseña nueva debe ser diferente a la actual"

    if error:
        return templates.TemplateResponse(
            request, "cambiar_password.html",
            {"usuario": usuario, "error": error, "obligatorio": usuario.debe_cambiar_password},
            status_code=400,
        )

    usuario.password_hash = hash_password(nueva)
    usuario.debe_cambiar_password = False
    session.add(usuario)
    session.commit()
    return RedirectResponse(url="/inventario", status_code=302)

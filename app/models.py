from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

TIPOS_MOVIMIENTO = ("ENTRADA", "SALIDA", "AJUSTE", "BAJA_CADUCIDAD")
ROLES = ("admin", "medico", "enfermeria")
UNIDADES = ("pieza", "caja")


class Tipo(Base):
    __tablename__ = "tipos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)


class Ubicacion(Base):
    __tablename__ = "ubicaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)


class Causa(Base):
    __tablename__ = "causas"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)


class Configuracion(Base):
    __tablename__ = "configuracion"
    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(50), unique=True)
    valor: Mapped[str] = mapped_column(String(100))


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    rol: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(80))
    debe_cambiar_password: Mapped[bool] = mapped_column(default=True)
    # Permiso individual otorgado por el admin (los admin siempre pueden).
    puede_crear_productos: Mapped[bool] = mapped_column(default=False)
    activo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (CheckConstraint(f"rol IN {ROLES}", name="rol_valido"),)


class Producto(Base):
    __tablename__ = "productos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipos.id"))
    ubicacion_id: Mapped[int] = mapped_column(ForeignKey("ubicaciones.id"))
    unidad: Mapped[str] = mapped_column(String(10), default="pieza")
    piezas_por_caja: Mapped[int | None] = mapped_column(default=None)
    clave: Mapped[str | None] = mapped_column(String(40), default=None)
    # Saldo de piezas al momento de la migración (Stock Final del Excel, "tal cual"
    # — decisión del doctor). Stock actual = stock_base + movimientos no históricos.
    stock_base: Mapped[int] = mapped_column(default=0)
    activo: Mapped[bool] = mapped_column(default=True)

    tipo: Mapped[Tipo] = relationship()
    ubicacion: Mapped[Ubicacion] = relationship()
    lotes: Mapped[list["Lote"]] = relationship(back_populates="producto")

    __table_args__ = (
        # El mismo nombre puede repetirse entre ubicaciones (farmacia y carro rojo)
        # y entre tipos dentro de la misma ubicación (así viene el Excel:
        # p.ej. BUTILHIOSINA como Inyectable y como Medicamento, ambos en Farmacia).
        UniqueConstraint("nombre", "tipo_id", "ubicacion_id", name="producto_unico"),
        CheckConstraint(f"unidad IN {UNIDADES}", name="unidad_valida"),
    )


class Lote(Base):
    __tablename__ = "lotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cajas: Mapped[int] = mapped_column(default=0)
    fecha_caducidad: Mapped[date]

    producto: Mapped[Producto] = relationship(back_populates="lotes")

    __table_args__ = (
        UniqueConstraint("producto_id", "fecha_caducidad", name="lote_unico_por_fecha"),
    )


class Movimiento(Base):
    __tablename__ = "movimientos"
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha_hora: Mapped[datetime] = mapped_column(default=datetime.now)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes.id"), default=None)
    tipo: Mapped[str] = mapped_column(String(20))
    piezas: Mapped[int] = mapped_column(default=0)
    cajas: Mapped[int] = mapped_column(default=0)
    # La fecha de caducidad viaja con el movimiento para conservar la del historial
    # migrado (sus lotes de origen ya no existen) y la de bajas de caja.
    fecha_caducidad: Mapped[date | None] = mapped_column(default=None)
    causa_id: Mapped[int | None] = mapped_column(ForeignKey("causas.id"), default=None)
    causa_detalle: Mapped[str | None] = mapped_column(String(300), default=None)
    paciente_ref: Mapped[str | None] = mapped_column(String(200), default=None)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # True = importado del Excel: es archivo de consulta y NO suma al stock,
    # porque stock_base ya refleja su efecto (evita contar doble).
    historico: Mapped[bool] = mapped_column(default=False)

    producto: Mapped[Producto] = relationship()
    causa: Mapped[Causa | None] = relationship()
    usuario: Mapped[Usuario] = relationship()

    __table_args__ = (
        CheckConstraint(f"tipo IN {TIPOS_MOVIMIENTO}", name="tipo_movimiento_valido"),
    )

"""Siembra una base de datos de DEMOSTRACIÓN: catálogo genérico + lotes + movimientos.

Para levantar una demo funcional sin datos reales:

    python -m app.demo_data
    python -m uvicorn app.main:app --port 8000

Aborta si la BD ya tiene productos (borra farmacia.db* para regenerar).
Las fechas de caducidad son RELATIVAS a hoy, así el semáforo muestra todas sus
categorías sin importar cuándo se ejecute. Los movimientos pasan por
services.registrar_movimiento(): las mismas reglas de negocio que producción.
"""
import sys
from datetime import date, timedelta

from . import seed
from .db import SessionLocal
from .models import Causa, Producto, Tipo, Ubicacion, Usuario
from .services import registrar_movimiento

# Días para caducar de cada lote demo, elegidos para cubrir el semáforo completo:
# 500=verde, 375=pronto a amarillo, 300=amarilla, 190=pronto a rojo,
# 90=rojo, 15=vence en 1 mes, -45=caduco.

# (nombre, tipo, ubicación, unidad, piezas_por_caja, piezas, [(cajas, días_para_caducar), ...])
PRODUCTOS = [
    ("PARACETAMOL 500 MG CAJA CON 10 TABLETAS", "Medicamento", "Farmacia", "pieza", 10, 240, [(12, 500), (4, 90)]),
    ("IBUPROFENO 400 MG CAJA CON 10 TABLETAS", "Medicamento", "Farmacia", "pieza", 10, 180, [(10, 300)]),
    ("OMEPRAZOL 20 MG CAJA CON 14 CAPSULAS", "Medicamento", "Farmacia", "pieza", 14, 154, [(8, 375)]),
    ("METFORMINA 850 MG CAJA CON 30 TABLETAS", "Medicamento", "Farmacia", "pieza", 30, 300, [(6, 500), (3, 15)]),
    ("LOSARTAN 50 MG CAJA CON 30 TABLETAS", "Medicamento", "Farmacia", "pieza", 30, 270, [(7, 300)]),
    ("SALBUTAMOL AEROSOL 100 MCG", "Medicamento", "Farmacia", "pieza", None, 12, [(5, 190)]),
    ("DICLOFENACO GEL 60 G", "Medicamento", "Farmacia", "pieza", None, 9, [(4, 90)]),
    ("LORATADINA 10 MG CAJA CON 20 TABLETAS", "Medicamento", "Farmacia", "pieza", 20, 120, [(5, 500)]),
    ("NAPROXENO 250 MG CAJA CON 30 TABLETAS", "Medicamento", "Farmacia", "pieza", 30, 150, [(4, -45)]),
    ("CAPTOPRIL 25 MG CAJA CON 30 TABLETAS", "Medicamento", "Farmacia", "pieza", 30, 210, [(6, 300)]),
    ("AMBROXOL JARABE 120 ML", "Medicamento", "Farmacia", "pieza", None, 14, [(6, 15)]),
    ("AMOXICILINA 500 MG CAJA CON 12 CAPSULAS", "Antibiótico", "Farmacia", "pieza", 12, 144, [(9, 375)]),
    ("AZITROMICINA 500 MG CAJA CON 3 TABLETAS", "Antibiótico", "Farmacia", "pieza", 3, 27, [(6, 90)]),
    ("CIPROFLOXACINO 500 MG CAJA CON 8 TABLETAS", "Antibiótico", "Farmacia", "pieza", 8, 64, [(5, 300)]),
    ("CEFTRIAXONA 1 G SOLUCION INYECTABLE", "Antibiótico inyectable", "Farmacia", "pieza", None, 20, [(8, 190)]),
    ("METAMIZOL SODICO 1 G SOLUCION INYECTABLE", "Inyectable", "Farmacia", "pieza", None, 25, [(10, 500)]),
    ("KETOROLACO 30 MG SOLUCION INYECTABLE", "Inyectable", "Farmacia", "pieza", None, 18, [(6, 90)]),
    ("DIAZEPAM 10 MG CAJA CON 20 TABLETAS", "Medicamento controlado", "Farmacia controlado", "pieza", 20, 60, [(3, 300)]),
    ("TRAMADOL 50 MG CAJA CON 10 CAPSULAS", "Medicamento controlado", "Farmacia controlado", "pieza", 10, 40, [(4, 190)]),
    ("GASAS ESTERILES 10X10 CAJA CON 100", "Material", "Farmacia", "caja", 100, 0, [(15, 500)]),
    ("GUANTES DE LATEX MEDIANOS CAJA CON 100", "Material", "Farmacia", "caja", 100, 0, [(20, 375)]),
    ("JERINGAS DESECHABLES 5 ML CAJA CON 50", "Material", "Farmacia", "caja", 50, 0, [(12, 300)]),
    ("CUBREBOCAS TRIPLE CAPA CAJA CON 50", "Material", "Farmacia", "caja", 50, 0, [(18, 500)]),
    ("CONTENEDOR PUNZOCORTANTES RPBI", "Material RPBI", "Farmacia", "caja", None, 0, [(6, 500)]),
    ("BOLSA ROJA RPBI PAQUETE CON 10", "Material RPBI", "Farmacia", "caja", 10, 0, [(8, 300)]),
    ("LIDOCAINA DENTAL 2% CARTUCHO CON 50", "Material dental", "Consultorio dental", "caja", 50, 0, [(4, 190)]),
    ("RESINA FOTOCURABLE A2 JERINGA 4 G", "Material dental", "Consultorio dental", "caja", None, 0, [(3, 375)]),
    ("ADRENALINA 1 MG SOLUCION INYECTABLE", "Medicamento", "Carro rojo P1", "pieza", None, 10, [(5, 190)]),
    ("ATROPINA 1 MG SOLUCION INYECTABLE", "Medicamento", "Carro rojo P1", "pieza", None, 8, [(4, 90)]),
    ("AMIODARONA 150 MG SOLUCION INYECTABLE", "Medicamento", "Carro rojo P2", "pieza", None, 6, [(3, 300)]),
]

# Salidas de ejemplo para poblar el historial:
# (nombre_producto, piezas, usuario, paciente_ref)
SALIDAS = [
    ("PARACETAMOL 500 MG CAJA CON 10 TABLETAS", 20, "Dra. Médico Demo", "PAC-DEMO-001"),
    ("AMOXICILINA 500 MG CAJA CON 12 CAPSULAS", 12, "Dra. Médico Demo", "PAC-DEMO-002"),
    ("METFORMINA 850 MG CAJA CON 30 TABLETAS", 30, "Enf. Enfermería Demo", "PAC-DEMO-003"),
    ("IBUPROFENO 400 MG CAJA CON 10 TABLETAS", 10, "Enf. Enfermería Demo", "PAC-DEMO-004"),
    ("OMEPRAZOL 20 MG CAJA CON 14 CAPSULAS", 14, "Dra. Médico Demo", "PAC-DEMO-005"),
    ("KETOROLACO 30 MG SOLUCION INYECTABLE", 2, "Dra. Médico Demo", "PAC-DEMO-006"),
]


def run() -> None:
    seed.run()  # tablas, catálogos y usuarios demo
    with SessionLocal() as session:
        if session.query(Producto).count() > 0:
            sys.exit("La BD ya tiene productos. Borra farmacia.db* y vuelve a correr demo_data.")

        tipos = {t.nombre: t for t in session.query(Tipo)}
        ubicaciones = {u.nombre: u for u in session.query(Ubicacion)}
        causas = {c.nombre: c for c in session.query(Causa)}
        usuarios = {u.nombre: u for u in session.query(Usuario)}
        admin = usuarios["Admin Demo"]
        hoy = date.today()

        productos: dict[str, Producto] = {}
        for nombre, tipo, ubic, unidad, ppc, piezas, lotes in PRODUCTOS:
            p = Producto(
                nombre=nombre, tipo_id=tipos[tipo].id, ubicacion_id=ubicaciones[ubic].id,
                unidad=unidad, piezas_por_caja=ppc, stock_base=0,
            )
            session.add(p)
            session.flush()
            productos[nombre] = p

            # Entradas iniciales: una por lote (cajas + caducidad) y una de piezas.
            for cajas, dias in lotes:
                registrar_movimiento(
                    session, usuario=admin, producto=p, tipo="ENTRADA", cajas=cajas,
                    fecha_caducidad=hoy + timedelta(days=dias),
                    causa_detalle="Carga inicial demo")
            if piezas > 0:
                registrar_movimiento(
                    session, usuario=admin, producto=p, tipo="ENTRADA", piezas=piezas,
                    causa_detalle="Carga inicial demo")

        for nombre, piezas, usuario, paciente in SALIDAS:
            registrar_movimiento(
                session, usuario=usuarios[usuario], producto=productos[nombre],
                tipo="SALIDA", piezas=piezas,
                causa=causas["Tratamiento / receta a paciente"], paciente_ref=paciente)

        # Una baja por caducidad (lote vencido de NAPROXENO) y un ajuste por conteo.
        naproxeno = productos["NAPROXENO 250 MG CAJA CON 30 TABLETAS"]
        lote_vencido = min(naproxeno.lotes, key=lambda l: l.fecha_caducidad)
        registrar_movimiento(
            session, usuario=admin, producto=naproxeno, tipo="BAJA_CADUCIDAD",
            cajas=2, lote=lote_vencido, causa=causas["Caducidad"],
            causa_detalle="Retiro de lote vencido (demo)")
        registrar_movimiento(
            session, usuario=admin, producto=productos["LORATADINA 10 MG CAJA CON 20 TABLETAS"],
            tipo="AJUSTE", piezas=-3, causa=causas["Ajuste por conteo"],
            causa_detalle="Conteo físico semanal (demo)")

        session.commit()
        n_prod = session.query(Producto).count()

    print(f"Demo lista: {n_prod} productos con lotes y movimientos de ejemplo.")
    print("Inicia sesión con 'Admin Demo' / 'demo1234' (pedirá definir una nueva).")


if __name__ == "__main__":
    run()

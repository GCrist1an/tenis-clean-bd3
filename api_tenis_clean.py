"""
Tenis Clean · API con MongoDB y Redis (proyecto final)
Bases de Datos III · CIAF · Corte 2

Persistencia políglota:
  - MongoDB Atlas (limpieza_tenis.pares_trazabilidad): datos del negocio que NO se pueden perder
    (pares, cliente, eventos de trazabilidad, fotos).
  - Redis: copias rápidas y datos que se pueden perder.

Claves de Redis (formato tipo:entidad:id):
  cache:reporte:ingresos_por_servicio   string JSON, 120 s   (caché del reporte)
  cache:estado:REG-0001                 string JSON, 60 s    (caché del seguimiento en vivo)
  consultas:registro:REG-0001           string con INCR      (contador)
  ranking:registros_consultados         sorted set           (ranking)
  codigo_retiro:registro:REG-0006       string, 300 s        (dato temporal)

Ejecutar:
  pip install -r requirements.txt
  configurar MONGO_URL y REDIS_URL (ver .env.example)
  uvicorn api_tenis_clean:app --reload   ->  http://127.0.0.1:8000/docs
"""

import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Literal

import redis
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient

# Si existe un archivo .env (y python-dotenv está instalado), carga sus variables.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 1. Conexiones: las cadenas van en variables de entorno, nunca en el código
# ---------------------------------------------------------------------------
cliente_mongo = MongoClient(
    os.getenv("MONGO_URL") or os.getenv("MONGO_URI") or "mongodb://localhost:27017"
)
db = cliente_mongo[os.getenv("MONGO_DB") or os.getenv("MONGO_DB_NAME") or "limpieza_tenis"]
pares = db["pares_trazabilidad"]

r = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,  # texto normal en vez de bytes
)

CLAVE_REPORTE = "cache:reporte:ingresos_por_servicio"
TTL_REPORTE = 120          # 2 minutos
TTL_ESTADO = 60            # el seguimiento en vivo puede atrasarse máximo 1 minuto
TTL_CODIGO_RETIRO = 300    # el código de retiro vale 5 minutos

ESTADOS = Literal[
    "recibido", "diagnostico", "limpieza", "arreglo", "pintura", "secado",
    "control_calidad", "listo_entrega", "entregado",
]
SERVICIOS = Literal["limpieza_completa", "premium", "express"]

app = FastAPI(
    title="Tenis Clean · API con MongoDB y Redis",
    description="Trazabilidad de pares de tenis en MongoDB; caché, contador y código temporal en Redis.",
)


# ---------------------------------------------------------------------------
# 2. Modelos de validación (FastAPI responde 422 si los datos no cumplen)
# ---------------------------------------------------------------------------
class Cliente(BaseModel):
    nombre: str = Field(min_length=2)
    telefono: str = Field(pattern=r"^\d{10}$", description="10 dígitos")


class ParNuevo(BaseModel):
    codigoRegistro: str = Field(pattern=r"^REG-\d{4}$")
    cliente: Cliente
    modelo: str = Field(min_length=2)
    marca: str = Field(min_length=2)
    tipoServicio: SERVICIOS
    precio: int = Field(ge=0)
    diasEstimados: int = Field(ge=1, le=7)
    entregaDomicilio: bool = False
    actividades: list[str] = []

    model_config = {"json_schema_extra": {"example": {
        "codigoRegistro": "REG-0029",
        "cliente": {"nombre": "Kevin Velásquez", "telefono": "3209990029"},
        "modelo": "Nike Air Force 1 blanco",
        "marca": "Nike",
        "tipoServicio": "premium",
        "precio": 110000,
        "diasEstimados": 7,
        "entregaDomicilio": True,
        "actividades": ["limpieza_profunda", "pintura"],
    }}}


class ParActualizar(BaseModel):
    """Todos opcionales: se actualiza solo lo que se envíe."""
    cliente: Cliente | None = None
    modelo: str | None = None
    marca: str | None = None
    tipoServicio: SERVICIOS | None = None
    precio: int | None = Field(default=None, ge=0)
    diasEstimados: int | None = Field(default=None, ge=1, le=7)
    entregaDomicilio: bool | None = None
    actividades: list[str] | None = None

    model_config = {"json_schema_extra": {"example": {"precio": 120000, "entregaDomicilio": True}}}


# ---------------------------------------------------------------------------
# 3. Funciones de apoyo
# ---------------------------------------------------------------------------
def limpiar(doc: dict) -> dict:
    """JSON no sabe mostrar ObjectId: se convierte a texto antes de responder."""
    doc["_id"] = str(doc["_id"])
    return doc


def id_valido(id: str) -> ObjectId:
    """400 si el texto ni siquiera tiene formato de ObjectId (no se consulta Mongo)."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="El id no tiene formato válido")
    return ObjectId(id)


def invalidar_cache(codigo: str | None = None):
    """Borra la caché del reporte y, si se indica, la del seguimiento de ese registro."""
    claves = [CLAVE_REPORTE] + ([f"cache:estado:{codigo}"] if codigo else [])
    return r.delete(*claves)


@app.get("/ping", tags=["Conexión"])
def ping():
    """Comprueba la conexión a las dos bases."""
    return {
        "mongo_responde": cliente_mongo.admin.command("ping").get("ok") == 1.0,
        "redis_responde": r.ping(),
    }


# ---------------------------------------------------------------------------
# 4. CRUD de la colección principal (MongoDB)
# ---------------------------------------------------------------------------
@app.get("/pares", tags=["1. CRUD pares (MongoDB)"])
def listar_pares(
    estadoActual: ESTADOS | None = None,
    tipoServicio: SERVICIOS | None = None,
    limite: int = Query(20, ge=1, le=100),
):
    filtro = {}
    if estadoActual:
        filtro["estadoActual"] = estadoActual
    if tipoServicio:
        filtro["tipoServicio"] = tipoServicio
    cursor = pares.find(filtro).sort("fechaIngreso", -1).limit(limite)
    return [limpiar(p) for p in cursor]


@app.get("/pares/{id}", tags=["1. CRUD pares (MongoDB)"])
def ver_par(id: str):
    par = pares.find_one({"_id": id_valido(id)})
    if par is None:
        raise HTTPException(status_code=404, detail="Par no encontrado")
    return limpiar(par)


@app.post("/pares", status_code=201, tags=["1. CRUD pares (MongoDB)"])
def crear_par(par: ParNuevo):
    """Registra un par que llega al local: arranca en 'recibido' con su primer evento."""
    ahora = datetime.now(timezone.utc)
    doc = par.model_dump()
    doc.update({
        "estadoActual": "recibido",
        "fechaIngreso": ahora,
        "eventos": [{"estado": "recibido", "fecha": ahora, "nota": "Registrado desde la API"}],
        "fotos": [],
    })
    pares.insert_one(doc)                  # pymongo agrega el _id al diccionario
    invalidar_cache(par.codigoRegistro)    # el reporte y el seguimiento ya no son ciertos
    return limpiar(doc)


@app.put("/pares/{id}", tags=["1. CRUD pares (MongoDB)"])
def actualizar_par(id: str, cambios: ParActualizar):
    """Actualiza uno o varios campos. El estado se cambia en PUT /pares/{id}/estado."""
    oid = id_valido(id)
    datos = cambios.model_dump(exclude_unset=True)
    if not datos:
        raise HTTPException(status_code=400, detail="No se envió ningún campo para actualizar")
    par = pares.find_one_and_update({"_id": oid}, {"$set": datos}, return_document=True)
    if par is None:
        raise HTTPException(status_code=404, detail="Par no encontrado")
    invalidar_cache(par["codigoRegistro"])
    return limpiar(par)


@app.put("/pares/{id}/estado", tags=["1. CRUD pares (MongoDB)"])
def cambiar_estado(id: str, nuevo_estado: ESTADOS, nota: str = "", invalidar: bool = True):
    """El encargado avanza el par en el taller: $set del estado y $push del evento."""
    oid = id_valido(id)
    evento = {"estado": nuevo_estado, "fecha": datetime.now(timezone.utc),
              "nota": nota or f"Cambio a {nuevo_estado}"}
    par = pares.find_one_and_update(
        {"_id": oid},
        {"$set": {"estadoActual": nuevo_estado}, "$push": {"eventos": evento}},
        return_document=True,
    )
    if par is None:
        raise HTTPException(status_code=404, detail="Par no encontrado")
    # 'invalidar' existe solo para la demo: con false se ve el dato viejo de la caché
    borradas = invalidar_cache(par["codigoRegistro"]) if invalidar else 0
    return {"_id": id, "codigoRegistro": par["codigoRegistro"],
            "estadoActual": nuevo_estado, "claves_borradas_en_redis": borradas}


@app.delete("/pares/{id}", tags=["1. CRUD pares (MongoDB)"])
def borrar_par(id: str):
    par = pares.find_one_and_delete({"_id": id_valido(id)})
    if par is None:
        raise HTTPException(status_code=404, detail="Par no encontrado")
    invalidar_cache(par["codigoRegistro"])
    return {"_id": id, "codigoRegistro": par["codigoRegistro"], "borrado": True}


# ---------------------------------------------------------------------------
# 5. Reporte con pipeline + caché en Redis (cache-aside)
# ---------------------------------------------------------------------------
PIPELINE_INGRESOS = [
    # $match: solo los pares entregados (ya cobrados)
    {"$match": {"estadoActual": "entregado"}},
    # $group: un documento por tipo de servicio con ingresos, cantidad y promedio
    {"$group": {
        "_id": "$tipoServicio",
        "ingresos": {"$sum": "$precio"},
        "pares": {"$sum": 1},
        "ticket_promedio": {"$avg": "$precio"},
    }},
    # $sort: el servicio que más dinero deja, primero
    {"$sort": {"ingresos": -1}},
    # $project: nombres claros y promedio sin decimales
    {"$project": {"_id": 0, "tipoServicio": "$_id", "ingresos": 1, "pares": 1,
                  "ticket_promedio": {"$round": ["$ticket_promedio", 0]}}},
]


@app.get("/reportes/ingresos-por-servicio", tags=["2. Reporte (Mongo + caché Redis)"])
def reporte_ingresos_por_servicio():
    """¿Qué tipo de servicio le deja más ingresos al emprendimiento?"""
    inicio = time.perf_counter()

    guardado = r.get(CLAVE_REPORTE)                         # 1. ¿Está en Redis?
    if guardado is not None:
        datos = json.loads(guardado)                        # 2a. Sí: responde Redis
        origen = "redis"
    else:
        datos = list(pares.aggregate(PIPELINE_INGRESOS))    # 2b. No: pipeline en Mongo
        r.set(CLAVE_REPORTE, json.dumps(datos, default=str), ex=TTL_REPORTE)  # 3. Guarda 2 min
        origen = "mongo"

    return {
        "origen": origen,
        "tiempo_ms": round((time.perf_counter() - inicio) * 1000, 2),
        "expira_en_segundos": r.ttl(CLAVE_REPORTE),
        "datos": datos,
    }


# ---------------------------------------------------------------------------
# 6. Seguimiento en vivo (caché) + contador y ranking de consultas (Redis)
# ---------------------------------------------------------------------------
def estado_desde_mongo(codigo: str):
    resultado = list(pares.aggregate([
        {"$match": {"codigoRegistro": codigo}},
        {"$project": {
            "_id": 0,
            "id_par": {"$toString": "$_id"},
            "cliente": "$cliente.nombre",
            "modelo": 1,
            "tipoServicio": 1,
            "estadoActual": 1,
            "ultimoEvento": {"$arrayElemAt": ["$eventos.nota", -1]},
        }},
    ]))
    if not resultado:
        return None
    return {"codigoRegistro": codigo, "cliente": resultado[0].pop("cliente"),
            "pares": [{k: v for k, v in p.items() if k != "cliente"} for p in resultado]}


@app.get("/registros/{codigo}/estado", tags=["3. Seguimiento en vivo y ranking (Redis)"])
def estado_en_vivo(codigo: str):
    """Pantalla del cliente: 'tu par está en secado'. Cuenta cada consulta."""
    inicio = time.perf_counter()
    clave = f"cache:estado:{codigo}"

    guardado = r.get(clave)
    if guardado is not None:
        datos, origen = json.loads(guardado), "redis"
    else:
        datos = estado_desde_mongo(codigo)
        if datos is None:
            raise HTTPException(status_code=404, detail=f"No existe el registro {codigo}")
        r.set(clave, json.dumps(datos, default=str), ex=TTL_ESTADO)
        origen = "mongo"

    consultas = r.incr(f"consultas:registro:{codigo}")          # contador
    r.zincrby("ranking:registros_consultados", 1, codigo)        # ranking

    return {
        "origen": origen,
        "tiempo_ms": round((time.perf_counter() - inicio) * 1000, 2),
        "expira_en_segundos": r.ttl(clave),
        "consultas_de_este_registro": consultas,
        "datos": datos,
    }


@app.get("/ranking/registros-consultados", tags=["3. Seguimiento en vivo y ranking (Redis)"])
def ranking_consultados(n: int = Query(5, ge=1, le=50)):
    top = r.zrevrange("ranking:registros_consultados", 0, n - 1, withscores=True)
    return [{"codigoRegistro": m, "consultas": int(p)} for m, p in top]


# ---------------------------------------------------------------------------
# 7. Dato temporal: código de retiro que vence en 5 minutos (Redis)
# ---------------------------------------------------------------------------
@app.post("/registros/{codigo}/codigo-retiro", tags=["4. Código de retiro temporal (Redis)"])
def generar_codigo_retiro(codigo: str):
    """La secretaria genera un PIN de 4 dígitos cuando el cliente viene a recoger."""
    if pares.count_documents({"codigoRegistro": codigo, "estadoActual": "listo_entrega"}) == 0:
        raise HTTPException(status_code=409,
                            detail=f"El registro {codigo} no tiene pares listos para entrega")
    clave = f"codigo_retiro:registro:{codigo}"
    pin = f"{random.randint(0, 9999):04d}"
    r.set(clave, pin, ex=TTL_CODIGO_RETIRO)
    return {"codigoRegistro": codigo, "codigo_retiro": pin, "expira_en_segundos": r.ttl(clave)}


@app.post("/registros/{codigo}/verificar-retiro", tags=["4. Código de retiro temporal (Redis)"])
def verificar_codigo_retiro(codigo: str, pin: str):
    clave = f"codigo_retiro:registro:{codigo}"
    guardado = r.get(clave)
    if guardado is None:
        return {"valido": False, "motivo": "No hay código o ya venció (5 minutos)"}
    if guardado != pin:
        return {"valido": False, "motivo": "Código incorrecto", "expira_en_segundos": r.ttl(clave)}
    r.delete(clave)  # un solo uso
    return {"valido": True, "mensaje": "Puede entregar los tenis"}

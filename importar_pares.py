"""Importa pares_nuevos_21.json en Atlas sin duplicar y verifica el total.

Uso:  python importar_pares.py
Lee MONGO_URL y MONGO_DB del archivo .env (igual que la API).
Se puede correr varias veces: solo inserta los _id que todavía no existen.
"""
import os
from pathlib import Path

from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
if not url:
    raise SystemExit("Falta MONGO_URL en el .env")

db = MongoClient(url, serverSelectionTimeoutMS=10000)[
    os.getenv("MONGO_DB") or os.getenv("MONGO_DB_NAME") or "limpieza_tenis"
]
col = db["pares_trazabilidad"]

docs = json_util.loads(Path("pares_nuevos_21.json").read_text(encoding="utf-8"))
print("Documentos antes:", col.count_documents({}))

existentes = {d["_id"] for d in col.find({"_id": {"$in": [d["_id"] for d in docs]}}, {"_id": 1})}
nuevos = [d for d in docs if d["_id"] not in existentes]
if nuevos:
    col.insert_many(nuevos)
print(f"Insertados: {len(nuevos)} | ya existían: {len(existentes)}")

total = col.count_documents({})
print("Documentos después:", total)
print("Registros distintos:", len(col.distinct("codigoRegistro")))
print("OK: hay 30" if total == 30 else f"OJO: se esperaban 30 y hay {total}")

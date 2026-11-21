# Tenis Clean · API con MongoDB y Redis (proyecto final)

Archivo de la API: `api_tenis_clean.py` · Base: `limpieza_tenis` · Colección: `pares_trazabilidad`

## 1. Cargar los 30 documentos en Atlas

`limpieza_tenis.pares_trazabilidad.json` trae los 9 pares originales + 21 nuevos (30 en total).

En Compass, conectados al clúster `tennisclean`:

1. Crear la base `limpieza_tenis` con la colección `pares_trazabilidad` (si no existe).
2. Si la colección está vacía: **Add Data → Import JSON** → `limpieza_tenis.pares_trazabilidad.json`.
3. Si ya tiene los 9 originales: importar solo `pares_nuevos_21.json`.
4. Comprobar en mongosh: `db.pares_trazabilidad.countDocuments()` → `30`.

## 2. Correr la API

```powershell
pip install -r requirements.txt
copy .env.example .env      # y poner en .env los valores reales
uvicorn api_tenis_clean:app --reload
```

Abrir http://127.0.0.1:8000/docs → `GET /ping` → `{"mongo_responde": true, "redis_responde": true}`

`.env` está en el `.gitignore`: las contraseñas no se suben. También se pueden poner con `$env:MONGO_URL = "..."` en la terminal.

## 3. Endpoints

| Grupo | Endpoint | Qué hace | Redis |
|---|---|---|---|
| Conexión | `GET /ping` | Prueba Mongo y Redis | `PING` |
| CRUD | `GET /pares?estadoActual=&tipoServicio=&limite=` | Lista con filtros y límite | — |
| CRUD | `GET /pares/{id}` | Un par (400 id inválido, 404 no existe) | — |
| CRUD | `POST /pares` | Crea un par validado con `ParNuevo` (422 si los datos están mal); arranca en `recibido` | `DEL` caché |
| CRUD | `PUT /pares/{id}` | Actualiza uno o varios campos (400 si no se envía nada) | `DEL` caché |
| CRUD | `PUT /pares/{id}/estado` | Cambia el estado (`$set`) y agrega el evento (`$push`) | `DEL` caché |
| CRUD | `DELETE /pares/{id}` | Borra un par | `DEL` caché |
| Reporte | `GET /reportes/ingresos-por-servicio` | Pipeline `$match → $group → $sort → $project`; responde `"origen": "mongo"` o `"redis"` | `GET` / `SET ... EX 120` |
| Redis | `GET /registros/{codigo}/estado` | Seguimiento en vivo (caché 60 s) + contador | `GET`/`SET EX 60`, `INCR`, `ZINCRBY` |
| Redis | `GET /ranking/registros-consultados` | Registros más consultados | `ZREVRANGE` |
| Redis | `POST /registros/{codigo}/codigo-retiro` | PIN de retiro que vence en 5 min | `SET ... EX 300` |
| Redis | `POST /registros/{codigo}/verificar-retiro` | Valida el PIN (un solo uso) | `GET`, `DEL` |

**Pregunta de negocio del reporte:** ¿qué tipo de servicio le deja más ingresos al emprendimiento? Solo cuenta los pares `entregado` (ya cobrados) y muestra ingresos, número de pares y ticket promedio por servicio.

**Dónde se invalida la caché:** función `invalidar_cache()`, llamada en `crear_par`, `actualizar_par`, `cambiar_estado` y `borrar_par`. Borra `cache:reporte:ingresos_por_servicio` y `cache:estado:{codigo}`.

## 4. Guion de la demo (3 minutos)

1. `GET /ping` → las dos bases en `true`.
2. `GET /reportes/ingresos-por-servicio` dos veces → `mongo` y luego `redis` (con menos `tiempo_ms`).
3. `POST /pares` con el ejemplo de Swagger → 201. Copiar el `_id`.
4. `PUT /pares/{id}/estado` con `entregado` → `claves_borradas_en_redis` mayor que 0.
5. `GET /reportes/ingresos-por-servicio` → vuelve a salir de `mongo` y premium sube.
6. `GET /pares/abc` → 400 · `DELETE /pares/{id}` dos veces → 200 y luego 404.
7. Si sobra tiempo: `GET /registros/REG-0021/estado` y `POST /registros/REG-0021/codigo-retiro` (REG-0021, REG-0023 y REG-0006 tienen pares en `listo_entrega`).

## 5. Comprobar en la consola de Redis

```
KEYS *
GET cache:reporte:ingresos_por_servicio
TTL cache:reporte:ingresos_por_servicio
ZREVRANGE ranking:registros_consultados 0 4 WITHSCORES
TTL codigo_retiro:registro:REG-0021
```

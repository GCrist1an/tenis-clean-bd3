# Limpieza de Tenis — Gestión Integral de Servicios y Trazabilidad para la Restauración de Calzado

**Emprendimiento pereirano**

## 📌 Descripción

Sistema de gestión de servicios de limpieza y restauración de tenis que maneja pedidos, códigos de registro, historial fotográfico y estados del proceso, para el equipo operativo de un emprendimiento en Pereira.

El sistema está pensado para apoyar a:

- Administrador
- Encargado de restauración
- Secretaria

## 👥 Integrantes

- Cristian Gutiérrez
- Víctor Manuel Parra
- Jonh Jawy Perdomo Grizales
- Johan Quintero
- Kevin Velásquez Pino

**Fecha:** 22/09/2026

## 🧾 Caso real

El emprendimiento atiende a los clientes por orden de llegada. Cada número de registro puede cubrir varios pares que un mismo cliente entregue.

Ofrece tres tipos de servicio:

- Limpieza completa
- Servicio premium
- Limpieza express, con promesa de entrega en 48 horas

El proceso completo toma hasta 7 días entre recogida, restauración y entrega. La recogida a domicilio es opcional. El pago se realiza en efectivo o transferencia al momento de la entrega, que puede hacerse a domicilio con un costo adicional variable según la zona de la ciudad.

Para los servicios de restauración incluidos en el servicio premium, se maneja un control básico de insumos:

- Productos de limpieza
- Pintura para calzado
- Pegamento/resina
- Materiales para restauración de suelas

Cada pedido se formaliza como una **Orden de Trabajo (OT)**, que vincula:

- Actividades solicitadas: limpieza, arreglos, arreglo y limpieza, limpieza profunda, limpieza exprés, entre otras.
- Fecha de inicio y fecha de entrega comprometida.
- PDF con la descripción del trabajo a realizar.
- Ubicación o dirección del cliente.

Adicionalmente, el sistema debe llevar un control contable básico de entradas y salidas de dinero: pagos recibidos de clientes y gastos en insumos, separado del seguimiento operativo del proceso.

## 🎯 Objetivo del proyecto

Diseñar e implementar una solución de base de datos que permita gestionar de forma integral los servicios de limpieza y restauración de tenis, garantizando:

- Trazabilidad del proceso de restauración.
- Seguimiento en vivo del estado de cada par.
- Consistencia en el manejo de pagos y facturación.
- Control básico de insumos.
- Registro fotográfico y eventos por pedido.

## 🗄️ Motores de base de datos evaluados

**Parte del sistema elegida:** trazabilidad y seguimiento del estado del proceso de restauración:

> recibido → diagnóstico → limpieza → secado → control de calidad → listo para entrega

Incluyendo fotos y eventos de cada par.

| Criterio | MongoDB (documental) | Redis (clave-valor) | PostgreSQL (relacional) |
|---|---|---|---|
| Consistencia | Media — eventual; aceptable porque un estado desactualizado por segundos no afecta el servicio. | Baja — pensado para datos volátiles/temporales, no es la fuente de verdad permanente. | Alta — garantiza que el estado mostrado al cliente sea siempre el oficial y auditable. |
| Latencia | Media — suficiente para consultas de historial, no crítica segundo a segundo. | Baja — ideal para el estado "en vivo" que el cliente consulta constantemente en la app. | Media-alta — los JOINs entre pedido, cliente y eventos añaden algo de costo. |
| Escalabilidad | Alta — soporta el crecimiento de fotos y eventos variables por pedido sin rediseñar el esquema. | Alta en velocidad, pero limitada por la RAM disponible; no pensado para guardar historial completo. | Media — escala bien hasta cierto volumen; luego exige particionamiento. |
| Costo operativo | Medio — un solo motor cubre catálogo y trazabilidad, reduce infraestructura. | Bajo — motor liviano, pero no reemplaza una base persistente. | Medio — gratuito y conocido, pero exige modelar tablas para datos que varían mucho (fotos, eventos). |
| Flexibilidad de esquema | Alta — cada documento puede tener distintos campos/eventos sin migrar tablas. | Baja — solo pares clave-valor, no modela estructuras variables. | Baja — un cambio en los campos exige alterar tablas. |

## ✅ Justificación final

### Motor 1 — MongoDB (elegido para la trazabilidad)

Para la trazabilidad del proceso de restauración elegimos **MongoDB** porque la variedad de eventos y evidencia fotográfica por pedido es alta y cambia según el tipo de servicio. Un lavado básico no genera los mismos pasos que una restauración de suela. Esto se evidencia en que un pedido simple registra aproximadamente 3 eventos y uno completo supera los 8.

### Motor 2 — Redis (complemento para el estado en vivo)

Para la pantalla que el cliente consulta en tiempo real, por ejemplo: *"tu par está en secado"*, usamos **Redis** como caché porque la latencia debe ser mínima cada vez que se refresca. No se usa como fuente de verdad porque no está pensado para conservar el historial completo.

### Motor 3 — PostgreSQL (para pagos y facturación)

Los pagos y la facturación del servicio quedan en **PostgreSQL** dentro de la arquitectura general, porque allí la consistencia es innegociable: involucra dinero real de los clientes.

## 🏗️ Arquitectura inicial

El sistema contempla 3 pantallas principales y la base de datos que cada una consulta:

| Pantalla | Base de datos | Función |
|---|---|---|
| Recepción de pedido | MongoDB | Registra cliente, par de tenis y servicio solicitado; los atributos varían según el tipo de calzado y servicio. |
| Seguimiento en vivo | Redis | Muestra el estado actual (recibido / lavado / secado / listo) con la latencia mínima que la experiencia del cliente necesita. |
| Pagos y facturación | PostgreSQL | Registra cobros, facturas y el control de entradas y salidas de dinero, donde la consistencia y el respaldo transaccional no son negociables. |

```mermaid
flowchart LR
    A[Pantalla de recepción de pedido] --> B[(MongoDB)]
    C[Pantalla de seguimiento en vivo] --> D[(Redis)]
    E[Pantalla de pagos y facturación] --> F[(PostgreSQL)]

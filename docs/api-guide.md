# Guía de API — Fases 0–12

Versión de aplicación 0.1.0; prefijo /api/v1. Contrato reproducible:
[openapi.json](openapi.json), [inventario](api-inventory.md).
155 operaciones OpenAPI en 114 paths; inventario de 157 operaciones incluye
GET / y GET /health legacy fuera del schema. 140 operaciones Bearer.
Docs locales: http://localhost:8000/docs. Disponibilidad HTTP no certifica DB.

## Autenticación y errores

Authorization: Bearer <access token> para rutas protegidas. Tokens de refresh y
verificación de teléfono solo sirven para sus operaciones específicas.
Identidad Guest no es rol administrativo ni cuenta registrada; favorites requiere
REGISTERED. Roles/permisos vienen de DB, no del body/query/claims del cliente.

403 corresponde a scope/permiso o cuenta bloqueada; 404 oculta recursos ajenos;
409 indica conflicto de estado/idempotencia; 422 datos inválidos sin eco de input;
503 dependencia ausente (DB/proveedor). 500 es genérico, sin SQL/DSN/traceback.
Errores conservan el envelope error.code/error.message. No imprimir tokens.
X-Request-ID identifica la petición; no sustituye identidad o idempotencia.

## Flujo cliente

1. OTP request/verify → guest o register/login según la identidad.
2. Branches y Catalog menu/product son públicos; branch_id selecciona contexto.
3. Crear cart ACTIVE por Customer + branch; añadir presentación/opciones/qty/notas.
4. GET lee snapshots; recalcular revalida Catalog explícitamente. Cliente no manda precios.
5. POST /api/v1/orders con Idempotency-Key crea histórico y consume cart atómicamente.
6. LOCAL usa mesa/QR y permite CASH según configuración; PICKUP horario y ONLINE;
   DELIVERY dirección propia/cobertura/tarifa y ONLINE.
7. Consultar orden/pago/notificaciones propios. Review solo al finalizar; receipt
   requiere coherencia con ledger. Favorites es por User; ruleta gratuita por Customer.

No replicar la máquina de estados en frontend como autoridad. Datos de catálogo
cambiados no reescriben el histórico. Total y descuentos/cargos vienen del servidor.

## Idempotencia

Headers Idempotency-Key obligatorios donde el contrato los declara: checkout,
iniciar pago online, procesar refund online, fiscal process y roulette spins.
Formato permitido de clave: caracteres alfanuméricos/punto/guion/underscore/dos
puntos y longitud 1..128; scope/fingerprint según caso de uso.
Misma clave/cuerpo devuelve el resultado persistido; misma clave con otro request
no autoriza una segunda operación. No exponer claves/hashes privados en logs.
Callbacks solo se aceptan después de verificación del adaptador; no confiar en
JSON paid=true ni crear rutas de confirmación online manual.

## Operación administrativa

Las familias admin requieren REGISTERED activo, asignación ADMIN vigente,
permiso específico y branch scope en DB. Permisos, estados y ownership se
comprueban antes de modificar. Kitchen tiene proyección operativa separada.
Véase la [matriz](security-review.md), no usar un flag frontend como autorización.

La corrección puntual F12 agrega:

```text
POST /api/v1/admin/orders/branches/{branch_id}/orders/{order_id}/serve-local
Authorization: Bearer <access token de Admin autorizado>
Body: ausente o {}
```

Exige ORDER_MANAGE, modalidad LOCAL confirmada y estado READY; pasa a SERVED.
Reintentar SERVED no duplica historia/audit. Rechaza body con status/price/actor.
No cobra, no reembolsa y no confirma PAID: CASH LOCAL conserva la política
existente; ONLINE exige PAID. Foreign branch/ID no puede cerrar una orden.

## SSE / CORS

Rutas stream y snapshots exactas están en el inventario (familias realtime).
Content-Type: text/event-stream. Usar cliente fetch/stream que permita header
Authorization; EventSource nativo no envía un header Bearer configurable.
No pasar token por query como workaround. Last-Event-ID o cursor permitido
sirve para reconectar; cursores son opacos por scope, no identidad.

ready inicial, eventos tipados, heartbeat y cursor id; batch100/poll1s/
heartbeat15s/revalidación15s/lifetime300s. Al desconectar, expirar o revocar
scope se cierra. No hay sesión DB abierta esperando ni datos sensibles Kitchen.
Reconectar al cierre con backoff cliente; evitar buffering proxy.
CORS permite origins explícitos configurados, Authorization/Idempotency-Key/
Last-Event-ID/X-Request-ID y expone X-Request-ID. No wildcard.

## Público y proveedores

La allowlist pública exacta está en scripts/contracts.py: health/root,
OTP/register/guest/login/refresh/logout, branches y Catalog público.
Refresh/logout/proof siguen requiriendo sus datos de prueba, aunque no access Bearer.
Los dos webhooks payment/refund son entradas externas verificadas y fail-closed.
Sin provider productivo: ONLINE/refund/fiscal/push no se simulan como éxito.
Sender OTP en staging/production y workers/scheduler siguen pendientes.

## Salud y mantenimiento del contrato

Liveness no toca DB; readiness solo SELECT 1 con timeout, no valida migrations.
Generar/check sin conectar ni arrancar lifespan:

```bash
python scripts/export_openapi.py
python scripts/export_openapi.py --check
python scripts/release_check.py
```

Si cambia una ruta/schema, revisar compatibilidad y regenerar ambos artefactos.
No editar JSON/inventario a mano ni modificar reglas de negocio para satisfacer
una aserción de Swagger antigua. El guard detecta routes/operation IDs duplicados,
Bearer/admin sin protección, public no declarado y segmentos backdoor.
La factory app/factory.py no inicializa app global al importarse; app.main conserva
el entrypoint y el alias create_app. El export proporciona defaults explícitos
de todos los campos, sin leer .env/deployment env ni crear conexión.

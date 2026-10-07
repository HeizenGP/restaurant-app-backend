# Fase 9 — Notifications & Realtime

Fecha: 2026-10-07. Implementación y límites de verificación.

## 1. Resumen ejecutivo

Fase 9 implementada en `chore/backend-foundation`, partiendo de
`87ec588` (F8). Prevalece la instrucción directa de misma rama sobre
`feat/notifications` del documento adjunto.

In-app: IMPLEMENTADO. SSE: IMPLEMENTADO. Push orchestration: IMPLEMENTADA.
Entrega móvil real: PENDIENTE DE PROVEEDOR. Worker externo: PENDIENTE DE DESPLIEGUE.
Migración preparada/validada offline; NO aplicada a la base normal incompatible.
No staging, commit, push ni avance a Fase 10.

## 2. Alcance

Notificaciones del cliente, read/unread, dispositivos, outbox/reintentos,
eventos durables por sucursal y tres streams SSE. No se escribe un frontend,
no se construye una nueva cola de cocina y no se redefine el estado financiero.

Archivos creados: 24 Python en `app/modules/notifications/` (incluidos seis
`__init__.py`), nueve Python en `tests/modules/notifications/`,
`migrations/versions/0009_create_notifications.py`,
`tests/test_phase9_migration.py`, `tests/integration/test_phase9_postgresql.py`
y este informe: 37 archivos nuevos.

Modificados: `README.md`, `app/presentation/api/v1/router.py`,
`migrations/env.py`, `tests/test_phase1_migration.py`,
`tests/test_phase8_migration.py`, `tests/modules/kitchen/test_api.py`.
Los tests anteriores conservan sus invariantes históricas y reconocen F9;
ningún servicio de negocio ni migración 0001–0008 fue modificado.

Inventario del slice:

- domain: `models.py`, `content.py`.
- application: `dtos.py`, `errors.py`, `ports.py`, `services.py`,
  `push.py`, `realtime.py`.
- infrastructure: `authorization.py`, `push_gateway.py`, `realtime.py`;
  persistence: `models.py`, `repositories.py`, `push.py`.
- presentation: `dependencies.py`, `schemas.py`, `router.py`, `sse.py`.
- tests: `fakes.py`, `conftest.py`, `test_domain.py`, `test_services.py`,
  `test_api.py`, `test_push.py`, `test_sse.py`, `test_repositories.py`.

## 3. RF cubiertos

RF-53: siete notificaciones según modalidad; RF-54: señales realtime
administrativas/cocina; RF-26: READY_FOR_PICKUP separado de READY.
La lista de órdenes, cocina, pagos, incidentes y cancelaciones existentes
siguen siendo las fuentes del negocio.

## 4. Arquitectura

Vertical slice hexagonal: Presentation usa Application y Domain;
Infrastructure implementa NotificationRepository, NotificationAuthorization,
PushRepository, PushGatewayRegistry, PushGateway y StreamReader.
Domain/Application no importan FastAPI, ORM ni infraestructura.
Las dependencias públicas Auth/Branches/Orders se reutilizan sin APIs privadas.
No NotificationService dentro de Orders/Payments/Kitchen/Fulfillment/Cancellations.

## 5. Eventos vs notifications

RealtimeOrderEvent señala creación/cambio de estado o pago/retraso.
CustomerNotification es un hecho dirigido a un Customer específico.
PushDelivery es un intento de transporte de ese hecho a un dispositivo.
No son otra máquina de estados de Orders ni un nuevo ledger de pagos.

## 6. realtime_order_events

BIGINT GENERATED ALWAYS AS IDENTITY; branch/order FK RESTRICT,
número histórico, mode, type, status/payment_status, flags, referencia opcional,
occurred_at TZ. Append-only; lectura branch + id > cursor, ASC.
Tipos: ORDER_CREATED, ORDER_CHANGED, DELIVERY_DELAYED; wire:
order.created, order.changed, delivery.delayed. Cambiar solo updated_at o repetir
status/payment_status no genera ORDER_CHANGED.

## 7. customer_notifications

UUID id y sequence_id BIGINT ALWAYS único. Customer/Order/Branch RESTRICT.
Kind, número/status históricos, source_kind/source_id, created_at/read_at TZ.
Dedupe UNIQUE(source_kind, source_id, kind): identidad concreta de Order,
StatusHistory o DelayIncident, nunca búsqueda del último historial.
Inmutabilidad excepto primer read_at; DELETE protegido. Sin backfill.

## 8. Device registry

UUID de instalación único, ANDROID/IOS, proveedor canónico, token opaco
UTF-8 de 1..2048 bytes sin whitespace/control, UNIQUE(provider_code,push_token).
PUT crea/actualiza 200 sin duplicar instalación; DELETE lógico 204.
last_seen_at y updated_at; token sin repr/respuestas/logging.
No device nuevo recibe notificaciones push anteriores a su registro.

## 9. Push deliveries

UUID; UNIQUE(notification_id,device_id); provider y device_generation;
PENDING/PROCESSING/SENT/FAILED/CANCELLED, attempt_count 0..5,
next_attempt_at, locked_until, claim_token, provider_message_id seguro opcional,
failure_code constante, sent_at iff SENT y timestamps TZ.
Outbox se encola por dispositivos activos del propietario durante el evento.

## 10. PushGateway

Puerto asíncrono send(PushMessage) -> PushResult:
SENT, INVALID_TOKEN, RETRYABLE_FAILURE, PERMANENT_FAILURE.
El mensaje comparte título/body con in-app, tiene notification/delivery IDs,
token no representable, datos mínimos order_id/number/kind/status y clave estable
`push-delivery:<delivery UUID>`. Sin payloads crudos del proveedor.
Registry anuncia únicamente adapters realmente suministrados por composición.

## 11. Provider real configurado o pendiente

Producción usa ConfiguredPushGatewayRegistry vacío. UnconfiguredPushGateway
devuelve 503, jamás SENT ficticio. Registrar un proveedor no soportado o ejecutar
dispatcher sin providers devuelve PUSH_PROVIDER_UNAVAILABLE antes de escrituras,
claims o incremento de intentos. TestGateway vive únicamente en tests.

## 12. ORDER_RECEIVED

Order INSERT de cualquier modalidad: source ORDER, source_id=Order.id,
timestamp Order.created_at. Recibido no significa pagado, confirmado ni visible
en cocina. Retry de checkout que devuelve Order existente no repite INSERT.

## 13. ORDER_PREPARING

Historial con from_status no nulo/distinto y to_status=PREPARING,
LOCAL/PICKUP/DELIVERY. Source ORDER_STATUS_HISTORY y ese History.id.
No se notifica un historial inicial con from_status NULL.

## 14. ORDER_READY

Historial hacia READY solamente LOCAL o DELIVERY. Un Order PICKUP no
recibe ORDER_READY. No reemplaza ni cambia Kitchen.mark_ready.

## 15. ORDER_READY_FOR_PICKUP

Historial hacia READY_FOR_PICKUP solamente PICKUP, texto explícito de
recojo RF-26. PICKED_UP posterior no genera una notificación adicional.

## 16. ORDER_OUT_FOR_DELIVERY

Historial hacia OUT_FOR_DELIVERY solamente DELIVERY. La asignación y
validación de despacho siguen perteneciendo a Fulfillment/Orders.

## 17. ORDER_DELIVERED

Historial hacia DELIVERED solamente DELIVERY. No se notifica SERVED
o PICKED_UP bajo RF-53 y no se inventa una entrega desde un pago.

## 18. DELIVERY_DELAYED

AFTER INSERT de DeliveryDelayIncident existente: source del incidente,
ID/timestamp detected_at exactos; evento realtime y notificación atomizados.
Comprueba Order DELIVERY y branch coincidente. No recalcula ETA/umbral,
no consulta reloj para decidir retraso y no genera avisos por lectura/evaluación.

## 19. Notification content

Una función Domain `content(kind,order_number_snapshot)` produce títulos/
mensajes españoles idénticos para in-app y PushMessage. No Catalog, nombre,
dirección, teléfono, montos, tokens ni texto arbitrario en el contenido.

| Kind | Título |
| --- | --- |
| ORDER_RECEIVED | Pedido recibido |
| ORDER_PREPARING | Pedido en preparación |
| ORDER_READY | Pedido listo |
| ORDER_READY_FOR_PICKUP | Pedido listo para recojo |
| ORDER_OUT_FOR_DELIVERY | Pedido en camino |
| ORDER_DELIVERED | Pedido entregado |
| DELIVERY_DELAYED | Tu delivery presenta un retraso |

Todos los bodies incluyen el número histórico #123, no un precio actual.

## 20. In-app API

Prefijo /api/v1, 11 operaciones y 10 paths nuevos, todos con Bearer.

| Método | Ruta sin prefijo | Permiso |
| --- | --- | --- |
| GET | /notifications | Customer propietario |
| GET | /notifications/unread-count | Customer propietario |
| POST | /notifications/{notification_id}/read | Customer propietario |
| POST | /notifications/read-all | Customer propietario |
| GET | /notifications/stream | Customer propietario |
| PUT/DELETE | /notifications/devices/{installation_id} | Customer + reglas de handoff |
| GET | /admin/realtime/branches/{branch_id}/orders | ORDER_REALTIME_VIEW |
| GET | /admin/realtime/branches/{branch_id}/orders/events | ORDER_REALTIME_VIEW |
| GET | /admin/realtime/branches/{branch_id}/orders/stream | ORDER_REALTIME_VIEW |
| GET | /kitchen/branches/{branch_id}/orders/stream | KITCHEN_VIEW |

Lista descending: limit default50/max100, before_sequence_id opcional.
Devuelve items/latest_sequence_id/next_before_sequence_id.
Respuesta incluye notification ID, sequence_id, order/branch, kind, número/status,
title/body, created_at/read_at/is_read; no customer/source IDs ni token.
Bodies/query extra_forbid; read admite body ausente o {}.
Swagger documenta text/event-stream, seguridad y error envelope.

## 21. Read/unread

COUNT SQL únicamente del Customer; mark-read UPDATE por customer+ID+read NULL,
fallback scoped idempotente; marca greatest(utc_now,created_at) una sola vez.
read-all es un UPDATE de filas propias no leídas, devuelve marked_count,
sin cargar todos los rows. No afecta Orders, historial, finanzas ni push pendiente.

## 22. Guest support

CurrentCustomer obtiene identidad invitada de un JWT válido y del repositorio
Auth actual. Ningún customer_id del body/query determina ownership.
Los invitados tienen API in-app, SSE y dispositivos sin inventar un User.

## 23. Registered support

El mismo Customer conserva historia al promoverse a User registrado.
Principal, token y estado vigente se resuelven por Auth, no por roles del JWT.
Un registered sin Customer no puede usar endpoints del cliente.
Admin/Kitchen requieren CurrentRegisteredUser además del permiso en DB.

## 24. Device privacy

Device se bloquea antes de deliveries. Reasignación, rotación o reactivación
cancela PENDING/PROCESSING viejos y aumenta generation en la misma transacción.
Device.send_locked_until protege el handoff durante llamadas externas:
cambio significativo con lease activo ->409 NOTIFICATION_DEVICE_BUSY.
PUT idéntico puede renovar last_seen_at; DELETE invalida generación y cancela,
pero conserva la barrera. Worker viejo no finaliza ni invalida token nuevo.

Campos adicionales justificados: Device.generation/send_locked_until y
Delivery.device_generation/claim_token; evitan TOCTOU y finalización tardía.
No garantizan retirar un push ya aceptado/encolado por un proveedor externo.
El adapter futuro debe respetar timeout/cancelación; después de expiración del
lease y frente a un proveedor lento se requiere dedupe/validación del cliente.
Rotación misma cuenta cancela old-generation no enviado por elección conservadora;
in-app nunca se pierde. El registro real está deshabilitado sin proveedor.

## 25. Push retries

Dispatcher default50/max100; paralelismo10 (máximo20).
Reserva PROCESSING, aumenta count y commit antes de llamar al proveedor.
Timeout de aplicación 30 s, configurable >0 y <=60 s (mitad del lease120).
Reintentos a los 30/120/600/1800 s tras intentos1..4; quinto fallo es FAILED.
La función de política define también 3600 s para count5, pero no hay sexto claim.
Lease expirado recuperable; un quinto PROCESSING expirado termina FAILED sin HTTP.

## 26. Invalid tokens

INVALID_TOKEN -> FAILED con código seguro, device inactive/generation+1 y
cancelación de restantes no enviados, solo si claim actual/lease vigente.
Conserva send_locked_until porque cancelar leases no cancela mágicamente HTTP
de otros envíos en vuelo. Un resultado viejo jamás desactiva un token reactivado.

## 27. Push concurrency

Dos consultas batched de claim: Device candidatas con EXISTS due,
FOR UPDATE SKIP LOCKED; luego deliveries+notifications FOR UPDATE OF delivery
SKIP LOCKED. Orden Device -> Delivery uniforme en registro/claim/completion.
Claim_token + generation + propietario + active + lease vigente se revalidan
antes del envío y al completar. Sessions cortas y cerradas antes de send.
Clave externa estable permite dedupe; no se promete exactamente una vez externa.
Un claim enviado antes de crash puede necesitar retry aunque proveedor lo aceptó.

## 28. Admin realtime

Nuevo ORDER_REALTIME_VIEW otorgado solo al ADMIN de scope BRANCH existente.
GET snapshot minimal proyecta Order ID/number/mode/status/payment_status,
customer_name_snapshot, created_at/confirmed_at/updated_at, sin items/phones/
addresses/customer ID/provider keys. Default ocho estados activos; terminales
solo por status explícito. limit100/max200, after_order_number.
Cursor latest_event_id consultado ANTES del snapshot, nunca después.
Events after_id default0, limit100/max200, branch+id ASC.

## 29. Kitchen realtime

KITCHEN_VIEW existente, sucursal actual; no KitchenManage ni nuevas acciones.
Queue/rest existentes siguen intactos. Stream avisa cualquier cambio de Order
de la sucursal y Kitchen refresca la cola para decidir visibilidad real.
Ruta estática stream se registra antes de {order_id}, evitando captura como UUID.
Test histórico conserva las cuatro operaciones existentes y prueba stream GET-only.

## 30. Customer notification stream

Solo customer_notifications del Customer vigente, IDs sequence_id.
Tipo notification.created y response seguro con contenido compartido.
No emite branch events ni historia ajena, no crea notificaciones al conectar.
Flutter obtiene lista/unread, abre SSE desde latest_sequence_id, deduplica IDs
y refresca lista/unread ante eventos. El SDK móvil/proveedor aún no se integró.

## 31. SSE design

StreamingResponse text/event-stream; Cache-Control no-cache,no-transform,
X-Accel-Buffering no. ready, eventos y comentarios keep-alive.
Poll1s, lote100 drenado inmediatamente si completo; sesiones nuevas por poll,
cerradas antes del yield/sleep. La sesión request de Auth se libera antes del stream.
Revalidación cada15s y entre filas si consumidor suspendió un batch; expiry JWT
se verifica en cada fila/poll. Máximo300s y Request.is_disconnected.
CancelledError se propaga; error tras headers cierra con comentario constante,
nunca JSON tardío ni error DB/proveedor crudo.

## 32. Cursor

BIGINT>=0 <=9223372036854775807, independiente del UUID de la notificación.
MAX scoped comprometido antes de datos, batches limitados por ese watermark.
Gaps de secuencia son normales; el cliente compara > cursor, no espera ID+1.

Identity allocation NO implica commit-order. Toda captura adquiere advisory
transaction lock907009001 ANTES de asignar event ID/notification sequence y
lo mantiene hasta commit/rollback. Un commit tardío no aparece detrás del cursor
ya consumido. Serialización global MVP es un coste explícito, no escalabilidad
ilimitada. Writes manuales privilegiados que omitan captura no son un API válido.
[PostgreSQL isolation/sequences](https://www.postgresql.org/docs/current/transaction-iso.html)
y [transaction advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html).

## 33. Last-Event-ID

Header ASCII decimal validado; after_id query explícito prevalece incluso
si el header no se usa. Header ausente y after_id ausente -> inicio desde MAX
autorizado; after_id=0 -> replay autorizado completo/batched.
Cursor por encima del MAX de ese ámbito ->422 antes de headers.
ready conserva el cursor pedido, no lo salta al último antes de transmitir replay.
[Protocolo SSE del estándar HTML](https://html.spec.whatwg.org/multipage/server-sent-events.html).

## 34. Reconnection

REST=estado, SSE=señal. Admin: snapshot con watermark, abrir stream desde ese
watermark, deduplicar por ID y refetch ante change. Customer: usar latest_sequence_id
de la lista. Kitchen: abrir sin cursor y refrescar queue después del ready;
resync_required=true cierra la ventana inicial, sin endpoint queue duplicado.
Cliente sin cursor refresca estado después de ready; con cursor no se le obliga
a reproducir millones de rows antiguos. Ante cierre/expiry obtener JWT válido y
reconectar usando último ID procesado; al perder cursor refrescar snapshot.
Sin purga/retención automática en esta fase; futuros gaps por purga necesitarán
protocolo explícito de resync. SDK EventSource nativo no admite Bearer custom:
usar cliente SSE fetch autenticado/Flutter compatible, jamás JWT en URL.

## 35. Heartbeats

Comentario `: keep-alive\n\n` cada15s mientras la conexión puede consumir.
No crea cursor ni notification; no abre una transacción durante el sleep.
Con proxy buffering desactivado, dimensionar timeouts proxy mayores que heartbeat.
Límite300s obliga renovación periódica y reduce retención de credenciales.

## 36. Security

Auth real reutilizada. Sin hardcoded current principals, grants desde JWT,
nuevos tipos JWT ni superadmin. Branches valida user ACTIVE/no deleted,
staff activo/vigente, branch activa, role BRANCH y permiso.
No access_token query. Inputs/queries forbid-extra, límites/cursors y UUIDs.
Errores 401/403/404/409/422/503 seguros; tokens sin repr, sin echo de inputs.
Sin provider tokens/idempotency keys/finanzas privadas en SSE.

## 37. Branch isolation

Cada snapshot, events, watermark y poll de staff se filtra por branch.
Cada SSE revalida staff/permiso de esa branch. No existe global realtime stream.
Kitchen de A, aunque tenga JWT válido, no ve B ni tiene ORDER_REALTIME_VIEW.
Admin no recibe superadmin por tener rol ADMIN en otra sucursal.

## 38. IDOR

mark-read/unregister filtran ownership antes del ID. Missing y foreign ->404
indistinguible. read-all/list/count/customer stream solo identidad Auth vigente.
Rebind global de instalación es una operación explícita y atómica con
cancelación/generation/lease, no un GET global de dispositivos ni tokens.

## 39. Database triggers

Nueve triggers: Order INSERT y UPDATE status/payment_status, History INSERT,
DelayIncident INSERT, Notification INSERT enqueue, protección de los dos hechos,
updated_at compartido para Device/Delivery. Siete funciones propias:
cursor_gate, notification, order_event, history_notification, delay_notification,
enqueue_push, protect_fact. Sin HTTP, backfill, nuevos orders/payments/histories
ni redefinición de funciones antiguas. Ambos timestamps updated_at reutilizan F1.

## 40. Atomicity

Order/status/payment o incidente, realtime fact, customer notification y outbox
comparten la transacción del productor; fallo en captura aborta todo.
Provider se ejecuta SOLO después de claim commit; completion es otra transacción
fenced, no un HTTP en trigger ni una saga agregada a Orders.
Dedupe repetido verifica todos los snapshots; un source conflict corrupto falla,
no queda silenciado por ON CONFLICT genérico.

## 41. Migration 0009

Revision0009_notifications -> down_revision0008_cancellations_refunds.
Cuatro tablas propias, sin ALTER/DROP de negocio ni reescritura0001–0008.
50 tablas app/51 con alembic_version. Head único, lineal.
Downgrade primero rechaza cualquier fila en cualquiera de las cuatro tablas;
solo si vacías borra sus triggers/functions/tables/grant/permission, no F1/F8.
NO migrar/stamp/reconciliar la base normal manual sin plan de adopción.
No create_all ni migration runner en startup/lifespan/Docker.

## 42. Constraints

PK/identity positivas; checks enums, source_kind por kind, read_at>=created_at,
token byte bounds/formato/provider, generation positiva, delivery count0..5,
PROCESSING iff locked_until+claim_token, SENT iff sent_at, identifiers/failure safe.
Unique source/kind, notification sequence, installation, provider/token,
notification/device; ocho FK propios RESTRICT.
Append-only/first-read se protegen también en PostgreSQL, no solo servicios.

## 43. Indexes

Nueve explícitos: realtime branch/id y order/id; notification customer/sequence
DESC, customer/read_at y order/created_at; device customer/is_active; delivery
status/next_attempt/id WHERE PENDING, locked_until/id WHERE PROCESSING,
device/status. Uniques/PK generan sus índices implícitos adicionales.
Queries principales están scoped/cursorizadas/batched, sin OFFSET para F9;
claim limita volumen; sin cargar toda la historia para unread.

## 44. Tests Domain

Matriz de tres modalidades × doce estados; history inicial/repetido ignorado;
contenido compartido y snapshot numbers, cursores BIGINT, provider/token byte
limits/control, proveniencia, inmutabilidad, tiempos TZ, delivery/lease/count y retry.
No frameworks ni SDK en reglas puras.

## 45. Tests Services

Ownership guest/registered, lista/cursor, unread/first-read/all-read idempotentes,
rollback commit fallido, registrar/rotar/rebind/reactivar/delete, no retroactivo,
busy-lease, no provider antes de writes, read no cancela push, permisos exactos.
Fakes son adaptadores de tests, no evidencia de carreras PostgreSQL.

## 46. Tests API

Bearer/JWT real y AuthService con repositorio test-only, no override del current
principal. In-app/read/unread, IDOR/forged fields, token redaction, límites,
guest/registered, dispositivos, admin scope/snapshot projection, SSE routes/auth,
Last-Event-ID/precedencia/future cursor y OpenAPI11 operaciones/10 paths.
Test F5 conserva permisos de mutación y añade el reconocimiento explícito SSE.

## 47. Tests SSE

Replay ASC, gaps, MAX scoped/no global, ready cursor sin salto, >100 rows sin
sleep entre batches, heartbeat15s, revalidación/permission revocation entre filas,
expiry exacto, máximo300s, disconnect, CancelledError, tipos mínimos y no URL JWT.
Reader SQL cierra la sesión antes de devolver; route libera sesión de Auth.
Test HTTP usa reloj/límite corto inyectado, no modifica defaults productivos.

## 48. Tests Push

Sin gateway no claim, SENT fuera de transacción y contenido seguro,
repetición no reenvía SENT, retry/backoff5máximo, token inválido, permanente,
lease crash/expiry/claim_token viejo, delete antes de send, concurrencia en memoria,
adapter inesperado/clave estable, timeout cancelable y validación timeout <=60s.
SQL compilado confirma lock order, SKIP LOCKED batched y fence/lease de privacidad.
Fake gateway únicamente en tests; no entrega móvil real ejecutada.

## 49. Tests Migration

9 passed: head/chain/metadata50, cuatro tablas/nueve índices/identities,
constraints/FKs/timezones comparados contra metadata, siete funciones/nueve triggers,
RF-53 exacto, gate antes de IDs, conflicto histórico, no backfill/foreign writes,
permisos ADMIN, append-only/read-once y downgrade guard anterior a todo DDL.
La comprobación offline no certifica ejecutar PL/pgSQL en un servidor real.

## 50. PostgreSQL integration

Dos tests F9 opt-in con guarded_test_url: nombre TEST explícito,
vacío y distinto de normal. El primero migra1..9 en outer transaction,
51 tablas, captures7 kinds/outbox/read/rollback/protection/downgrade y revierte DDL.
El segundo necesita commits visibles entre conexiones: crea schema
phase9_test_<UUID32hex> exclusivamente en TEST vacío, migra schema real, verifica
pg_backend_pid distinto, gate bloqueando commitB antes de A, replay sin gaps,
SKIP LOCKED/lease, unregister/rebind/old-result y envío sin checked-out sessions.
Cleanup verifica schema exacto/owner, borra solo ese schema y extensiones
citext/pgcrypto únicamente si instaladas por su setup, sin CASCADE de extensión.
No instala DB/Docker. Ambos OMITIDOS en este entorno; no se afirma prueba real.

## 51. Ruff

Resultado final:
`ruff check .` -> All checks passed!
`ruff format --check .` -> 388 files already formatted.
No dependencias nuevas ni cambios en requirements/pyproject.

## 52. Pytest

Baseline previo:1714 passed,8 skipped.
F9 focal actual:252 passed; migration:9 passed.
Primera regresión detectó un test F5 que contaba4 paths; se corrigió preservando
el set exacto de4 históricos y stream GET-only.
Suite completa final: `1975 passed, 10 skipped in 304.69s (0:05:04)`.
Focal final: `252 passed in 24.88s`; migración: `9 passed`.
`pytest -m integration -q`:10 skipped,1975 deselected
(TEST_DATABASE_URL is not configured).

## 53. Alembic heads/history

Head único0009_notifications; nueve revisiones lineales:

`base -> 0001_phase1 -> 0002_catalog -> 0003_cart -> 0004_orders ->
0005_kitchen -> 0006_payments -> 0007_fulfillment ->
0008_cancellations_refunds -> 0009_notifications`.

`alembic heads` y `alembic history` no aplican DDL ni consultan una migración
stamp sobre la base normal. Migraciones1..8 con diff vacío.

## 54. PostgreSQL real validado o skipped

SKIPPED: no TEST_DATABASE_URL. No conexión a una TEST database, no claims de
constraints/triggers/races reales ejecutados. Las10 integraciones del proyecto
quedaron omitidas; entre ellas las dos nuevas de F9.
Base normal manual incompatible se preservó sin migrate/stamp/drop/adopción.
La validación online queda pendiente de proporcionar TEST dedicada/vacía.

## 55. Push provider real o pendiente

PENDIENTE: no FCM, APNs, SDK, cuenta ni credenciales. API device register sin
provider ->503, dispatcher vacío ->503. No afirma que un teléfono recibió push.
Integrar adapter real y verificar idempotency/cancelación/protocolo del proveedor
es trabajo futuro de despliegue, sin implementar promociones/marketing.

## 56. Push worker deployment real o pendiente

PENDIENTE. No existe un patrón CLI operativo que reutilizar; no se agrega uno
gratuitamente, cron, Celery/APScheduler, thread infinito ni lifespan loop.
get_push_dispatch_service es el seam de composición, no endpoint ni daemon.
Un worker externo deberá inyectar registry real y programar invocaciones finitas
de dispatch_pending_pushes(limit), registrar resultados seguros y recuperación.

## 57. Git status

Rama chore/backend-foundation; HEAD87ec588 sin staging/commit/push.
Seis archivos tracked modificados y37 nuevos; git status agrupa varios directorios.
`git diff --stat` muestra SOLO tracked, no cuenta source/tests/docs no rastreados.
`git diff --check` final sin errores. Stat tracked: seis archivos,
153 inserciones y nueve eliminaciones; no incluye los 37 archivos nuevos.
Whitespace de los nuevos se comprobó por separado sin staging.
No se creó ni eliminó rama y no se avanzó F10.

## 58. Riesgos

Advisory gate global serializa productores y exige load test/orden de locks
al añadir nuevos workflows multiórdenes; PostgreSQL revierte deadlocks, no rompe
atomicidad. Un writer DB privilegiado que omita captura invalida el contrato cursor.
Polling1s/COUNT y SSE concurrentes requieren capacity/proxy monitoring.
No retención automática: history crece. Snapshot puede estar adelantado al cursor
(tolerable replay), no atrasado con cursor adelantado que cause pérdida.
Push externo al menos una vez; crash después de aceptación puede duplicar.
Provider pendiente: no se puede prometer retractar mensajes aceptados ni
privacidad física después de un lease expirado con adapter que ignore cancelación.
Cliente debe deduplicar y validar contexto propietario al mostrar/refetch.
Base normal incompatible y PostgreSQL real no validado impiden afirmar despliegue
funcional completo de notificaciones en esa base.

## 59. Pendientes

Proporcionar TEST_DATABASE_URL vacía/dedicada y ejecutar ambas integraciones;
validar PL/pgSQL y carreras reales antes de desplegar. Planificar adopción de la
base manual sin stamp destructivo. Elegir/probar PushGateway real, credenciales,
worker externo, observabilidad segura, SDK Flutter y frontend SSE autorizado.
Dimensionar índices/conexiones, global gate, retention y proxy timeouts.
Ninguna de estas tareas se ejecutó sobre infraestructura externa sin autorización.

## 60. Fuera de alcance

Fase10, marketing/promociones/preferences complejas, emails/SMS/WhatsApp,
reviews/favoritos/boleta/PDF, dashboard RF-49, inventario, topics/broadcast/manual
admin push, WebSocket, Redis/Kafka/RabbitMQ, SDK FCM/APNs concreto, Docker.
No modificaciones directas de status/order financial ledger desde Notifications.
No commits/pushes ni cambio de rama.

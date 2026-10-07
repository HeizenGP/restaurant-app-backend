# Fase 8 — Cancelaciones y reembolsos

Fecha: 2026-10-07. Repositorio: /home/heizen27/proyectos/restaurante-backend.
Rama: chore/backend-foundation. Base: bfe2295 (Fase 7).
La petición directa de conservar la rama prevalece sobre feat/cancellations-refunds
del adjunto. No se creó rama, staging, commit, push ni Fase 9.

## 1. Resumen ejecutivo

Se implementan solicitudes de cliente, aprobación/rechazo administrativo,
cancelación directa y obligación de reembolso íntegro. El pedido y el cobro
original conservan su historia. Se agregan seis tablas, 13 operaciones HTTP,
migración 0008, permisos por sucursal y pruebas en todas las capas.

REFUND ORCHESTRATION: IMPLEMENTADA.
REAL ONLINE REFUND WITH FINANCIAL PROVIDER: PENDIENTE.

## 2. Alcance

Cliente solicita; ADMIN decide. Pedido no pagado se cancela sin inventar un
Payment ni Refund. Pedido pagado exige Refund por el 100 % en la misma
transacción. CASH se confirma únicamente después de la devolución efectiva
por el administrador. ONLINE necesita un proveedor financiero real.

## 3. CU/RF cubiertos

CU-08, CU-27 y CU-28, según el alcance proporcionado. RF-48: cancel_order
específico. RF-50: cliente solicita, administrador evalúa. RF-51: devolución
íntegra del cobro. RF-52: OUT_OF_STOCK cancela el pedido completo, no sus líneas.
No se inventan significados adicionales para los identificadores CU.

## 4. RN cubiertas

RN-13: Kitchen no puede cancelar pedidos. RN-14: cliente no cancela
directamente. RN-15: Refund.amount = Payment.amount = Order.total histórico.
RN-16: agotamiento tras pago cancela el pedido íntegro y registra Refund.
PEN y Decimal estrictos; sin porcentajes configurables ni importes del cliente.

## 5. Política MVP de cancelación

Permitidos: PENDING_PAYMENT, PENDING_CASH_CONFIRMATION, SCHEDULED, WAITING,
PREPARING, READY, READY_FOR_PICKUP y OUT_FOR_DELIVERY.
SERVED, PICKED_UP y DELIVERED son terminales no cancelables. CANCELLED solo admite
reintento idéntico; no una segunda cancelación. No se declara esta política como
normativa legal universal. Modificarla requiere decisión del negocio.

La política específica validate_cancellation no modifica validate_transition
ni habilita cancelación desde Kitchen/Fulfillment.

## 6. Arquitectura

Vertical slices hexagonales: Presentation → Application → Domain; Infrastructure
implementa puertos explícitos. Cancellations coordina Orders, registro local de
Refunds, cleanup de Fulfillment, autorización y auditoría. Payments es dueño
del ledger de reembolsos y OnlineRefundGateway. Ningún controlador genérico
ni BaseRepository/GenericService introduce acoplamiento entre slices.

## 7. Cancellations slice

Nuevo app/modules/cancellations:

- domain/models.py y policies.py: solicitud, cancelación, motivos y decisiones.
- application/dtos.py, errors.py, ports.py y services.py: casos de uso.
- infrastructure/orders.py, payments.py, fulfillment.py y authorization.py:
  adaptadores de capacidades públicas de los slices propietarios.
- infrastructure/persistence/models.py y repositories.py: dos tablas.
- presentation/schemas.py, dependencies.py y router.py: API y wiring.
- __init__.py de los paquetes.

Application/Domain no importan SQLAlchemy, SQLModel, FastAPI ni adaptadores.
No llaman a PaymentsService/KitchenService ni calculan importes de reembolso.

## 8. Orders integration

Nuevos app/modules/orders/domain/cancellations.py e
infrastructure/cancellations.py. OrderCancellationContext proyecta solo
identidad, sucursal, modalidad, estados, método e importe histórico.
Orders conserva propiedad exclusiva de status/order_status_history.
UPDATE condicional modifica únicamente status; se agrega historia con actor,
fecha backend y motivo constante seguro. No se borran items, addons ni snapshots.

## 9. Payments integration

Nuevos domain/refunds.py; application/refund_dtos.py, refund_errors.py,
refund_ports.py, refund_registration.py y refund_services.py;
infrastructure/refund_gateway.py y refund_registration.py;
infrastructure/persistence/refund_models.py y refund_repositories.py;
presentation/refund_schemas.py, refund_dependencies.py y refund_router.py.

El contrato público register_full verifica el Payment real y guarda obligación
e historia inicial sin commit propio. El repositorio de Payments implementa
ensure_cancelled_refund obligatorio; el servicio existente lo llama en los tres
caminos de éxito sobre pedidos cancelados. No se detecta opcionalmente si existen
tablas/capacidades para eludir el invariante de producción.

## 10. Fulfillment cleanup

Nuevo infrastructure/cancellations.py en Fulfillment. Tras la cancelación,
cierra la asignación activa mediante la capacidad pública de su repositorio:
unassigned_at, unassigned_by_user_id y reason = "Order cancelled".
Incluye OUT_FOR_DELIVERY. Conserva el registro y personal históricos.
La cola de Kitchen/Fulfillment deja de mostrar el pedido por sus filtros
existentes; no se llama a KitchenService ni se elimina su historia.

## 11. Customer requests

Customer/Guest con identidad vigente puede solicitar solo para pedidos propios.
Reason se recorta, es obligatorio, máximo 1000 caracteres, texto plano sin
HTML ni controles Unicode. No admite estado, actor, fecha ni importe del cliente.
Una solicitud PENDING por pedido. Repetir el mismo motivo normalizado devuelve
200; motivo distinto mientras está pendiente devuelve 409. Crear devuelve 201.
Una solicitud rechazada queda histórica; puede crearse otra.
La propia tabla constituye la trazabilidad del cliente.

## 12. Admin approve

Revalida estado y pertenencia después del lock de Order y refresca la Request.
En una transacción: status/history de Order, OrderCancellation con Request,
Refund íntegro cuando corresponde, cierre de asignación, evaluación y audit.
No marca REFUNDED automáticamente. Reintento con mismo evaluador/nota es
idempotente; decisión, nota o evaluador diferentes devuelven 409.

## 13. Admin reject

Modifica únicamente evaluación de Request y agrega audit. No altera Order,
Payment, Refund ni asignaciones. Reintento exacto no agrega auditoría duplicada.
La evaluación usa actor autenticado y reloj backend.

## 14. Direct cancellation

ADMIN usa cancel_order con OUT_OF_STOCK u OTHER (OTHER exige reason).
No hay PATCH genérico de estado. Una Request pendiente se resuelve APPROVED
con nota backend en la misma transacción. El registro de cancelación conserva
source ADMIN y cancellation_request_id NULL; la solicitud resuelta se relaciona
históricamente por order_id, sin hacerse pasar por una solicitud aprobada normal.
Mismo actor/motivo permite reintento exacto; otros motivos/actor dan 409.

## 15. Out of stock

OUT_OF_STOCK cancela el pedido completo. No es un motor de stock, no reemplaza
productos ni cambia cantidades, total, tarifa o descuentos. Si fue pagado,
obliga a registrar Refund 100 %; si no, no crea movimiento financiero ficticio.

## 16. OrderCancellation

Registro único por Order, sucursal, source, motivo, referencia de Request
opcional, actor y fechas backend. Source CUSTOMER_REQUEST requiere Request y
código CUSTOMER_REQUEST; ADMIN requiere referencia NULL y motivo administrativo.
FK RESTRICT. Trigger impide UPDATE/DELETE de esta historia.

## 17. Refund model

Registro único por Payment y por Order; amount NUMERIC(18,2), moneda PEN, método
original, reason CANCELLATION, estados PENDING/PROCESSING/REFUNDED/FAILED y
timestamps conscientes de zona. refunded_at existe exactamente en REFUNDED.
reconciliation_required indica éxitos adicionales o intento externo pendiente
tras otro éxito; es evidencia interna, no expuesta al cliente.

Decisión para total cero: Payment real de 0.00 permite obligación explícita
PENDING de 0.00, sin inventar una transferencia. CASH puede confirmarse; ONLINE
requiere un proveedor configurado con soporte a esa operación.

## 18. Full refund invariant

CANCELLED + Payment realmente PAID exige Refund.amount = Payment.amount =
Order.total, moneda y método coherentes. Pedido con payment_status PAID pero
sin Payment financiero coherente devuelve REFUND_REQUIRED_PAYMENT_MISSING
(503) y rollback; nunca fabrica un cobro para satisfacerlo.

Además de locks/casos de uso, cuatro constraint triggers evalúan el estado final
al terminar la transacción. La semántica diferida sigue la
[documentación oficial de PostgreSQL](https://www.postgresql.org/docs/current/sql-createtrigger.html).
Guardan obligación íntegra y ausencia de asignación activa; otro trigger protege
el snapshot financiero inmutable del Refund. No se auditó/aplicó esto sobre
datos heredados reales: antes del despliegue es necesaria su conciliación.

## 19. Cash refund

POST administrativo, sin amount/fecha/actor del cliente. PENDING → REFUNDED con
historia STAFF y audit REFUND_CASH_CONFIRMED. Es una confirmación humana de
devolución efectiva, no una automatización de caja. Repetir devuelve el mismo
resultado sin nueva historia. Payment continúa PAID; Order continúa CANCELLED.

## 20. Online refund

PENDING → PROCESSING → REFUNDED o FAILED; FAILED → PROCESSING con un nuevo
intento/key. REFUNDED es terminal. Se exige una captura original SUCCEEDED
coherente y del mismo proveedor: cero/múltiples capturas o importe/proveedor
ambiguos se rechazan antes de enviar dinero. Múltiples capturas reales necesitan
conciliación explícita; el MVP no devuelve todos esos cobros automáticamente.

Reserva/commit → llamada externa con key estable → persistencia/commit.
Reintento de key fallida no reenvía dinero. Timeout deja CREATED recuperable,
nunca lo convierte ficticiamente en FAILED ni REFUNDED.

## 21. OnlineRefundGateway

Puerto de Payments con refund(request) y verify_and_parse_webhook(bytes,headers).
Request contiene referencia original del cobro, importe/moneda backend y
provider_idempotency_key = refund-attempt:<UUID>. Resultado confiable puede ser
PROCESSING, SUCCEEDED o FAILED. La firma solo se verifica en el adaptador del
proveedor; no se inventó HMAC, secreto, endpoint ni SDK de producción.

## 22. Provider real configurado o no

UnconfiguredOnlineRefundGateway devuelve REFUND_PROVIDER_UNAVAILABLE (503).
No reserva nuevos intentos ni cambia PENDING cuando falta configuración.
El fake firmado y cacheado existe solo en tests. No representa devolución
bancaria real ni se conecta a servicios externos.

## 23. Refund attempts

Históricos CREATED/PROCESSING/SUCCEEDED/FAILED. UNIQUE(refund_id,key), índice
único parcial de intento activo y referencia única por proveedor cuando existe.
Idempotencia externa deriva del UUID persistido y se conserva en timeout/retry.
Referencia original del Payment se consulta, no se acepta del administrador.
No se confunde RefundAttempt con PaymentAttempt.

## 24. Refund history

Append-only, estado anterior/nuevo, fuente SYSTEM/STAFF/PROVIDER, actor cuando
corresponde, intento/evento y fecha backend. NULL → PENDING requiere SYSTEM.
Confirmación CASH usa STAFF. Verificación financiera ONLINE usa PROVIDER.
Ningún cliente puede aportar source ni "mark refunded".
Trigger bloquea UPDATE/DELETE; estados adicionales no borran historia anterior.

## 25. Refund provider events

Webhook recibe bytes opacos (máximo 64 KiB) sin JWT, verifica antes de acceder a
DB y solo procesa DTO confiable. UNIQUE(provider,event_id), hash SHA-256 de bytes,
importe/moneda reportados y resultado. No almacena payload bruto ni secretos.
Mismo ID/hash se deduplica; mismo ID/diferentes bytes da 409 sin cambiar evidencia.

Amount/currency mismatch guarda REJECTED y ACK 200 sin REFUNDED.
Referencia aún desconocida guarda evidencia y devuelve 503 para reintentar.
Éxito tardío tras FAILED registra verdad financiera; failure tras REFUNDED se
ignora. Dos éxitos diferentes conservan ambas evidencias y señalan conciliación,
sin dos transiciones REFUNDED ni reactivar Order.

## 26. Late payment

Todos los caminos de éxito del Payment existente sobre CANCELLED registran
Refund íntegro en la misma transacción que captura, Payment/history y evento.
Si falla ese registro, se revierte la captura local y el evento puede reintentarse.
No se llama a OnlineRefundGateway en el webhook de cobro.
Order.payment_status pasa a PAID pero Order.status sigue CANCELLED.

## 27. Concurrency

Orden elegido: Order → Request (si aplica) → Payment → Refund → Assignment.
El lookup inicial de Request en review es scoped/read-only; luego se bloquea
Order y se refresca/bloquea Request. Esto difiere del orden sugerido en el adjunto:
bloquear Request antes de Order crearía inversión frente a cancelación directa
y creación de solicitudes. Rechazo también adquiere Order primero.
Procesar Refund bloquea solo Refund → Attempt, nunca Orders/Payment; así no
introduce el ciclo contrario. Eventos se deduplican antes de ese lock.

Locks FOR UPDATE, updates condicionales e índices únicos son barreras distintas.
Las pruebas con adaptadores de memoria independientes cubren órdenes de carrera
cancel/approve, approve/reject, cancel/preparación, cancel/despacho y cancel/pago.
No constituyen evidencia de contención PostgreSQL entre conexiones; esa
verificación continúa pendiente por falta de TEST_DATABASE_URL.

## 28. Transactions

Una AsyncSession compartida por acción local. Adaptadores entre slices no hacen
commit. Cancelación/decisión/refund/history/cleanup/audit se confirman una vez.
Fallo intermedio o commit fallido provoca rollback de todo. El proveedor nunca
se llama dentro de la transacción de cancelación ni manteniendo locks DB.
Ejecución ONLINE usa dos transacciones breves separadas por I/O externo.
Webhook Refund guarda evento, intento, obligación e historia atómicamente.

## 29. Authorization

Nuevos CANCELLATION_VIEW, CANCELLATION_MANAGE y REFUND_MANAGE, solo ADMIN BRANCH
existente. No nuevos roles, KITCHEN ni CUSTOMER reciben estos permisos.
CurrentRegisteredUser/CurrentCustomer reales validan JWT e identidad actual;
los permisos se consultan en DB en cada acción, no en claims de rol.
Webhook no usa JWT del proveedor: exige autenticación propia del gateway.

## 30. Branch isolation

Permiso específico por branch_id antes de cargar recursos. Repositorios filtran
branch antes/junto al ID; un ID perteneciente a otra sucursal autorizada se
oculta como 404. Listas filtran sucursal y usan limit 1..100 (default 50),
offset 0..INT32, orden estable por fecha/UUID.

## 31. IDOR

Customer/Guest solo consulta solicitudes y Refund de su customer_id. Recursos
ajenos/no existentes dan 404. Cliente no procesa/refunda/cancela directamente.
RefundResponse oculta Payment ID, referencias bancarias, keys, hashes, payloads
y motivos internos. Admin recibe resumen de intentos/historia, no secretos.

## 32. Audit

Acciones: CANCELLATION_REQUEST_APPROVED, CANCELLATION_REQUEST_REJECTED,
ORDER_CANCELLED, REFUND_CASH_CONFIRMED y REFUND_ONLINE_PROCESS_REQUESTED.
Auditoría usa la misma sesión, actor actual y estados mínimos; no motivos de
cliente crudos en Order history, payloads, tokens ni secretos.
El reintento idéntico no agrega acciones repetidas.

## 33. Migration 0008

0008_cancellations_refunds depende de 0007_fulfillment. Seis tablas nuevas:
cancellation_requests, order_cancellations, refunds, refund_attempts,
refund_status_history, refund_provider_events. Total: 46 tablas de aplicación,
47 incluyendo alembic_version. Migraciones 0001–0007 intactas.
Reutiliza restaurant_phase1_set_updated_at en tres tablas.
Dos funciones propias protegen invariante financiero/historia, sin duplicar
la función reloj compartida. Downgrade comprueba primero las seis tablas y
aborta si hay historia, antes de cualquier DDL; solo retira objetos propios.
No startup DDL, create_all, autogenerate, stamp ni cambio de URL/configuración.

## 34. Constraints

UUID/FK RESTRICT, motivos y estados válidos, texto plano acotado, evaluación
completa/cronológica, source/provenance, Decimal no negativo/sin NaN,
PEN/método original, estado/refunded_at, finalización de intentos y eventos.
Unicidad de Request pendiente, cancelación, obligación, intento y evento.
Constraint triggers diferidos para coherencia inter-tablas y snapshot Refund
inmutable; triggers append-only para cancelación e historia financiera.

## 35. Indexes

Diez índices explícitos nuevos: tres de Requests (pendiente único/owner/review),
uno de cancelaciones por sucursal/fecha, dos de Refunds (status/fecha/UUID y
fecha/UUID), tres de Attempts (activo/reference/history) y uno de timeline de
Refund history. UNIQUE(order_id) y UNIQUE(refund_id,key) son constraints, no
índices explícitos extra. Scope/ownership financiero se obtiene vía Orders.
Los nombres, columnas, predicados y cardinalidad se contrastan con metadata en
tests/test_phase8_migration.py. No duplicación de índices de Orders/Fulfillment.

## 36. Tests Domain

Estados cancelables vs terminales, decisiones exactas, motivos, Unicode,
provenance, fechas, dinero estricto/PEN/cero, grafo completo 4×4 de Refund ONLINE,
flujo CASH, historia/actor y coherencia full-refund. Casos parametrizados.
Los principios de Orders/Payment se reutilizan, no se reemplazan por políticas
relajadas en los fakes.

## 37. Tests Services

Idempotencia, solicitud/rechazo/nueva solicitud, approve/direct, ocho estados,
pago coherente/incoherente, rollback en siete pasos locales, cleanup histórico,
cash, provider ausente, timeout/key estable, retry fallido, webhook firmado,
mismatches, eventos duplicados/desordenados, éxitos adicionales y conciliación.
PaymentService real con adaptadores de prueba demuestra captura tardía atómica
y rollback si falla la obligación. No fake en wiring de producción.

## 38. Tests API

93 pruebas de Fase 8 con TestClient y AuthService/JWT reales. Solo se sustituyen
puertos y repositorios de infraestructura de pruebas, nunca CurrentPrincipal.
401 sin token, 403 sin permiso, 404 IDOR/sucursal, 409 reintentos conflictivos,
422 inputs/controlados y 503 evidencia/proveedor ausentes.
Protección de datos, permisos revocados y usuario bloqueado/eliminado.

## 39. Tests Repositories

SQL compilado PostgreSQL: proyecciones mínimas, filtros de ownership/sucursal,
locks FOR UPDATE OF orders/refunds, refresh, updates condicionales y sin cambiar
importe/snapshots. Consulta de captura limita a dos para detectar ambigüedad.
Listados paginados; detalle financiero son dos consultas acotadas, no N+1.
Eventos ON CONFLICT DO NOTHING; errores IntegrityError sanitizados.

## 40. Tests Migration

Siete pruebas específicas: head/cadena, seis tablas exactas, metadata total,
checks/índices/FK/tipos, full obligation y triggers, permisos, downgrade y capas.
Pruebas históricas Fase 7 siguen ancladas a su revisión, sin asumir ser head.
Pruebas OpenAPI de Fases 4/6 siguen verificando sus operaciones originales,
excluyen solo nuevas rutas Cancellation/Refund verificadas en Fase 8.

## 41. PostgreSQL integration

tests/integration/test_phase8_postgresql.py usa guarded_test_url heredado:
requiere -m integration, TEST_DATABASE_URL explícita, nombre TEST y base vacía
distinta de normal; todas las operaciones/DDL se revierten por transacción externa.
Prepara cadena 0001–0008, grants, unique, rollback tras registro Refund,
confirmación CASH, trigger diferido forzado, historia/snapshot inmutables,
captura tardía con repositorio real, cleanup y downgrade guardado/vacío.

El test histórico Fase 6 mantiene esquema 0006 con adaptador EXCLUSIVAMENTE
de prueba para el hook que entonces no existía. Producción nunca omite el hook;
el test de Fase 8 utiliza SQLAlchemyPaymentRepository real. No se presenta
esta prueba de una conexión como carrera multiconexión.

## 42. Ruff

ruff check .: All checks passed!
ruff format --check .: 351 files already formatted.
Ambos comandos terminaron con código 0.
No se agregaron dependencias, SDK ni configuración global para Phase 8.

## 43. Pytest

Baseline previo: 1440 passed, 7 skipped, 0 failed (225.51 s).
La suite actual recoge 1722 pruebas. Resultado final exacto:

~~~text
pytest -q
1714 passed, 8 skipped in 298.38s (0:04:58)

pytest tests/modules/cancellations -q
185 passed in 72.49s (0:01:12)

pytest tests/modules/payments -q
338 passed in 35.99s

pytest tests/test_phase8_migration.py -q
7 passed in 0.16s

pytest tests/integration/test_phase8_postgresql.py -m integration -q
1 skipped in 0.09s
TEST_DATABASE_URL is not configured
~~~

Todas las ejecuciones finales terminaron con código 0. Hay 274 nuevas pruebas
no PG y una integración nueva opt-in. El primer recorrido completo detectó
cuatro fallos: dos expectativas históricas OpenAPI (corregidas para conservar
sus operaciones originales) y dos respuestas JWT 401 transitorias de F7 que
no se reprodujeron al ejecutar esos diez casos (10 passed) ni al repetir toda
la suite. No se relajó la validación JWT ni se modificaron esos tests de F7.
El primer recorrido fue 4 failed, 1710 passed, 8 skipped; no se oculta ese dato.

## 44. Alembic

alembic heads: 0008_cancellations_refunds (head).
alembic history: base → 0001_phase1 → 0002_catalog → 0003_cart → 0004_orders →
0005_kitchen → 0006_payments → 0007_fulfillment → 0008_cancellations_refunds.
Un solo head. Compilar SQL offline no demuestra aplicación PostgreSQL real.

## 45. PostgreSQL real validado o skipped

SKIPPED: TEST_DATABASE_URL no está configurada.
Prueba opt-in específica: 1 skipped por ese motivo. La base normal manual
incompatible se preservó sin upgrade/stamp/reconciliación. Por tanto no se afirma
migración 0008 aplicada, validación real de triggers ni carrera PG real.
Swagger/OpenAPI vivo respondió 200 y expone las 12 rutas/13 operaciones nuevas.
Smoke HTTP: /docs 200; solicitud sin JWT 401; webhook de Refund con proveedor
no configurado 503. Ninguno de esos checks creó/canceló pedidos ni devolvió dinero.

## 46. External refund provider real o pendiente

PENDIENTE. Seleccionar proveedor y su protocolo oficial de devolución/firma,
referencias de captura, errores, idempotencia y soporte de cero. Implementar
adaptador, secretos seguros, pruebas sandbox/contratos y operación/conciliación.
Nada en esta fase constituye evidencia de devolución bancaria efectiva.

## 47. Notifications pendientes

Sin envío push, email ni avisos automáticos. Historia y audit están listos para
integración posterior. No se instaló cola, scheduler ni worker en lifespan.

## 48. Riesgos

Antes de producción: esquema heredado incompatible; conciliar Cancelled+Paid
históricos sin Refund antes de migrar; validar triggers/locks/downgrade en TEST.
Proveedor real no configurado; no poner operador ONLINE en uso bancario.
Timeout necesita reintento con misma key; fallos reales requieren nueva key.
Múltiples cobros/devoluciones exigen conciliación humana, no doble dinero automático.
Pruebas de memoria/SQL estático no demuestran aislamiento bajo contención real.

## 49. Pendientes

Proporcionar TEST_DATABASE_URL dedicada/vacía y validar integración más carreras
entre conexiones. Elegir/configurar proveedor real con protocolo firmado y
sandbox. Aprobar política operacional de cancelación avanzada y de importe cero.
Conciliar datos heredados bajo un plan independiente; no ejecutar sobre la base
actual de forma automática. Notificaciones/operación contable fuera de esta fase.

## 50. Git status final

Rama conservada: chore/backend-foundation; HEAD bfe2295, sin commit/push del agente.
Cambios tracked: Payments ports/service/repository; router v1; migrations/env.py;
README; tests históricos de capas, migración F7, API Orders F4 y
API/Fakes/integración Payments F6.
Untracked: slice Cancellations; capacidades públicas Orders/Fulfillment;
archivos Refunds de Payments; migration 0008; tests de Cancellations/Refunds,
migración/integración F8 y este informe. Sin staging.
git diff --stat no cuenta untracked; el inventario anterior sí los incluye.
git status --short --branch: chore/backend-foundation...origin/chore/backend-foundation.
12 archivos tracked modificados; 52 archivos untracked; 0 staged.
git diff --stat: 12 files changed, 203 insertions(+), 8 deletions(-), excluye
untracked por semántica de Git. git diff --check: código 0, sin diagnósticos.
Chequeo adicional de los 52 archivos untracked: 0 diagnósticos de whitespace.
Ningún archivo 0001–0007 aparece en git diff; requirements/config/startup intactos.

## 51. Fuera de alcance

Fase 9, notificaciones, UI frontend/dashboard, contabilidad/caja automatizada,
refunds parciales, voids, chargebacks, cupones/compensaciones, stock automático,
proveedor financiero inventado, SDK nuevo, roles/permisos genéricos, scheduler,
cleanup destructivo de órdenes/pagos y migración de la base manual.

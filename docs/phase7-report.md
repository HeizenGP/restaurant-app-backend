# Fase 7 — Fulfillment: delivery y recojo programado

Fecha: 2026-10-07. Repositorio: /home/heizen27/proyectos/restaurante-backend.
Rama: chore/backend-foundation. Base: ff8f304, Fase 6 guardada por el usuario.
La instrucción directa de mantener la rama prevalece sobre feat/fulfillment
mencionada en el adjunto. No se crea rama, staging, commit ni push.

## 1. Resumen ejecutivo

Se implementó el slice Fulfillment con 13 operaciones administrativas:
reevaluación/liberación de recojos programados, entrega con validación de
identidad histórica, cola y asignaciones de delivery, despacho/entrega auditados
e incidencias de retraso sujetas a decisión humana. Incluye migración 0007,
autorización por sucursal y pruebas de dominio, aplicación, API y persistencia.
No se declara ejecución PostgreSQL real ni worker instalado.

## 2. Alcance

PICKUP SCHEDULED → WAITING; READY_FOR_PICKUP → PICKED_UP.
DELIVERY READY → OUT_FOR_DELIVERY → DELIVERED. Historial de asignación y revisión
de retrasos > 15 minutos. GET no escribe; las acciones y detección son explícitas.
No incluye caja contable, pagos parciales, devoluciones, promociones o Fase 8.

## 3. Reglas funcionales y de negocio

Se cubren los requisitos del adjunto relativos a recojo programado, entrega
con identidad, delivery por sucursal, personal activo, ETA histórica, retraso
estricto e intervención humana. Se preservan las reglas heredadas de zonas
y tarifas; no se reinventa su validación ni se modifican importes. No se asignan
números RF/RN que no estén identificados de forma inequívoca en el código base.

## 4. Capacidades heredadas de Fase 4

Orders ya conserva modalidad, configuración aplicada, requested_pickup_at,
calculated_kitchen_release_at, estimated_ready_at, snapshots de identidad,
dirección/zona/tarifa/ETA y el historial histórico completo. Se consume esa
información; no se añade otra tabla de órdenes ni se recalcula un checkout.

## 5. Capacidades completadas en Fase 7

La programación ahora tiene consulta operativa y liberación manual/en lote.
La preparación existente se enlaza con la entrega final de recojo y delivery.
Se agrega asignación histórica de personal e incidencia única por pedido,
con aprobación/rechazo auditable sin impacto financiero automático.

## 6. Arquitectura

Vertical slice hexagonal: Presentation → Application → Domain; Infrastructure
implementa puertos específicos. Fulfillment.Domain importa contratos mínimos
de Orders.Domain; Application coordina OrdersGateway, Authorization,
FulfillmentRepository y AuditRecorder. No BaseRepository, GenericService ni
controlador genérico. Una AsyncSession por petición y una transacción por acción.

## 7. Límite con Orders

Orders es dueño del único lifecycle y order_status_history. Su nuevo contrato
OrderFulfillmentContext proyecta solo identidad operacional/timing/snapshots.
validate_fulfillment_transition restringe las cuatro acciones y reutiliza el
grafo existente validate_transition. UPDATE condicional modifica solo status;
actor, motivo y fecha se agregan al historial en la misma sesión.

## 8. Límite con Kitchen

Fulfillment no importa ni llama a KitchenService. PREPARING y READY o
READY_FOR_PICKUP continúan siendo responsabilidad exclusiva de Kitchen.
Liberar SCHEDULED a WAITING permite que la cola de Kitchen lo vea naturalmente.
No endpoint genérico permite saltar preparación ni cancelar desde Fulfillment.

## 9. Límite con Payments

No cambia Payments, su ledger ni su gateway. PICKUP/DELIVERY exigen ONLINE,
PAID y confirmed_at; la API no acepta confirmación financiera del cliente.
Payments sigue activando WAITING/SCHEDULED según modalidad. El proveedor online
de Fase 6 continúa sin configurar: no se simula una captura real de dinero.

## 10. Archivos nuevos

- app/modules/fulfillment/domain/models.py y policies.py: entidades/invariantes.
- app/modules/fulfillment/application/dtos.py, errors.py, ports.py, services.py.
- app/modules/fulfillment/infrastructure/authorization.py y orders.py.
- app/modules/fulfillment/infrastructure/persistence/models.py y repositories.py.
- app/modules/fulfillment/presentation/dependencies.py, schemas.py y router.py.
- __init__.py de cada paquete del nuevo slice.
- app/modules/orders/domain/fulfillment.py: contrato y política pública de Orders.
- app/modules/orders/infrastructure/fulfillment.py: proyección y transiciones.
- migrations/versions/0007_create_fulfillment.py.
- tests/modules/fulfillment: fakes.py, conftest.py, test_domain.py,
  test_services.py, test_api.py, test_repositories.py y __init__.py.
- tests/test_phase7_migration.py; tests/integration/test_phase7_postgresql.py.
- docs/phase7-report.md.

## 11. Archivos modificados

- app/modules/branches/infrastructure/persistence/repositories.py:
  contrato público staff_is_active con scope y locks compartidos.
- app/modules/orders/infrastructure/persistence/models.py: índice parcial PICKUP.
- app/presentation/api/v1/router.py: registro del router Fulfillment.
- migrations/env.py: registro de metadata Fulfillment.
- tests/test_phase1_migration.py: nuevo slice en auditoría de capas.
- tests/test_phase6_migration.py: pruebas históricas no presuponen head actual;
  checks y SQL específicos de Fase 6 se mantienen.
- README.md: alcance, arquitectura, operación, migración y pendientes actuales.

No se modifican migraciones 0001–0006, requirements, lifespan, puertos de red,
contenedores ni archivos de configuración con secretos.

## 12. Programación de recojo

GET /pickup/due devuelve recojos SCHEDULED pagados/confirmados por sucursal,
incluidos próximos todavía no vencidos. Su respuesta muestra referencia inicial
y recomendación vigente, requested_pickup_at, ambos ready_at, queue_depth,
minutes_until_release e is_due. No consulta el perfil actual del cliente.

## 13. Algoritmo de reevaluación

queue_delay = queue_depth × queue_delay_per_order_minutes.
prep_minutes = default_prep_minutes + queue_delay.
estimated_ready_at vigente = requested_pickup_at − pickup_buffer_minutes.
recommended_release_at = estimated_ready_at vigente − prep_minutes.
Todas las fechas son aware. Se rechaza una cola negativa/no entera o un schedule
no representable. La hora solicitada y los cálculos originales permanecen intactos.

## 14. Profundidad de cola

Se reutiliza queue_depth público de Orders, contando WAITING/PREPARING por
sucursal. Settings provienen del repositorio público de configuración de Orders.
Un lote usa una foto de cola para todos sus candidatos; los pedidos que el propio
lote libera no aumentan sucesivamente la recomendación de los demás.

## 15. Elegibilidad de liberación

SCHEDULED, PICKUP, ONLINE, PAID y confirmed_at, con reloj backend >= recomendación
actual. Antes de esa fecha: 409 PICKUP_NOT_DUE. WAITING es reintento sin escritura
extra; PREPARING/READY_FOR_PICKUP/PICKED_UP no retroceden. El historial usa
"Scheduled pickup released to kitchen", actor y timestamp del backend.

## 16. Liberación por lote

POST /pickup/release-due acepta limit 1..100, 50 por defecto. Lee candidatos
debidos bajo FOR UPDATE OF orders SKIP LOCKED y aplica el mismo caso de uso.
Un commit para el lote; cualquier fallo revierte todo. No duplica historial.
La función release_due_pickups es reusable por un futuro worker externo con
actor autorizado, pero no se instala ejecución periódica.

## 17. Entrega del recojo

POST /pickup/orders/{order_id}/complete acepta únicamente customer_name y
customer_phone. READY_FOR_PICKUP → PICKED_UP exige coincidencia completa de
ambos snapshots. Reintento en PICKED_UP vuelve a validar identidad y no escribe
otra historia. No puede entregar un pedido en SCHEDULED/WAITING/PREPARING.

## 18. Identidad

Nombre: trim, colapso de espacios y casefold, sin fuzzy matching ni quitar
acentos. Teléfono: número completo de 9..15 dígitos ASCII, + opcional y separadores
espacio/paréntesis/guion; no se infiere prefijo de país ni se comparan últimos
cuatro dígitos. Texto vacío, largo o con controles se rechaza. No se encontró
normalizador compartido existente: se conserva el formato base de Auth sin
cambiar su comportamiento. Inputs de verificación no se persisten ni se loguean.

## 19. Cola de delivery

GET /delivery/queue: solo DELIVERY de la sucursal autorizado, ONLINE/PAID/
confirmed_at y WAITING, PREPARING, READY u OUT_FOR_DELIVERY. limit/offset acotados,
filtro status y orden estable por order_number/id. Una consulta proyecta Orders,
detalles e historial; una segunda carga asignaciones activas en lote, no N+1.
Incluye dirección/recipiente/ETA histórica únicamente para personal autorizado.

## 20. Asignación

PUT /delivery/orders/{order_id}/assignment acepta assigned_user_id.
Solo WAITING/PREPARING/READY; usuario ACTIVE no eliminado, asignación staff activa
ya iniciada y no terminada, misma sucursal activa, rol BRANCH. No inventa DRIVER.
La asignación guarda assigned_by_user_id y assigned_at del backend.
Mismo asignado activo: idempotente, sin duplicar registro ni auditoría.

## 21. Reasignación y desasignación

Reasignar cierra la fila anterior con unassigned_at, unassigned_by_user_id y
motivo, y crea la nueva en la misma transacción. DELETE /assignment cierra la
activa y responde 204; repetir no elimina historia. Se prohíben estos cambios
después del despacho en el MVP. Auditoría compartida registra ASSIGNED,
REASSIGNED o UNASSIGNED con identificadores, sin dirección ni identidad privada.

## 22. Despacho

POST /delivery/orders/{order_id}/dispatch: READY → OUT_FOR_DELIVERY con asignación
activa. Revalida elegibilidad del personal y conserva locks SHARE de staff/user
hasta commit. Un retry en OUT_FOR_DELIVERY es seguro y no agrega historial;
si ya no existe asignación elegible se rechaza, sin fabricar una.

## 23. Entrega de delivery

POST /delivery/orders/{order_id}/complete: OUT_FOR_DELIVERY → DELIVERED y
completed_at de asignación en la misma transacción con historial. Retentar
DELIVERED no repite escritura. La hora real es la historia DELIVERED, no una
estimación ni la fecha de consulta. Se permite al ADMIN autorizado completar
un despacho existente aunque el asignado haya sido desactivado posteriormente.

## 24. Zonas y tarifas

Se preserva configuración de DeliveryZone de Fase 4, incluida cobertura y zonas
gratuitas. Fulfillment solo muestra delivery_zone_name_snapshot. No consulta
la zona actual para reconstruir un pedido ni introduce otra tarifa.
delivery_fee histórico y cualquier importe del pedido permanecen inalterados.

## 25. ETA comprometida

estimated_delivery_at de OrderDeliveryDetails permanece inmutable. No se reemplaza
por settings actuales ni por hora de despacho/entrega. La incidencia conserva
committed_eta copiado de ese snapshot. Los listados no fabrican una ETA nueva.

## 26. Detección de retrasos

POST /delivery/delays/detect requiere DELIVERY_DELAY_REVIEW. Solo delivery
pagado/confirmado en los cuatro estados operacionales o DELIVERED; CANCELLED
queda excluido. Para activos usa backend now; para terminados usa delivered_at
del único historial DELIVERED. Se calcula desde la misma foto MVCC de la consulta.
Historial DELIVERED ausente o múltiple causa error seguro, no evidencia inventada.

## 27. Umbral de quince minutos

Condición estricta: referencia > committed_eta + 15 minutos.
14:59 y 15:00 no son retraso; 15:00.000001 sí. La condición usa datetime sin
redondeo. delay_seconds_at_detection usa ceil positivo, evitando que 900.1 se
guarde como 900; se satura a 2147483647. Fechas equivalentes en otra zona horaria
producen el mismo resultado. DELIVERED no sigue acumulando retraso tras completar.

## 28. Incidencias

delivery_delay_incidents tiene UNIQUE(order_id). INSERT ON CONFLICT DO NOTHING
preserva detected_at, ETA, umbral, estado observado y segundos originales.
Detectar repetidamente devuelve recuento nuevo/existente, sin reemplazar evidencia.
GET /delivery/delays es solo lectura y lista por detected_at/id descendente.
Detección limitada usa after_order_number y next_order_number para recorrer todas
las páginas; cada ciclo vuelve a 0, incluidos pedidos omitidos por SKIP LOCKED.

## 29. Responsabilidad del cliente

customer_responsibility es StrictBool o null, definido explícitamente por el
evaluador. No lo infiere el reloj, el retraso ni aprobar/rechazar. Puede existir
APPROVED con true: una decisión comercial no se deduce de responsabilidad.
OPEN no puede tener datos de evaluación, responsabilidad o remediación.

## 30. Aprobación

POST /delivery/delays/{incident_id}/approve exige descripción no vacía de hasta
2000 caracteres y permite nota/responsabilidad. OPEN → APPROVED guarda evaluador,
fecha y auditoría compartida. No crea descuento, reembolso, crédito ni cupón.
Mismo actor y datos normalizados: retry idempotente; cualquier otra decisión
terminal: 409 DELIVERY_DELAY_ALREADY_DECIDED.

## 31. Rechazo

POST /delivery/delays/{incident_id}/reject permite nota/responsabilidad pero
rechaza remediation_description como extra. OPEN → REJECTED registra procedencia
y auditoría; no borra incidencia ni evidence. Una decisión no se puede sobreescribir
con la otra, ni editarse informalmente mediante un endpoint genérico.

## 32. Sin compensación financiera automática

La descripción representa una actuación humana/documental. No se ejecuta una
transferencia, pago, devolución o descuento. No se modifica Orders.total,
delivery_fee, snapshots monetarios ni Payment. Integrar remediación financiera
requiere una fase específica y autoridad adicional, no está implícito aquí.

## 33. Permisos

Cuatro permisos nuevos sembrados exclusivamente en ADMIN de scope BRANCH:
FULFILLMENT_VIEW, FULFILLMENT_MANAGE, DELIVERY_ASSIGN, DELIVERY_DELAY_REVIEW.
No KITCHEN ni CUSTOMER. View permite lecturas; manage liberación/entrega/
despacho; assign únicamente asignaciones; review detección y decisión humana.
No hay PAYMENT_VIEW nuevo ni autorización administrativa global inventada.

## 34. Seguridad

Todas las rutas usan CurrentRegisteredUser de Auth, JWT real y usuario activo.
Autorización se resuelve contra permisos/asignaciones vigentes en DB; no roles
del token. Scoping de sucursal precede acceso por ID en SQL. Otra sucursal
autorizada no permite leer/mutar recursos ajenos: 404. Sin permiso: 403;
sin JWT/usuario válido: 401. Request schemas prohíben extras en body/query.

## 35. Privacidad

Cola administrativa devuelve únicamente los campos históricos operativos
necesarios, incluida dirección para delivery. No expone password/JWT/keys de
checkout/referencias de proveedor/customer_id ni precios. Errores no incluyen
inputs de identidad, direcciones, notas o SQL. Auditoría de asignación/decisión
usa IDs y estados; historial de recojo usa motivo constante sin nombre/teléfono.

## 36. Transacciones

Session compartida entre FulfillmentRepository, OrdersGateway, Branches y
AuditRecorder. El caso de uso hace commit/rollback, no adaptadores individuales.
Status + historial; reasignación + auditoría; DELIVERED + cierre de asignación;
decisión + auditoría son atómicos. GET no hace commit ni crea datos. Fallos de
historial, cierre, auditoría o commit revierten efectos previos.

## 37. Concurrencia

Orden de locks operacional: Order → Assignment. Detección: Order SKIP LOCKED →
INSERT incidente. Revisión: solo Incident, nunca después Order, evitando inversión.
Asignación y despacho toman SHARE de staff/user. UNIQUE parcial y UNIQUE por Order
refuerzan barreras de DB. UPDATE de estado/decisión incluye estado origen y scope.
Se prueban carreras con repositorios independientes y almacén en memoria
serializado; se valida SQL de FOR UPDATE OF orders SKIP LOCKED. Eso no demuestra
contención real multi-conexión PostgreSQL: pendiente de entorno TEST.

## 38. Migración Alembic

0007_create_fulfillment.py, revision 0007_fulfillment, down_revision 0006_payments.
Solo dos tablas nuevas, permisos y seis índices; 40 tablas app + alembic_version.
Cadena única: 0001_phase1 → 0002_catalog → 0003_cart → 0004_orders → 0005_kitchen
→ 0006_payments → 0007_fulfillment. No se reescribe historia 0001–0006, no se
crea esquema en startup. Downgrade aborta antes de cualquier DDL si hay datos en
asignaciones/incidencias, protegiendo su historia; no elimina historial de Orders.

## 39. Constraints

Assignments: UUID/FK RESTRICT a Orders y users; terminales excluyentes, par
unassigned_at/actor consistente, cierre >= asignación. Incidents: UUID/FK RESTRICT
a Orders/Branches/evaluador; UNIQUE order_id; umbral 900 y segundos > 900;
estado observado solo delivery operacional/DELIVERED; decisión OPEN/APPROVED/
REJECTED; procedencia de evaluación y evaluated_at >= detected_at; remediación
solo obligatoria en APPROVED; nota/descripción acotadas. Timestamps aware.

## 40. Índices

| Índice | Propósito |
| --- | --- |
| uq_delivery_assignments_active | Un activo por Order, parcial sin cierre |
| ix_delivery_assignments_history | Historia por order_id, assigned_at, id |
| ix_delivery_assignments_staff | Personal, assigned_at, id |
| ix_delivery_delay_incidents_review | branch_id, decisión, detected_at, id |
| ix_delivery_delay_incidents_recent | branch_id, detected_at, id sin filtro |
| ix_orders_pickup_release | SCHEDULED/PICKUP/PAID por sucursal, número, id |

Se reutilizan índices existentes de Orders e historial para cola delivery y
proyección de tiempos; no se agrega índice delivery redundante. La condición
de due usa requested_pickup_at y recomendación actual, no el release inicial.
Planes/latencia bajo carga requieren EXPLAIN en PostgreSQL con datos representativos.

## 41. Pruebas de dominio

Algoritmo actual y profundidad de cola, overflow, normalización estricta,
identidad no fuzzy/no sufijos, fechas aware, límites del umbral incluidos
microsegundos, DELIVERED con hora real, saturación, CANCELLED excluido, invariantes
de asignación/incidencia, responsabilidad nullable, decisiones y retries,
cuatro transiciones sobre el grafo de Orders, guardas de pago/confirmación.

## 42. Pruebas de aplicación

Liberación antes/en límite; lote cinco debidos/cinco futuros; snapshot inicial
preservado; pago/scope; identidad; asignar/reasignar/desasignar; personal inválido;
dispatch/complete sin saltos; datos históricos inmutables; evidencia de retraso
única; cursor evita inanición de páginas posteriores; decisión humana independiente
de responsabilidad; rollback y retries/carreras. Dominio + aplicación: 199 passed.

## 43. Pruebas de API

147 passed. 13 operaciones con JWT real; guest/customer/foreign/kitchen denegados;
usuario bloqueado/eliminado y permisos revocados; scope; extras body/query y
mass assignment; identidad/controles; StrictBool; paginación; estados de cola;
flujo pickup/delivery; incidentes/aprobación/retry; respuestas sin secretos.
OpenAPI contiene 12 paths y 13 operaciones con errores estándar.

## 44. Pruebas de repositorios

18 passed. SQL PostgreSQL compilado: proyección LATERAL única, historial de
entrega real, scoping, lock solo Order y SKIP LOCKED, UPDATE status-only, batch
de asignaciones, cierre condicional, ON CONFLICT sin sobrescribir evidencia,
lista estable/lock de incidencia, actualización de evaluación únicamente,
staff activo con SHARE, mapper/error seguro, no commit independiente.

## 45. Pruebas de migración

7 passed. Head único y siete revisiones; metadata de 40 tablas; SQL offline
crea únicamente dos tablas; checks/índices coinciden con ORM; FK RESTRICT/
timestamps aware; permisos solo ADMIN BRANCH; downgrade protegido y preservación
de Orders/Payments; capas sin llamadas a otros servicios ni repositorios privados.

## 46. Integración PostgreSQL preparada

tests/integration/test_phase7_postgresql.py reutiliza el guard explícito TEST:
nombre de DB con marcador test, distinta de la normal, PostgreSQL y sin objetos
de usuario antes de tocarla. Caller-owned transaction revierte DDL/datos.
Prepara migraciones 0001–0007, permisos/constraints, flujos con Kitchen real,
snapshots inmutables, UNIQUE activo, retries, FK-failure después de status y
después de historial DELIVERED, detección/evaluación y downgrade protegido/vacío.
No es prueba multi-conexión de scheduling bajo contención.

## 47. Ruff

ruff check .: PASS. ruff format --check .: PASS, 299 archivos formateados.
No nuevas dependencias ni bypass de reglas de lint.

## 48. Pytest

Baseline al iniciar: 1069 passed, 6 skipped, 0 failed, 231.22 s.
Fase 7 focalizada: 371 passed (364 módulo + 7 migración), por ejecuciones de
dominio/aplicación, API y repositorios/migración. Suite completa final:
1440 passed, 7 skipped, 0 failed, 384.42 s (6 min 24 s). Las siete omitidas son
integraciones PostgreSQL opt-in, no pruebas funcionales fallidas.
git diff --check: PASS; se comprueban también archivos nuevos sin staging.

## 49. Alembic

alembic heads: 0007_fulfillment (head), único.
alembic history: siete revisiones lineales desde 0001_phase1, con Fase 6 intacta.
SQL offline upgrade/downgrade y equivalencia de metadata verificados por tests.
No se ejecutó upgrade/stamp de la base normal.

## 50. PostgreSQL: verificado versus omitido

pytest tests/integration/test_phase7_postgresql.py -m integration -q:
1 skipped, TEST_DATABASE_URL is not configured. No validación real de migración,
índices/planes, triggers, contención entre conexiones o rollback PostgreSQL en
esta ejecución. No se interpreta skipped como passed. La base manual actual
no corresponde a la cadena Alembic (49 tablas, sin alembic_version); se preserva
sin reconciliación, stamps ni cambios destructivos. La fase no se declara
validada para producción hasta disponer de una base TEST compatible/dedicada.

## 51. Scheduler

PICKUP SCHEDULING LOGIC: IMPLEMENTADA.
AUTOMATIC PERIODIC WORKER: NO IMPLEMENTADO / PREPARADO PARA INTEGRACIÓN.

Hay caso de uso acotado, actor/permisos y SKIP LOCKED, no Celery/APScheduler,
cron ni loop en lifespan. Un futuro worker debe cerrar sesión por lote,
reintentar locks omitidos en siguiente ciclo y recorrer el cursor de detección
hasta null, reiniciándolo en 0 en cada ciclo. No se fabrica automatización externa.

## 52. Notificaciones

READY_FOR_PICKUP STATE: IMPLEMENTADO.
PUSH NOTIFICATION: PENDIENTE.

Se conserva estado que produce Kitchen. No se agrega token push, proveedor,
evento fake, bus, outbox ni NotificationService que anuncie una entrega inexistente.

## 53. Riesgos y decisiones MVP

Sin PostgreSQL TEST no hay evidencia real de DDL/contención/planes. Lote usa foto
de cola común y precisión por recomendación actual; no optimiza cocina por ítem
ni garantiza SLA real. No se reasigna después de OUT_FOR_DELIVERY. La identidad
no infiere país ni elimina acentos: formatos semánticamente distintos fallan.
La deuda previa Orders.Domain → Cart.Domain se conserva; Fulfillment no la amplía
mediante llamadas a Cart/Catalog. Datos DELIVERED ambiguos fallan de forma segura.

## 54. Pendientes explícitos

Configurar TEST_DATABASE_URL dedicada/vacía y ejecutar integración y pruebas de
contención PostgreSQL multi-conexión. Revisar planes e índices con volumen real.
Provisionar/reconciliar una base normal compatible mediante un plan separado.
Integrar worker periódico, monitoreo y alertas; elegir proveedor online de Fase 6.
Push y cualquier compensación financiera quedan para alcance posterior.

## 55. Git y programa

Misma rama chore/backend-foundation, HEAD ff8f304; no nueva rama ni cambios
de historial Git. Los archivos nuevos y modificaciones quedan en working tree,
sin staging/commit/push. Swagger existente en http://localhost:8000/docs devuelve
200 y OpenAPI publica los 12 paths de Fulfillment. GET sin JWT devuelve 401.
Estas comprobaciones son read-only; no se hicieron pedidos ni pagos contra la
base normal no migrada. No se cambió puerto ni se inició otro servidor.

## 56. Fuera de alcance y entrega

Sin frontend/app móvil, mapas/GPS, routing de repartidores, nuevo rol DRIVER,
stock, loyalty, cupones, refunds, pagos parciales, proveedor delivery, bus de
eventos, push o Fase 8. Se entrega lógica, API, persistencia/migración, pruebas y
documentación de Fase 7 en la rama indicada; límites de validación real y
automatización están diferenciados expresamente de capacidades implementadas.

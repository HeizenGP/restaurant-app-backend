# Informe de Fase 4 — Creación de pedidos

Fecha: 2026-10-06, America/Lima. Restaurant App / Chifa Asia.
Repositorio: /home/heizen27/proyectos/restaurante-backend.
Rama: chore/backend-foundation. HEAD inicial/final: 902014f.

## 1. Resumen ejecutivo

Implementado Orders en arquitectura hexagonal + vertical slicing: 14 operaciones
HTTP, once tablas nuevas, checkout atómico, snapshots históricos, idempotencia,
LOCAL/PICKUP/DELIVERY y configuración por sucursal. No se avanza a Fase 5.

Baseline verificado: árbol limpio, Fase 3 committeada en 902014f y 407 passed,
3 skipped. Prevalece la petición directa de continuar en la misma rama sobre
feat/orders del documento adjunto; no se crea rama ni staging/commit/push.

Resultado verificado: 624 passed, 4 skipped, 0 failed. Orders: 212 passed;
migración offline: 5 passed. Ruff check y format sin errores. Alembic único head
0004_orders. PostgreSQL real NO validado: TEST_DATABASE_URL no está configurada.
La base manual antigua no se tocó ni migró. Swagger continúa disponible en
http://localhost:8000/docs; mostrar endpoints no equivale a schema aplicado.

## 2. Alcance

Crear un pedido desde el ACTIVE Cart del Customer actual; consultar historial y
detalle propio; liberar un LOCAL CASH cuando requiere confirmación; configurar
settings, mesas y zonas de delivery con autorización branch-scoped.
Snapshots/totales pertenecen al Order; Cart continúa temporal, sin reservar stock
ni precio. No se exponen CRUD financiero o transiciones arbitrarias.

## 3. CU/RF cubiertos

| Requisito | Implementación dentro de Fase 4 |
| --- | --- |
| CU-06 / CU-13 | Creación, consulta y operación específica de liberación cash |
| RF-18 / RF-19 | Modalidad exclusiva y resolución LOCAL por QR de mesa |
| RF-20 / RF-21 / RF-22 | Varios pedidos por mesa, elección CASH/ONLINE y confirmación |
| RF-23 / RF-24 / RF-27 | Pickup futuro, estimador determinista y contacto histórico |
| RF-29 / RF-30 | Delivery con dirección propia y snapshots completos |
| RF-31 / RF-32 | Tres zonas globales gratuitas y zonas configurables por sucursal |
| RF-33 / RF-37 | ETA inicial y mínimo sobre subtotal de productos |
| RF-34 / RF-35 | Consulta de estado y modelo de transición; ejecución futura parcial |

RN-04..11 se respetan conforme a las reglas concretas descritas por el adjunto:
una sucursal, importes backend-side, modalidades, prepago online, zonas gratuitas,
cobertura y mínimo. No se inventan reglas adicionales por el número de RN.

## 4. Requerimientos parcialmente preparados

RF-25: release calculado/persistido y consulta de vencidos disponible, sin
despacho operativo a Kitchen. RF-26: READY_FOR_PICKUP modelado, sin push.
RF-28/RF-36: ONLINE inicia PENDING_PAYMENT y exige PAID para activarse, sin
pasarela ni confirmación real de pago. RF-34/RF-35: estados consultables y
transiciones de dominio, sin interfaz/operaciones Kitchen o reparto.

No se atribuye finalización a esas integraciones futuras.

## 5. Arquitectura

Domain: dataclasses inmutables, enums, dinero, reglas horarias y grafo de estados.
Application: OrderService, OrderSettingsService, DTO y puertos específicos.
Infrastructure: gateways Cart/Customer, authorization, estimador y repositorios
SQLAlchemy sobre la misma AsyncSession de la petición.
Presentation: schemas Pydantic, discriminated union, dependencias y routers.

Se reutilizan CurrentPrincipal/get_current_customer, decoder y resolución actual
de Auth, get_session, permisos de Branch y el envelope existente.
Orders.Application/Domain no importan ORM, HTTP ni infraestructura.
Catalog conserva el algoritmo único de precio; Cart.recalculate público no se usa.
No BaseRepository, GenericService, auth nueva ni reemplazo de tecnologías.

## 6. Archivos creados

33 archivos nuevos, incluidos seis __init__.py de Orders, el __init__.py de
pruebas y este informe. Archivos funcionales:

~~~text
app/modules/orders/domain/models.py
app/modules/orders/domain/policies.py
app/modules/orders/domain/transitions.py
app/modules/orders/application/dtos.py
app/modules/orders/application/errors.py
app/modules/orders/application/ports.py
app/modules/orders/application/services.py
app/modules/orders/infrastructure/authorization.py
app/modules/orders/infrastructure/cart.py
app/modules/orders/infrastructure/customers.py
app/modules/orders/infrastructure/scheduling.py
app/modules/orders/infrastructure/persistence/models.py
app/modules/orders/infrastructure/persistence/repositories.py
app/modules/orders/presentation/dependencies.py
app/modules/orders/presentation/router.py
app/modules/orders/presentation/schemas.py
migrations/versions/0004_create_orders.py
tests/modules/orders/conftest.py
tests/modules/orders/fakes.py
tests/modules/orders/test_domain.py
tests/modules/orders/test_services.py
tests/modules/orders/test_api.py
tests/modules/orders/test_repositories.py
tests/test_phase4_migration.py
tests/integration/test_phase4_postgresql.py
docs/phase4-report.md
~~~

## 7. Archivos modificados

11 archivos previos:

| Archivo | Cambio |
| --- | --- |
| README.md | Fase 4, contratos, defaults, fórmulas, migración y límites |
| cart/domain/models.py | Añade CHECKED_OUT; mantiene cantidad/notas/dinero |
| cart/infrastructure/persistence/models.py | Metadata del nuevo CHECK de estado |
| catalog/application/dtos.py | Nombres en selección interna, con defaults compatibles |
| catalog/application/services.py | Extrae la misma política de selección para batch; añade nombres |
| catalog/infrastructure/persistence/repositories.py | Filtro interno opcional por lote de productos |
| app/presentation/api/v1/router.py | Registra routers Orders y admin Orders |
| migrations/env.py | Registra metadata Orders |
| tests/test_phase1_migration.py | Auditoría hexagonal incluye Orders |
| tests/test_phase3_migration.py | Mantiene invariantes de 0003 sin exigir que siga siendo head |
| tests/integration/test_phase3_postgresql.py | Fija upgrade histórico a 0003_cart |

Paths cart/catalog anteriores bajo app/modules. No se modifican requirements,
.env, .env.example, Docker, puertos, Auth, Customers, Branches o migraciones
0001/0002/0003. Se preservan informes de fases anteriores.

## 8. Modelo de datos

| Tabla nueva | Responsabilidad |
| --- | --- |
| orders | Cabecera histórica, source Cart, Customer, Branch, estado y totales |
| order_items | Producto/presentación/cantidad/notas y snapshots |
| order_item_addon_options | Nombres e importes de adicionales elegidos |
| order_status_history | Estado inicial y transiciones auditables |
| order_local_details | Mesa y política cash histórica |
| order_pickup_details | Hora, release, ready y contacto |
| order_delivery_details | Dirección/recipiente/zona/fee/ETA histórica |
| restaurant_tables | Mesas branch-scoped con QR UUID |
| branch_order_settings | Configuración efectiva por sucursal |
| delivery_zones | Políticas globales y específicas de sucursal |
| order_schedule_calculations | Entradas/resultados que explican la estimación |

34 tablas de aplicación con fases anteriores; alembic_version es adicional.
Detalle exclusivo por modalidad garantizado por Application y pruebas, no por
un simple CHECK cross-table.

## 9. Orders

UUID PK; número BIGINT IDENTITY UNIQUE; source_cart_id UNIQUE FK; customer_id y
branch_id FK; mode/status/payment enums con CHECK; totales NUMERIC(18,2);
contacto snapshot; key y fingerprint privados; configuración efectiva JSONB;
created_at/updated_at/confirmed_at TIMESTAMPTZ.

branch_id procede del Cart, customer_id del principal. No son asignables.
order_number tiene secuencia real PostgreSQL, no MAX+1; huecos por rollback son
normales. Historial propio ordenado created_at DESC, id DESC; limit 1..100,
offset >=0. Pedido ajeno/inexistente produce el mismo 404 desde query scoped.

## 10. Order items

FK Order/Product/Presentation, nombres históricos hasta 150 caracteres,
quantity 1..10000, notes normalizadas y cinco importes snapshot.
line_total_snapshot = unit_price_snapshot * quantity se persiste y valida con
CHECK. Unit = presentation + addons; subtotal suma líneas. No existe endpoint
de edición o recalculate Order. GET histórico no consulta nombres/precios Catalog.

El límite técnico y reglas de notas/dinero se reutilizan de Cart sin ampliarlos.

## 11. Addon snapshots

Una fila por opción con IDs de grupo/opción, nombres e additional_price snapshot.
Se valida pertenencia, disponibilidad, límites y duplicados en Catalog. UNIQUE
(item,option) evita repetidos. La suma de opciones coincide con addons_price.
CASCADE desde OrderItem es aceptable; FK hacia Catalog usa RESTRICT.

## 12. Status history

Initial history: from_status=NULL, to_status=estado inicial.
Cash release añade from/to, actor registrado, razón fija y timestamp.
Ambos se insertan en la misma transacción de la escritura principal. No se
cambia status con history separado. El response no expone actor_user_id.

## 13. Local

QR activo resuelve mesa; debe pertenecer a la sucursal del Cart.
Inexistente/inactivo: TABLE_NOT_FOUND (404). Otra sucursal:
TABLE_BRANCH_MISMATCH (409). ONLINE → PENDING_PAYMENT.
CASH con confirmación → PENDING_CASH_CONFIRMATION; sin ella → WAITING.
payment_status siempre PENDING al crear, incluso CASH inmediato.

## 14. Restaurant tables

Branch/label/QR UUID generado por backend/active/timestamps. No UNIQUE de mesa
en Orders; múltiples compras de una mesa son independientes.
DELETE desactiva, no elimina; PATCH rotate_qr_token=true rota explícitamente.
Etiqueta y confirmación quedan copiadas en el detalle histórico; cambios futuros
de mesa no cambian pedidos anteriores.

## 15. Pickup

ONLINE implícito, PENDING_PAYMENT inicial. requested_pickup_at aware, futuro y
factible; pasado/próximo/fuera de horario → 409 PICKUP_TIME_UNAVAILABLE.
Snapshot de Customer nombre/phone en pickup details. No se solicita contacto
otra vez ni se envía a Kitchen al crear.

## 16. Scheduling

KitchenLoadEstimator reemplazable. Cuenta WAITING/PREPARING de la sucursal,
excluyendo impagos pendientes, SCHEDULED, listos y terminales.

~~~text
queue_delay = queue_depth * queue_delay_per_order_minutes
estimated_prep = default_prep_minutes + queue_delay
ready_at = requested_pickup_at - pickup_buffer_minutes
release_at = ready_at - estimated_prep
~~~

release_at < now rechaza. Persistencia de queue, base, delay, buffer, travel y
resultado. Sin IA/heurísticas opacas. branch_hours: 0=lunes, cierre exclusivo,
overnight admitido, timezone de settings; sin horarios no se inventa cierre,
con configuración parcial los días no cubiertos no están disponibles.
Consulta futura obtiene PICKUP SCHEDULED + PAID + release vencido. No scheduler.

## 17. Delivery

ONLINE implícito y PENDING_PAYMENT. Dirección buscada por id+customer_id:
ajena/inexistente → mismo 404. Snapshot de destinatario/phone, dirección,
referencia, distrito, ciudad, departamento, lat/lng, zona, fee y ETA.
Address FK nullable SET NULL permite eliminar dirección sin perder la fotografía.
Resto de FK histórica relevante usa RESTRICT.

## 18. Delivery zones

Seeds globales idempotentes: Tarapoto, Morales y La Banda de Shilcayo gratuitas.
CITEXT + trim; prioridad global gratuita activa sobre override branch pagado.
Se permite configuración de otras zonas de sucursal con tarifa y travel override.
Zonas globales son visibles al ADMIN autorizado pero no editables por las rutas
branch-scoped. Sin coincidencia activa → DELIVERY_ZONE_UNAVAILABLE (409).
No geocoding externo ni tarifa inventada.

## 19. Delivery minimum

delivery_minimum_order compara subtotal de productos, antes del fee.
29.99 no cumple mínimo 30 aunque haya cargo 10; 30.00 sí.
Rechazo 409 DELIVERY_MINIMUM_NOT_MET conserva Cart ACTIVE y no crea Order.

## 20. ETA

estimated_delivery_at = now + default_prep + queue_delay + travel.
Travel de zona si está configurado, de sucursal en caso contrario.
Se guarda como estimación inicial, no garantía; cambios de settings/cola/zona no
recalculan el histórico. No driver/map tracking.

## 21. Payment gating

PaymentMethodType ONLINE/CASH; CASH solo LOCAL. PENDING al crear.
Online no activa un pedido sin PAID: regla Domain y CHECK PostgreSQL.
Confirmar cash release no marca PAID ni simula recibo, gateway o caja.

Grafo futuro:
LOCAL → WAITING → PREPARING → READY → SERVED.
PICKUP → SCHEDULED/WAITING → PREPARING → READY_FOR_PICKUP → PICKED_UP.
DELIVERY → WAITING → PREPARING → READY → OUT_FOR_DELIVERY → DELIVERED.
Todos ONLINE comienzan PENDING_PAYMENT; CASH confirmado comienza
PENDING_CASH_CONFIRMATION. Solo cash release tiene endpoint de transición ahora.
CANCELLED se modela, sin flujo de solicitud/cancelación de esta fase.

## 22. Branch settings

Defaults efectivos: cash_confirmation=true; minimum=0.00; prep=20; queue delay
por pedido=5; pickup buffer=5; travel default=20; timezone=America/Lima.
Configurables, no constantes comerciales. Minutos 0..1440, prep mínimo 1.
Timezone validada con ZoneInfo/IANA.

GET sin fila no escribe, devuelve defaults; PATCH hace UPSERT. Bloqueo de Branch
cubre ausencia de fila; checkout SHARE, administración UPDATE, sin upgrade de
lock durante checkout. Order guarda la configuración efectiva usada, incluyendo
fallback si no estaba persistida.

## 23. Idempotency

Idempotency-Key obligatorio, ASCII [A-Za-z0-9._:-], 1..128.
UNIQUE(customer_id,key). Huella SHA256 canónica con Customer, source Cart,
modalidad, QR/address/requested time y método aplicable; timestamps UTC.
No incluye JWT, secretos ni precios de frontend.

Mismo Customer/key/payload → mismo Order; cambio → 409 IDEMPOTENCY_KEY_REUSED.
Creación/replay responden 201 consistente. Replay se resuelve antes de buscar
ACTIVE y conserva el pedido original cuando ya hay otro carrito.
Carrera UNIQUE: rollback, lectura del ganador y comparación de fingerprint.

## 24. Transactions

Una AsyncSession reutilizada por Auth, Cart gateway, Catalog y Orders.
Un commit únicamente al finalizar cabecera, líneas/opciones, detalle,
schedule/history y CHECKED_OUT. Ningún gateway confirma por su cuenta.
Fallo en item, detalle, history, checkout o commit revierte toda la unidad.
Cash release/status/history también comparten commit/rollback.

## 25. Concurrency

Contexto Customer FOR UPDATE serializa checkouts del mismo cliente; reconsulta
idempotencia después del lock. Cart FOR UPDATE compite con PATCH/recalculate/
delete/abandon que ya usan el mismo parent lock. CartItems ordenados y bloqueados.

Branch/Category/Product FOR SHARE estabilizan configuración y Catalog contra
los locks administrativos existentes, incluidos overrides aún no insertados.
Categorías/productos en orden determinista; cambio de categoría entre queries
rechaza sin adquirir otro lock fuera de orden. source Cart/key únicos son última
defensa. Dos keys distintas sobre un Cart consumido dan ORDER_ALREADY_CREATED.

Carreras de checkout probadas con sesiones transaccionales separadas sobre fakes
y SQL/locks inspeccionados. Contención real PostgreSQL multi-connection no está
validada por falta de TEST_DATABASE_URL. Locks reducen carreras, no eliminan
todo deadlock posible; fallo técnico revierte y permite retry con la misma key.

## 26. Ownership/security

Customer API requiere principal con Customer; guest y registered admitidos,
staff sin Customer rechazado. Current Auth valida firma, propósito y estado
actual de cuenta/Customer. Reutilización de key está scoped al Customer.
Queries Order/Address aplican ownership desde SQL, no comparación posterior.

extra=forbid, union por mode, query/body de operaciones sin input también
rechazan campos extra. Frontend nunca asigna precios, status, payment_status,
branch, customer, número/IDs o timestamps. No endpoint mark-paid cliente.
503 técnica no se disfraza como conflicto comercial. Envelope no expone DSN,
SQL, constraints, JWT, hashes, OTP o input rechazado.

## 27. Permissions

ORDER_MANAGE y ORDER_SETTINGS_MANAGE asignados idempotentemente a ADMIN BRANCH.
Autorización usa infraestructura actual de staff_assignments/roles/permissions,
cuenta y sucursal activas; no roles del token. ADMIN A no opera B.
ORDER_MANAGE para cash; ORDER_SETTINGS_MANAGE para settings/mesas/zonas.
Sin permisos actuales → 403. No SUPERADMIN ni nuevos roles.

## 28. Migration 0004

0004_create_orders.py, revision=0004_orders, down_revision=0003_cart.
Once tablas, índices, CHECK/FK/UNIQUE, cuatro triggers, permisos y free seeds.
Solo reemplaza ck_carts_status para ACTIVE/ABANDONED/CHECKED_OUT.
0001/0002/0003 intactas. No create_all ni migración automática en startup.

Downgrade verifica primero ausencia de CHECKED_OUT, rechaza explícitamente si
existen y no cambia historia para pasar. En TEST vacío de esos datos elimina
solo objetos Phase 4 y restaura el CHECK de 0003.

## 29. Constraints

Dinero finito/no negativo NUMERIC(18,2), NaN explícitamente rechazado.
total=subtotal+charges-discount, fee<=charges y fee=0 en LOCAL/PICKUP.
Unit=pres+addons, line=unit*qty, qty 1..10000; nombres/notas/políticas válidas.
En esta fase charges=fee, discount=0.00 por Application; sin promociones.

CHECK de enum/gating; key/fingerprint formato; free zone fee=0; coordenadas y
minutos; release<=ready<=requested. UNIQUE number/source Cart/customer key/QR,
item option y distrito por scope de zona. FK RESTRICT mayormente, addon option
CASCADE desde item y address SET NULL por snapshot.

## 30. Indexes

Orders: número/source/key únicos, branch/status/created, customer/created/id,
mode/status. Items: order/created/id; history: order/created/id.
Tables: branch/active + QR UNIQUE. Zones: índices parciales únicos para
distrito global y branch/distrito; índice cobertura branch/district/active.
Schedule: Order único, índice order/created. No unique de mesa en Orders.

## 31. Tests

212 tests Orders: Domain 62, services 68, API 59, repositories 23.
5 tests migración offline y una integración PostgreSQL opt-in.
Fakes transaccionales solo en tests; API usa Auth/JWT reales sobre doubles de
persistencia, no bypass del CurrentCustomer ni fake de pago/cocina.

Cobertura: modalidades, money/totals/qty, payment gate, QR, configuración cash,
snapshots producto/presentación/adicional/contacto/dirección/settings,
precio actual, rollback parcial/final, idempotencia/replay/carreras,
horarios/timezones/cola, fee/gratuidad/prioridad/mínimo/ETA,
permissions/ownership, schemas extra, errores, SQL/locks/batches y metadata.

Baselines anteriores permanecen con 407 pruebas. No se sustituyeron pruebas
de regresión por implementaciones vacías.

## 32. Ruff

ruff check . → All checks passed!
ruff format --check . → 206 files already formatted.
No cambios de configuración ni exclusiones para ocultar errores.

## 33. Pytest

pytest -q → 624 passed, 4 skipped, 0 failed.
pytest → 624 passed, 4 skipped, 0 failed (628 items collected).
pytest -q tests/modules/orders → 212 passed, 0 skipped, 0 failed.
pytest -q tests/test_phase4_migration.py → 5 passed, 0 skipped, 0 failed.
pytest -m integration -q → 4 skipped, 624 deselected, 0 failed;
motivo: TEST_DATABASE_URL is not configured.

Los resultados no constituyen validación PostgreSQL real. Compilación offline,
mocks SQL y HTTP/Swagger son evidencias separadas, no equivalentes a upgrade online.

## 34. Alembic heads/history

~~~text
0004_orders (head)
0003_cart -> 0004_orders (head)
0002_catalog -> 0003_cart
0001_phase1 -> 0002_catalog
<base> -> 0001_phase1
~~~

Cadena lineal y único head verificados sin conectar/modificar la base normal.

## 35. PostgreSQL real validation

NO validado por ausencia de TEST_DATABASE_URL. La integración está preparada
para DB vacía, nombre marcado test y distinta de la habitual, usando el guard
existente. Trabaja dentro de transacciones externas que revierten DDL/datos.

Verifica upgrade 0003→0004, 35 tablas con alembic_version, identidad, FK/CHECK/
UNIQUE/QR, seeds, permisos, triggers, rollback antes del commit, checkout real,
replay/ownership/cash history, rechazo de downgrade con CHECKED_OUT y downgrade
limpio 0004→0003 preservando Cart/Catalog.

No se ejecuta upgrade/current/stamp/DDL sobre la base manual antigua de unas
49 tablas incompatible con la cadena oficial. Debe usarse una base compatible
y autorizada para probar/desplegar, no inventar contenedores ni reconciliación.

## 36. Git status

Rama chore/backend-foundation, HEAD 902014f, staging vacío. 11 archivos
modificados y 33 nuevos sin seguimiento. Estado verificado de entrega:

~~~text
## chore/backend-foundation...origin/chore/backend-foundation
 M README.md
 M app/modules/cart/domain/models.py
 M app/modules/cart/infrastructure/persistence/models.py
 M app/modules/catalog/application/dtos.py
 M app/modules/catalog/application/services.py
 M app/modules/catalog/infrastructure/persistence/repositories.py
 M app/presentation/api/v1/router.py
 M migrations/env.py
 M tests/integration/test_phase3_postgresql.py
 M tests/test_phase1_migration.py
 M tests/test_phase3_migration.py
?? app/modules/orders/
?? docs/phase4-report.md
?? migrations/versions/0004_create_orders.py
?? tests/integration/test_phase4_postgresql.py
?? tests/modules/orders/
?? tests/test_phase4_migration.py
~~~

git diff --check sin errores. git diff --stat de archivos tracked se conserva
como inspección; por definición no contabiliza código nuevo untracked.
No git add/commit/push, merge, rebase, reset o cambio de rama.

## 37. Risks

Falta validación live PostgreSQL y contención real multi-connection. La base
manual no está preparada: Swagger 200 no garantiza que pueda aceptar pedidos.
El estimador es inicial y determinista, no una promesa de SLA ni reserva de
capacidad/stock. Se presupone base IANA de timezones disponible en el runtime
WSL/Linux. Futuros cambios de snapshots/config requieren evolución compatible
para seguir leyendo documentos históricos.

Locks de producto global pueden retrasar administración entre sucursales;
transacciones de checkout deben mantenerse cortas. Historias/listados cargan
colecciones en lotes, pero tamaño de líneas/opciones sigue afectando payload.
No se finge cobertura de esas condiciones mediante fakes.

## 38. Pendings

Configurar TEST_DATABASE_URL autorizada, vacía y aislada; ejecutar integración
real y pruebas multi-connection antes de despliegue. Aplicar 0004 solo a cadena
oficial compatible, previa revisión y backup. Configurar mesas/QR, horarios,
zonas y settings comerciales reales mediante permisos de sucursal.

Payments confirmará pago real; Kitchen ejecutará release/avance; Notifications
avisará recojo; Delivery operativa hará sus transiciones futuras. No se inicia
ninguna de esas fases. Reconciliación de base manual requiere trabajo y autoridad
separados; no se realizó como parte de esta implementación.

## 39. Out of scope

Pasarelas/transacciones/recibos/caja real, Yape/Plin/Culqi/Niubiz/Stripe/etc.;
refunds/invoices; Kitchen UI/tickets/despacho; push/SMS/FCM/event bus externo;
drivers/assignment/GPS/mapas; promociones/coupons/roulette; reviews; cancel
requests/compensaciones; dashboards y Fase 5. Sin dependencias nuevas.

Servidor Uvicorn existente se conserva en puerto 8000 con reload. Smoke no
mutante: /docs=200, OpenAPI con 8 paths/14 operaciones Orders,
/api/v1/orders sin JWT=401. No se usó un checkout autenticado contra la DB normal.

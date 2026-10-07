# Fase 5 — Cocina y estados

## 1. Resumen ejecutivo

Implementación backend de Kitchen desde el commit 7201466 de Fase 4, en la
rama feat/kitchen. Orders conserva la propiedad del estado y del historial.
Se agregan cuatro endpoints, autorización vigente por sucursal, tiempos derivados,
transiciones serializadas y una migración sin nuevas tablas. No se hicieron
staging, commits ni pushes; no se inició Fase 6.

## 2. Alcance

Cola, detalle operativo, iniciar preparación y marcar listo. Sin frontend,
pasarela de pagos, cancelación, atención local, entrega/recojo, scheduler,
notificaciones, dashboard, promociones, event bus ni nuevas dependencias.

## 3. CU/RF cubiertos

El documento define CU-40–CU-44 como conjunto; no se inventan títulos individuales
ausentes de la matriz disponible. RF-38: API consumible por KDS; RF-39:
modalidades diferenciadas; RF-40: espera desde history; RF-41: permisos actuales;
RF-42/RN-13: cocina no cancela; RF-43: preparación pickup hasta
READY_FOR_PICKUP; RF-44: preparación local hasta READY.
PICKED_UP y SERVED permanecen deliberadamente fuera de cocina; no se atribuye
implementación de esas etapas finales a esta fase.

## 4. Arquitectura

Vertical Slice + Hexagonal: Domain puro, Application con casos de uso y puertos,
Infrastructure con autorización/proyección PostgreSQL y Presentation con
Pydantic/FastAPI. La comprobación AST de capas ahora incluye Kitchen.
No BaseRepository ni GenericService; no ORM/HTTP en Domain/Application.

## 5. Límites Kitchen/Orders

Kitchen consume KitchenOrdersGateway y KitchenAuthorization. Orders ofrece
OrderTransitionContext y operaciones públicas internas lock_preparation_order
y record_preparation_transition. Se reutiliza validate_transition, sin copiar
su máquina de estados. El nuevo contrato admite únicamente preparación y
listo, valida actor, origen, target, confirmación y timestamps aware.
Kitchen.Infrastructure adapta ese contrato; nunca llama helpers privados de
otros slices. La lectura no reconstruye un agregado financiero Order.

## 6. Archivos creados

27 archivos nuevos:

- app/modules/kitchen/__init__.py
- app/modules/kitchen/domain/__init__.py, models.py
- app/modules/kitchen/application/__init__.py, dtos.py, errors.py, ports.py, services.py
- app/modules/kitchen/infrastructure/__init__.py, authorization.py, orders.py
- app/modules/kitchen/presentation/__init__.py, dependencies.py, schemas.py, router.py
- app/modules/orders/domain/lifecycle.py
- migrations/versions/0005_create_kitchen.py
- tests/modules/kitchen/__init__.py, conftest.py, fakes.py, test_domain.py,
  test_services.py, test_api.py, test_repositories.py
- tests/test_phase5_migration.py
- tests/integration/test_phase5_postgresql.py
- docs/phase5-report.md

## 7. Archivos modificados

9 archivos:

- README.md: documentación Kitchen, cadena y estructura actuales.
- app/modules/orders/application/ports.py: operaciones internas de preparación.
- app/modules/orders/domain/transitions.py: misma política, acepta contexto mínimo.
- app/modules/orders/infrastructure/persistence/models.py: metadata de dos índices.
- app/modules/orders/infrastructure/persistence/repositories.py: lock mínimo
  branch-scoped y UPDATE condicionado + INSERT history, sin commit interno.
- app/presentation/api/v1/router.py: registro del router Kitchen.
- tests/test_phase1_migration.py: guardia de capas extendida a Kitchen.
- tests/test_phase4_migration.py: comprueba revisión histórica y dependencias;
  el único head actual se verifica en Fase 5.
- tests/modules/orders/test_api.py: conteo OpenAPI limitado a las rutas del slice
  Orders; conserva 8 rutas/14 operaciones y las prohibiciones dentro de Orders.

Las migraciones 0001, 0002, 0003 y 0004 no se modificaron. Tampoco requirements,
pyproject, settings, .env, puertos, Docker ni lifespan.

## 8. Modelo de cola

GET /api/v1/kitchen/branches/{branch_id}/queue devuelve generated_at,
waiting[], preparing[], ready[], limit, offset y has_more.
Filtros opcionales mode y status de cocina. Limit 100 por defecto, rango 1–200;
offset 0–100000. Una página prioriza waiting, preparing, ready; cada columna
ordena timestamp de entrada ASC, order_number ASC e id ASC.
Se consulta limit+1 para has_more, pero se exponen máximo limit tarjetas.
Para colas grandes debe recorrerse la paginación; no se afirma que una página
acotada contenga todos los pedidos existentes.

## 9. Estados visibles

WAITING, PREPARING, READY para LOCAL/DELIVERY y READY_FOR_PICKUP para PICKUP.
Se exige confirmed_at no nulo y, para ONLINE, payment_status PAID.
CASH únicamente LOCAL, ya confirmado para cocina.
PENDING_PAYMENT, PENDING_CASH_CONFIRMATION, SCHEDULED, CANCELLED, SERVED,
PICKED_UP, OUT_FOR_DELIVERY y DELIVERED no aparecen.
QUEUE_STATUSES de Orders sigue siendo WAITING/PREPARING para estimar carga;
no se sustituyó por los cuatro estados visibles de la proyección Kitchen.
El detalle sigue la misma política activa: pedidos fuera de cocina devuelven 404.

## 10. Transiciones y endpoints

Bajo /api/v1/kitchen/branches/{branch_id}:

| Método | Ruta | Permiso |
| --- | --- | --- |
| GET | /queue | KITCHEN_VIEW |
| GET | /orders/{order_id} | KITCHEN_VIEW |
| POST | /orders/{order_id}/start-preparation | KITCHEN_MANAGE |
| POST | /orders/{order_id}/mark-ready | KITCHEN_MANAGE |

WAITING → PREPARING, PREPARING → target por modalidad. No saltos ni retrocesos.
POST sin body, null o {} según la convención existente; extra fields/query:
422. Actor, status, timestamp, reason y payment_status no son inputs.
Start repetido en PREPARING: 200 sin historia nueva; repetido cuando ya avanzó:
409. Mark-ready repetido en su target correcto: 200 sin historia nueva.
No hay PATCH genérico ni rutas de cancelar, pagar, servir, recoger o entregar.

## 11. LOCAL

Tarjeta incluye table_label snapshot, nunca QR. CASH inmediato de Fase 4 ya es
WAITING. CASH pendiente aparece solo después de confirm-cash-release existente.
Kitchen no libera caja ni modifica payment_status o confirmed_at.
PREPARING → READY; no SERVED.

## 12. PICKUP

Incluye requested_pickup_at y estimated_ready_at, sin contacto del cliente.
PREPARING → READY_FOR_PICKUP; no PICKED_UP.
SCHEDULED no se activa al consultar. pickup_due_for_release sigue siendo una
consulta preparada para un scheduler futuro, no implementado aquí.

## 13. DELIVERY

Incluye modalidad y estimated_delivery_at. No dirección, distrito, referencia,
teléfono, nombre, latitud ni longitud.
PREPARING → READY; no OUT_FOR_DELIVERY ni DELIVERED.

## 14. Wait time

entered_waiting_at proviene de history.to_status WAITING, incluso el initial
history NULL → WAITING. No se utiliza orders.created_at como espera.
Mientras WAITING: ahora−entrada. Desde PREPARING: inicio preparación−entrada.
Ejemplo comprobado: 12:00→12:05 = 300 segundos.

## 15. Preparation time

Antes de preparar: 0. Mientras PREPARING: ahora−inicio preparación.
Una vez listo: entrada READY/READY_FOR_PICKUP−inicio preparación.
Ejemplos comprobados: 12:04→12:10 = 360; 12:04→12:11 = 420 segundos.

## 16. Current status time

Ahora−entrada al estado actual. En listo 12:11→12:20 = 540 segundos.
Clock inyectable, default utc_now; fechas aware, TIMESTAMPTZ e ISO 8601.
Segundos enteros >=0, clamping explícito para desviaciones del reloj.
Cada tarjeta también expone generated_at; en una cola todas comparten el mismo
clock. No se persisten timers ni columnas redundantes.

## 17. Historial e integridad

Se reutiliza order_status_history, append-only. Cada cambio añade from_status,
to_status, principal.user_id, motivo interno y fecha del backend.
El response de detalle/POST muestra estados, motivo y fecha, pero no actor.
No se editan ni borran entradas previas. Falta, duplicación o desorden de los
timestamps requeridos se trata como 503 KITCHEN_HISTORY_INCONSISTENT, sin
fabricar fechas desde created_at; una transición inconsistente hace rollback.

## 18. Permisos

0005 añade KITCHEN_VIEW y KITCHEN_MANAGE, ambos para ADMIN y KITCHEN con scope
BRANCH. VIEW solo lectura; MANAGE solo comandos. No se asume implicación entre
permisos. CUSTOMER no recibe ninguno. KITCHEN no recibe ORDER_MANAGE,
ORDER_SETTINGS_MANAGE, CATALOG_MANAGE ni permisos de pago/cancelación.

## 19. Seguridad branch-scoped

Auth valida el access JWT real y la cuenta vigente; la autorización reutiliza
SQLAlchemyBranchRepository.has_permission con joins de User, Branch,
StaffAssignment, Role, RolePermission y Permission.
Requiere cuenta ACTIVE no eliminada, sucursal activa no eliminada, assignment
activo sin ended_at, branch correcto y permiso actual. No se confía en JWT roles.
Sin token: 401; Guest, Customer, staff sin permiso, bloqueado y branch no
autorizado/inactivo: 403. La sucursal inexistente devuelve 403 sin revelar su
existencia. Un pedido ajeno/ausente bajo branch autorizado: 404, filtrado en SQL.
El rol ADMIN no concede acceso global.

## 20. Concurrencia

FOR UPDATE sobre Orders con id+sucursal serializa comandos y comparte el mismo
lock que las operaciones administrativas de Orders. Se lee el estado después de
obtener el lock, no desde un objeto cacheado anterior.
UPDATE además compara status, branch, mode, método, pago y confirmación.
Dos starts o dos ready simultáneos producen un cambio real y un history;
el segundo observa el resultado y responde 200. Start contra ready conserva las
etapas. Pruebas async usan sesiones separadas y locks compartidos.
La contención multiproceso real en PostgreSQL queda pendiente de entorno TEST.

## 21. Transacciones

Application controla un único commit final. Adapter/repositorio solo execute,
add y flush. Se valida historia antes y después de escribir, antes del commit.
Un fallo tras UPDATE, insertando history o al confirmar hace rollback.
Los reintentos sin escritura también finalizan la transacción para liberar el lock.
No se llama a servicios de Cart/Catalog que confirmen transacciones ajenas.

## 22. Query performance

La proyección completa usa un solo SELECT PostgreSQL, con agregaciones JSONB
correlacionadas de items, addons e historial. No N+1, no nombres de Catalog,
no PII/finanzas cargadas en la proyección. Estado e historia usan el mismo
snapshot MVCC: un polling concurrente no mezcla snapshots de queries sucesivas.
Los tests verifican una ejecución para 0, 1 y 50 pedidos.
Aparte están la consulta de permisos y las consultas de Auth.
No locks de escritura, escrituras ni registros creados por GET.
No se afirma un benchmark ni un plan EXPLAIN validado en PostgreSQL real.

## 23. Data minimization

KitchenOrderResponse es específico, no reutiliza OrderResponse financiero.
No customer_id, emails, contactos, dirección, coordenadas, QR, precios,
subtotal, total, descuentos, delivery_fee, secretos, idempotency key,
fingerprint ni actor. Las tarjetas incluyen únicamente datos operativos y tiempos;
historial completo solo en detalle/POST. Los nombres son snapshots almacenados;
archivar o renombrar Catalog después no cambia lo que cocina prepara.
Las notas libres son las introducidas en el pedido, no una nueva fuente de PII.

## 24. Migración 0005

Archivo 0005_create_kitchen.py; revision 0005_kitchen; down_revision 0004_orders.
Crea dos permissions, cuatro relaciones ADMIN/KITCHEN y dos índices.
Cero nuevas tablas, constraints duplicados, extensiones o funciones.
34 tablas de aplicación, 35 incluyendo alembic_version en integración.
Downgrade quita índices, relaciones de esos permisos y permisos; conserva
Orders, history, Cart, Catalog, Auth, Branches y todos los estados de pedidos.
No create_all, DDL automático ni cambios destructivos de revisiones anteriores.

## 25. Índices

ix_orders_kitchen_queue: (branch_id, status, order_number, id), parcial para los
cuatro estados de cocina. Mantiene un índice operativo pequeño al crecer el
histórico; el índice previo incluye todos los estados y ordena por created_at,
que no es el timestamp de espera/preparación. La ordenación por tiempo de
historia aún necesita sort; el índice nuevo no promete evitarlo.

ix_order_status_history_entry: (order_id, to_status, created_at, id), útil para
buscar la entrada al estado actual por pedido+estado y obtener max(created_at).
El índice previo (order_id, created_at, id) se conserva para cargar toda la
historia cronológica. Metadata y DDL coinciden. Son decisiones de diseño de
consulta, pendientes de EXPLAIN/ANALYZE con volumen real y evaluación de su coste
de escritura; no se inventó una medición del planner.

## 26. Tests Domain

31 pruebas: targets por modalidad, esperas/preparación/listo, negativos,
clock/history naive, historia faltante/duplicada/desordenada, timestamps iguales,
agrupación/orden y límites. También protección del contrato interno Orders frente
a cancelación y operaciones fuera de preparación.

## 27. Tests Services

65 pruebas: lectura sin escrituras, permisos independientes, branch isolation,
404 IDOR, todos los estados excluidos, pagos/confirmación, paginación, retry,
actor, invariantes de snapshots/pago/confirmed_at, rollback, concurrencia y
snapshot de checkout conservado tras cambio de Catalog.
Los dobles representan transacciones independientes, sin bypass de la política
pública Orders.

## 28. Tests API

59 pruebas HTTPX/TestClient con JWT y AuthService reales sobre MemoryAuthRepository,
sin sustituir CurrentPrincipal. Cuatro endpoints, 401/403/404/409/422/503,
modalidades, empty body, filtros, privacidad recursiva, historial, revocación de
permiso sin renovar JWT y cuenta bloqueada. Verificación del boundary real de
sesión ante OperationalError, sin SQL/DSN privados expuestos.
Kitchen no puede llamar confirm-cash-release ni settings con sus permisos.

## 29. Tests Repository

22 pruebas: una query para 50 pedidos, filtros, scope, timestamp de ordenación,
proyección sin datos privados/Catalog, snapshots/history, FOR UPDATE mínimo,
UPDATE condicionado, append con actor, rechazo antes de SQL, errores flush,
delegación pública, autorización SQL vigente y corrupción segura.
También se construyen sin DB las fixtures de los tres modos del test de
integración, detectando incompatibilidades con el Domain aunque se omita PG.

## 30. Tests Migration

5 pruebas offline: único head y dependencias, DDL/seeds/mappings/índices,
downgrade sin tocar Orders/history, metadata sin nuevas tablas y checks
existentes compatibles. Ejecución targeted: 5 passed, 0 failed, 0 skipped.

## 31. PostgreSQL integration

tests/integration/test_phase5_postgresql.py usa exclusivamente guarded_test_url.
Sin TEST_DATABASE_URL no conecta. La guardia exige opt-in -m integration,
PostgreSQL, nombre test, base distinta de la normal y esquema vacío.
DDL/datos se ejecutan en transacción externa reversible; AsyncSession usa
savepoints. El test comprueba upgrade 0004→0005, permisos/índices, proyección,
snapshots tras archivo de Catalog, transitions LOCAL/DELIVERY/PICKUP, retry,
actor/estado/historia y rollback real por FK fallida del INSERT history después
del UPDATE. Verifica downgrade 0005→0004 conservando filas y fases previas.
Los ONLINE PAID son fixtures TEST ya confirmadas, no endpoints ni simulación de
Payments en la aplicación.
En este entorno TEST_DATABASE_URL está ausente, también en .env: integración
quedó omitida y no se tocó la base normal/manual.

## 32. Resultado Ruff

ruff check .: All checks passed! (0 errores).
ruff format --check .: 233 files already formatted (0 pendientes).

## 33. Resultado pytest

Baseline antes de cambios: 624 passed, 0 failed, 4 skipped.
Kitchen targeted: 177 passed, 0 failed.
Regresión final (pytest): 811 collected; 806 passed, 0 failed, 5 skipped,
en 102.62 segundos. Los cinco skipped son integración PostgreSQL opt-in.
Kitchen: 177 passed, 0 failed, 0 skipped.
Migración Fase 5: 5 passed, 0 failed, 0 skipped.
pytest -m integration: 5 skipped, 806 deselected, 0 failed; TEST_DATABASE_URL ausente.
Una ejecución intermedia detectó solo un conteo OpenAPI histórico demasiado
amplio; se corrigió su scope a Orders sin quitar ni debilitar invariantes.

## 34. Alembic heads

0005_kitchen (head). Único head; comando sin conectar a PostgreSQL.

## 35. Alembic history

<base> → 0001_phase1 → 0002_catalog → 0003_cart → 0004_orders → 0005_kitchen.
Lineal, sin merge revision y sin modificar migraciones anteriores.

## 36. PostgreSQL real validado o no

NO VALIDADO. pytest -m integration: 5 skipped; razón TEST_DATABASE_URL is not
configured. Ni offline DDL, mocks ni Swagger equivalen a aplicación real de
migración. No se ejecutaron upgrade, downgrade, current, stamp, drop o
reconciliación en la base manual incompatible.
La validación real y el despliegue a base compatible quedan pendientes.

## 37. Git status final

feat/kitchen, HEAD 7201466. Cambios sin staging: 9 archivos modificados y
27 nuevos. Sin commit/push; migraciones anteriores intactas.
git diff --check: correcto, sin errores de whitespace.
git diff --stat: 9 archivos tracked, 245 inserciones y 11 eliminaciones.
git diff --stat solo cuenta tracked; los nuevos archivos se contabilizan
adicionalmente con git ls-files --others --exclude-standard.

## 38. Riesgos

- Base manual normal incompatible con la cadena oficial: Swagger puede funcionar
  sin que la DB esté migrada; no usar esta fase sobre esa DB sin plan separado.
- Sin TEST_DATABASE_URL no hay validación ejecutada de DDL, SQL JSONB, locks,
  FK rollback, planner ni downgrade en PostgreSQL real.
- Cada página es coherente, pero offset entre pollings puede moverse; un KDS debe
  refrescar desde offset 0 y recorrer has_more cuando corresponda.
- Una inconsistencia histórica hace fallar la lectura con 503 de forma explícita,
  en vez de ocultarla con fechas inventadas.
- Las notas son texto libre del pedido; minimizar campos no garantiza que un
  cliente no haya escrito información personal dentro de notes.

## 39. Pendientes

Preparar TEST_DATABASE_URL aislada/vacía y ejecutar pytest -m integration.
Después, despliegue controlado de Alembic en una base compatible, prueba KDS
con polling/paginación y EXPLAIN/ANALYZE con datos representativos.
La deuda Orders.Domain→Cart.Domain detectada en Fase 4 permanece documentada;
no se efectuó refactor masivo.
Payments, scheduler de pickup, atención/fulfillment y Notifications siguen siendo
responsabilidades futuras, no bloqueos que se resuelvan fingiendo estados.

## 40. Fuera de alcance

Fase 6, frontend, Docker, cambio de puertos, sustitución de PostgreSQL,
pasarela o marcar PAID, cancelación, SERVED, PICKED_UP, OUT_FOR_DELIVERY,
DELIVERED, push/SMS, WebSocket, Redis/Kafka/RabbitMQ, reportes, descuentos,
promociones, creación de DBs, modificación de la base manual y operaciones Git
de publicación.

Comprobación HTTP no mutante: el servidor existente responde 200 en /docs y
su OpenAPI incluye las cuatro rutas Kitchen en localhost:8000. No se cambiaron
puertos ni se efectuaron operaciones autenticadas contra la base manual.

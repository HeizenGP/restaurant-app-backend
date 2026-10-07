# Informe de Fase 10 — Administración y dashboard

Fecha de verificación: 2026-10-07. Repositorio: `/home/heizen27/proyectos/restaurante-backend`.
Rama: `chore/backend-foundation`, conservada por instrucción directa del usuario,
que prevalece sobre `feat/admin` en el adjunto. Punto de partida: `6e940f4` (Fase 9).
No se ha hecho staging, commit, push ni trabajo de Fase 11.

## 1. Resumen ejecutivo

Implementados Customer administration, Staff administration, Branch administration,
horarios, overview de configuración de solo lectura y dashboard financiero.
Se incorporan 19 operaciones HTTP; las APIs anteriores se conservan. No hay una
base Admin paralela ni copias de Orders, Products o identidad.

Migración incremental `0010_admin`, dependiente de `0009_notifications`: cero
tablas nuevas, seis permisos, procedencia opcional de Customer, doce índices
y barreras transaccionales de sucursal/timezone. La validación PostgreSQL real
permanece pendiente: no existe TEST_DATABASE_URL. La base normal heredada no
ha sido migrada, estampada ni reconstruida.

## 2. Alcance

Clientes por sucursal autorizada; invitados creados sin cuenta autenticable;
edición coherente de perfil registrado; baja restringida de contacto sin uso;
asignaciones de personal sin borrar User; protección del último administrador;
creación atómica y baja lógica de sucursales; siete horarios semanales;
composición de configuración existente; métricas por fecha y timezone de sucursal.

Rutas nuevas, con prefijo `/api/v1`:

| Métodos | Ruta sin prefijo | Permiso |
| --- | --- | --- |
| GET, POST | /admin/branches | BRANCH_VIEW / BRANCH_CREATE |
| GET, PATCH, DELETE | /admin/branches/{branch_id} | BRANCH_VIEW / BRANCH_MANAGE |
| GET, PUT | /admin/branches/{branch_id}/hours | BRANCH_VIEW / BRANCH_MANAGE |
| GET, POST | /admin/branches/{branch_id}/staff | STAFF_MANAGE |
| PATCH, DELETE | /admin/branches/{branch_id}/staff/{assignment_id} | STAFF_MANAGE |
| GET | /admin/branches/{branch_id}/staff/candidates | STAFF_MANAGE |
| GET, POST | /admin/branches/{branch_id}/customers | CUSTOMER_VIEW / CUSTOMER_MANAGE |
| GET, PATCH, DELETE | /admin/branches/{branch_id}/customers/{customer_id} | CUSTOMER_VIEW / CUSTOMER_MANAGE |
| GET | /admin/branches/{branch_id}/configuration | BRANCH_VIEW |
| GET | /admin/dashboard | DASHBOARD_VIEW |

POST devuelve 201, DELETE 204, lecturas/ediciones 200. Todas exigen access JWT
registrado y autorización actual. ErrorResponse existente para 401/403/404/409/422/503.

## 3. CU cubiertos

El adjunto identifica CU-21, CU-22, CU-23, CU-24, CU-25 y CU-31 para esta fase.
La cobertura funcional corresponde a administración de clientes, personal,
sucursales, configuración, uso de Catalog/Orders existentes y dashboard.
No se inventan nombres ni una correspondencia individual de números: no se
aportó el catálogo formal de CU con sus definiciones. La trazabilidad verificable
es la matriz de APIs y ownership de este informe.

## 4. RF cubiertos

RF-49: dashboard implementado, con cobros, devoluciones, neto, volumen, productos,
modalidad y sucursal. RF-46: administración de clientes, personal y sucursales
implementada; Orders ya existente. RF-46 es PARCIAL mientras Promotions siga
pendiente. No se declara una cobertura completa de promociones ni marketing.

## 5. RF ya cubiertos por fases previas

RF-45 reutiliza Catalog y sus overrides por sucursal (Fase 2), sin reimplementar
Products. RF-47 reutiliza Orders, operaciones y Admin realtime de Fases 4–9.
RF-48 reutiliza cancellations/refunds de Fase 8. Las pruebas de regresión
incluyen identidad, catálogo, carrito, pedidos, cocina, pagos, fulfillment,
cancelaciones, refunds, notificaciones y SSE existentes.

## 6. RF-46 y estado de Promotions

Customer administration: IMPLEMENTADO. Staff administration: IMPLEMENTADO.
Branches: IMPLEMENTADO. Orders: IMPLEMENTADO EN FASES ANTERIORES.
Promotions: PENDIENTE DE SU FASE. No se añadieron tablas, descuentos ficticios,
endpoints vacíos ni una implementación de promociones bajo otra etiqueta.

## 7. Arquitectura

Vertical slices con Presentation → Application → Domain y adaptadores en
Infrastructure. Domain y puertos no dependen de FastAPI, SQLAlchemy o SQLModel.
Customers conserva sus escrituras; Branches conserva sucursales/personal;
Orders expone configuración oficial a través de un gateway público.
Admin coordina únicamente lecturas agregadas. No llama miembros privados de
otros slices, no usa un repositorio genérico y no añade un servicio omnipotente.

Archivos creados relevantes:

- `app/shared/application/administration.py`: autorización por sucursal y errores.
- `app/modules/admin/{domain,application,infrastructure,presentation}/`:
  periodos, puertos, lectura, SQL agregado, schemas y dos endpoints.
- `app/modules/customers/application/admin_{ports,services}.py`,
  `domain/administration.py`, `infrastructure/persistence/admin_repository.py`,
  `presentation/admin_{router,schemas}.py`: gestión Customer.
- `app/modules/branches/application/admin_{ports,services}.py`,
  `domain/administration.py`, `infrastructure/persistence/admin_repository.py`,
  `infrastructure/order_timezone.py`, `presentation/admin_{router,schemas}.py`.
- `app/modules/orders/infrastructure/branch_administration.py`: gateway oficial.
- `migrations/versions/0010_create_admin.py`.
- `tests/modules/admin/`, `tests/modules/branches/test_phase10_staff.py`,
  `tests/test_phase10_migration.py`, `tests/integration/test_phase10_postgresql.py`.

Archivos existentes modificados: modelos de Auth/Customers/Orders/Payments/Refunds
para índices y procedencia; puertos, servicio, repositorio, schemas y dependencias
de Branches; servicio/repositorio/dependencias de configuración de Orders;
router v1; README; fake de Branches y pruebas de migraciones 6/8/9 para mantener
sus contratos versionados al añadir la revisión 10. No se cambió ninguna
migración 0001–0009, requirements, lifespan, Docker ni migrations/env.py.

## 8. Admin slice

`AdministrationReadService` consume puertos de autorización y lectura.
`SQLAlchemyAdministrationReadRepository` implementa dashboard y configuration.
Routers registrados en v1; respuestas tipadas con Decimal y límites explícitos.
No crea User, Customer, Staff, Orders, Payments ni configuración propia.
Las escrituras administrativas están ubicadas en los slices propietarios.

## 9. Customer ownership

Customer es una identidad comercial global. Un administrador lo puede consultar
si tiene permiso en la sucursal y existe un pedido suyo allí o fue creado
administrativamente desde esa sucursal. `created_by_branch_id` es procedencia
nullable, no ownership exclusivo y no una sucursal inventada para clientes previos.
Un Customer compartido se ve en cada sucursal con relación real, sin duplicarlo.

La columna existe en metadata/migración, pero no se incluye en el mapeo ORM
ordinario de identidad: el adaptador Admin la proyecta explícitamente. Así los
select/insert de Auth no dependen de una nueva columna en pruebas de revisiones
anteriores. La promoción normal conserva la procedencia.

## 10. Customer list/detail

Filtro de ámbito SQL antes de paginar. Búsqueda opcional por prefijo literal
de nombre/email/teléfono; mínimo 2 y máximo 80 caracteres; %, _ y backslash
escapados como texto, no comodines de entrada. limit=50, máximo 100;
offset entre 0 y 10000; orden estable created_at/id descendente.
Detalle fuera de relación comercial devuelve 404.

Proyección: id, nombre comercial, first_name/last_name del registrado, teléfono,
email, is_guest, phone_verified_at y timestamps. No se exponen UserID, hashes,
direcciones, refresh/verification tokens, OTP ni secretos.

## 11. Customer creation

CUSTOMER_MANAGE. Crea exclusivamente Customer invitado con full_name, phone,
email opcional y procedencia de sucursal. No acepta user_id, is_guest,
phone_verified_at ni timestamps del cliente. No crea User ni contraseña,
no verifica contacto, no asigna CUSTOMER global y no emite credenciales.

Teléfono bajo la misma regla Fase 1: + opcional y 9–15 dígitos, sin nueva
normalización incompatible. Busca colisión en Customers y Users; unicidad
Customer protege la carrera de inserción. 409 CUSTOMER_PHONE_ALREADY_EXISTS.
El flujo OTP/registro normal puede promover ese mismo UUID posteriormente.

## 12. Customer update

Invitado: full_name/email. Registrado: first_name/last_name/email; full_name
se deriva, y no puede exceder 180 caracteres ni quedar vacío. Customer se bloquea
antes de User, y ambas escrituras se confirman en la misma transacción.
Se conserva al menos un identificador email/teléfono del User.
Cambio de email invalida email_verified_at previo; no concede verificación.
Email duplicado de otro User: 409 CUSTOMER_EMAIL_ALREADY_EXISTS.

Teléfono, user_id, proof, procedencia y campos de seguridad son inmutables desde
esta API. No hay bypass de OTP, registro, password o roles globales.
Bodies desconocidos o mezclas de nombres de invitado/registrado: 422.

## 13. Customer delete policy

Solo se borra físicamente un invitado creado por esa misma sucursal, sin User,
sin verificación telefónica y sin historia persistida. Se bloquea la fila y
se revisan Orders, Carts, Addresses, OTP vinculados por customer_id,
Notifications, Devices y CancellationRequests. No se ignoran relaciones con
CASCADE/SET NULL heredados. La FK es la barrera final ante nuevas referencias.

Registrado: 409 REGISTERED_CUSTOMER_CANNOT_BE_DELETED. Contacto histórico,
verificado, sin procedencia administrable o con relaciones: 409 CUSTOMER_HAS_HISTORY.
Un OTP no vinculado por customer_id no prueba por sí solo historia de esa identidad;
el teléfono no se usa como ownership alternativo ni como autorización.

## 14. Guest vs Registered

Guest significa user_id NULL, no usuario con contraseña temporal. Registered
significa enlace estable a User existente. Admin no transforma uno en otro.
La prueba HTTP usa JWT y Auth/OTP reales con repositorios en memoria:
crear Guest, verificar teléfono y registrar conserva CustomerUUID.
La integración preparada prueba la promoción con el adaptador SQL real.
No se borra un User desde administración comercial.

## 15. Staff management

Reutiliza `BranchService`, StaffAssignment, roles BRANCH y STAFF_MANAGE.
Las rutas históricas y los aliases Admin invocan el mismo caso de uso:
asignar, listar, actualizar y desactivar lógicamente. No se crea personal
anónimo, passwords, nuevas cuentas, payroll ni roles GLOBAL desde el formulario.

Respuesta conserva assignment y añade perfil seguro del User, estado de cuenta.
Deactivation fija ended_at; reactivation exige User actualmente ACTIVE,
no borrado, y limpia ended_at. Conserva UUID y trazabilidad.
Usuarios bloqueados/borrados y roles no BRANCH no son asignables.

## 16. Staff candidates

Búsqueda requerida de 2–80 caracteres, limit=20, máximo 100, en Users registrados
ACTIVE/no borrados, con proyección segura e indicador already_assigned.
Ámbito/STAFF_MANAGE se verifican antes de buscar. Se buscan prefijos de
nombre completo, apellido, email o teléfono. No se descarga el directorio global
completo al panel, no se expone password_hash y no se acepta búsqueda vacía.
already_assigned informa una relación existente, incluso histórica.

## 17. Last-admin protection

No se permite desactivar ni cambiar a otro rol al último ADMIN activo de
una sucursal: 409 LAST_BRANCH_ADMIN. Otro administrador cuenta solamente si
su User es ACTIVE/no borrado, assignment activo/no terminado y assigned_at
no futuro. KITCHEN, asignaciones de otra sucursal y cuentas inhabilitadas no cuentan.

Todas las mutaciones de Staff adquieren lock UPDATE de Branch y revalidan
permiso antes del assignment lock. Dos bajas concurrentes se serializan.
Tras auto-desactivarse, el actor ya no puede reactivarse a sí mismo; debe actuar
otro administrador autorizado. No se promete proteger contra deshabilitación de
cuentas por mecanismos externos a este caso de uso.

## 18. Branch management

Listado administrativo SQL-scoped por BRANCH_VIEW antes de limit/offset.
Detalle y horarios requieren permiso concreto de la sucursal actual/activa.
No se convierte un rol global CUSTOMER ni un ADMIN en una sucursal en
superadmin del restaurante. Las APIs públicas de Branches permanecen.
La baja administrativa no elimina asignaciones, pedidos ni ledger histórico.

## 19. Branch creation

BRANCH_CREATE exige un ADMIN BRANCH vigente en al menos una sucursal activa.
Una sola transacción crea Branch, siete BranchHours, BranchOrderSettings con
defaults oficiales, asignación ADMIN del creador y auditoría.
Cualquier fallo, incluido AuditRecorder o rol oficial ausente, provoca rollback.

Código trim/uppercase, 1–40 caracteres A-Z/0-9/guion/underscore; único en DB.
Precheck case-insensitive impide duplicar códigos heredados en minúsculas;
los nuevos códigos siempre uppercase y la restricción existente resuelve carreras.
No crea nuevos Users, permisos de cocina adicionales ni una cuenta bootstrap.

## 20. Branch update

Whitelist de nombre, dirección, distrito, ciudad/departamento, coordenadas,
teléfono y timezone. Coordenadas Decimal finitas y acotadas.
Code, id, is_active, deleted_at y timestamps no son editables.
Timezone IANA válida. Branch UPDATE lock y permiso revalidado bajo lock.

Cambiar timezone sincroniza BranchOrderSettings por el gateway público de Orders
dentro de la misma transacción. No se modifican precios, snapshots, horas UTC
históricas ni programaciones ya calculadas de Orders.

## 21. Branch hours

PUT sustituye la semana completa: siete días distintos 0..6, booleano is_closed,
horas locales sin tzinfo. El weekday HTTP debe ser entero, no bool/string/float.
Día cerrado requiere open_time/close_time NULL; abierto requiere ambas.
Se admiten turnos nocturnos y horas iguales, según el contrato existente;
no se introduce una regla arbitraria close > open.
Upsert transaccional bajo Branch lock; audit BRANCH_HOURS_UPDATED.

## 22. Branch deactivation

DELETE es soft: is_active=false y deleted_at. Se rechaza con
409 BRANCH_HAS_ACTIVE_OPERATIONS si hay cualquiera de los ocho estados activos
de Orders, solicitud de cancelación pendiente, delivery assignment no finalizado,
refund PENDING/PROCESSING/FAILED, pago PROCESSING/reconciliation_required
o intento CREATED/PROCESSING. Un refund FAILED sigue siendo una obligación,
no una devolución completada.

La revisión 10 añade guardas DB para coordinar deactivation con nuevos Orders.
Un pedido activo existente ya bloquea la baja; sus transiciones rutinarias no
reintroducen un lock Branch que invierta la cadena de Fulfillment.
Los históricos sobreviven, pero un assignment en Branch inactiva no concede
acceso administrativo actual. No se expone historial corporativo global implícito.

## 23. Branch reactivation si aplica

No se implementó la operación opcional de reactivación de Branch.
PATCH is_active/deleted_at está prohibido, no hay superadmin ni recuperación
global tácita. Una implementación futura necesita política explícita: ADMIN
vigente en otra Branch activa y autorización específica mantenida sobre la
Branch objetivo inactiva. No se confunde esto con reactivación de Staff, que sí existe.

## 24. Configuration ownership

Overview GET read-only, BRANCH_VIEW; no PATCH/POST genérico ni JSON duplicado.
Campos tipados: datos mínimos de Branch, Hours, configuración oficial de Orders,
conteo de mesas/zonas aplicables y resumen de productos configurados.
No crea filas al consultar. Una Branch previa sin settings devuelve los defaults
de Orders con timezone real de Branch, sin persistirlos automáticamente.

| Dato | Fuente de verdad | Escritura |
| --- | --- | --- |
| Datos/horarios | Branches / BranchHours | Admin Branches |
| Política operativa | BranchOrderSettings | API existente de Orders |
| Mesas | restaurant_tables | API existente de Orders |
| Cobertura | delivery_zones | API existente de Orders |
| Menú/disponibilidad | Catalog / branch_products | API existente de Catalog |

## 25. Catalog config reused

`/admin/catalog` mantiene Categories, Products, Presentations, AddonGroups,
AddonOptions y overrides de BranchProducts. Se reutilizan permisos/validaciones
y menú público, sin CRUD Admin duplicado ni cambios al precio histórico.
El overview informa configured_product_count; no es inventario ni un conteo
prometido de productos actualmente vendibles.

## 26. Order settings reused

`/admin/orders/branches/{branch_id}/settings` mantiene GET/PATCH y
ORDER_SETTINGS_MANAGE. El PATCH existente también sincroniza timezone con
el adaptador público de Branches, revalida permisos bajo lock y audita.
Ambos puntos de escritura respetan Branch → Settings y el mismo commit/rollback.
Triggers diferidos comprueban coherencia final, no escriben en tablas ajenas.

Defaults de BranchOrderSettings se reutilizan desde Orders; no hay copias
divergentes de cash confirmation, preparación, cola, pickup buffer,
mínimo delivery o ETA base.

## 27. Tables reused

`/admin/orders/branches/{branch_id}/tables` y sus mutaciones existentes conservan
owner, TABLE_MANAGE y reglas de QR/token/mesas de Fase 4.
Configuration muestra solamente table_count. No se duplican tablas, QR ni
endpoints de edición en Admin.

## 28. Delivery zones reused

Las rutas de delivery-zones de `/admin/orders/branches/{branch_id}` permanecen
en Orders con su permiso/validaciones. Overview cuenta zonas propias y globales
aplicables. No recalcula fees/ETA históricos ni introduce nueva cobertura,
fencing geográfico o un catálogo de zonas paralelo.

## 29. Dashboard

GET `/api/v1/admin/dashboard`, DASHBOARD_VIEW. Query opcional branch_id,
from_date y to_date; no acepta timezone del frontend. Por defecto usa el día
local actual de cada Branch autorizada. Respuesta PEN: summary, top_products,
sales_by_mode y sales_by_branch, incluyendo periodos/bounds UTC por Branch.
Máximo 31 días calendario inclusivos y 100 sucursales en un reporte.

Un filtro branch_id se aplica en SQL de autorización antes del límite; permite
consultar cualquier sucursal autorizada aunque no estuviera en las primeras 100.
Sin filtro, más de 100 devuelve 422 y solicita seleccionar una Branch, no
trunca silenciosamente ventas. No se devuelve información de ámbitos ajenos.

## 30. Gross sales

SUM(Payments.amount) solamente cuando Payments.status=PAID, filtrado por paid_at
en los bounds de Branch. Order.total no es una venta cobrada.
Incluye CASH y ONLINE cobrados y la realidad del cobro de un pedido que después
se canceló; esa salida se refleja por separado cuando se complete Refund.
No cuenta PENDING, PROCESSING, FAILED ni CANCELLED del ledger de pago.

## 31. Refunds

SUM(Refunds.amount) solamente status=REFUNDED, filtrado por refunded_at.
PENDING, PROCESSING y FAILED no reducen ventas. El periodo de devolución es
independiente del periodo del pago original: se puede devolver hoy un cobro viejo.
No se filtra por paid_at en el agregado de returns ni se duplica por OrderItems.

## 32. Net sales

net_sales = gross_sales - refunded_amount, con Decimal/numeric.
Puede ser negativo si se devuelve dinero de ventas anteriores en el periodo.
No se clamp a cero, no float y no contabilidad fiscal. Pydantic serializa importes
Decimal como strings JSON; no se convierten a float para formar respuestas.

## 33. Orders count

orders_count cuenta pedidos creados en el periodo por created_at, incluido
cancelados/no cobrados: mide volumen, no ingresos. paid_orders_count cuenta
cobros PAID por paid_at. No se fuerza que ambos conteos coincidan, ni se filtra
el volumen por estados de pago. Las fechas comerciales son deliberadamente distintas.

## 34. Top products

Top 10 por SUM(quantity) de OrderItems asociados a los pagos PAID del periodo,
excluyendo Orders.status=CANCELLED. Agrupa por product_id histórico.
Nombre tomado del snapshot elegible más reciente, con desempate paid_at,
item.created_at e item.id. No usa el nombre actual de Products ni fusiona
productos distintos con el mismo nombre.

La consulta calcula top_totals y selecciona nombres con DISTINCT ON para los
diez productos; no acumula todos los nombres en ARRAY_AGG.
Se muestran unidades, no revenue por producto ni atribución parcial de refunds.

## 35. Sales by modality

Siempre hay LOCAL, PICKUP y DELIVERY, con ceros tipados si faltan datos.
Cada modalidad aplica los mismos gross/refunded/net y conteos; no añade
modalidades del frontend ni incorpora fulfillment como fuente financiera.
Suma únicamente agregados acotados recibidos de SQL.

## 36. Sales by branch

Solo sucursales actualmente autorizadas. Cada fila incluye UUID, nombre,
timezone, fechas locales, start/end UTC y métricas. Una Branch vacía aparece
con ceros, no desaparece. Summary suma esos ámbitos y sales_by_mode comparte
los mismos hechos; no añade sucursales no autorizadas mediante joins financieros.

## 37. Timezone behavior

Reloj backend aware UTC; ZoneInfo por Branch. Límites son medianoches locales
convertidas a [start,end) UTC, sin truncar timestamps en UTC ni incluir dos veces
la medianoche final. DST puede producir días de 23/25 horas.
Fechas invertidas, rango >31, overflow extremo y reloj naive se rechazan.

Cambio de timezone afecta consultas/políticas futuras; no reescribe snapshots.
No se hace backfill de posibles discrepancias heredadas Branch/Settings: el
gateway sincroniza cambios explícitos y los triggers comprueban nuevas escrituras
de timezone. Datos previos incompatibles requieren auditoría/migración separada.

## 38. Permissions

Nuevos: CUSTOMER_VIEW, CUSTOMER_MANAGE, BRANCH_VIEW, BRANCH_MANAGE,
BRANCH_CREATE, DASHBOARD_VIEW. Seed idempotente solo a ADMIN scope=BRANCH.
STAFF_MANAGE se reutiliza; no se crea STAFF_VIEW para el mismo flujo.
KITCHEN/CUSTOMER no reciben estos grants.

JWT access identifica; la base autoriza: User ACTIVE/no borrado, assignment
vigente/activo/no terminado/no futuro, Branch activa/no borrada, role BRANCH y
Permission vigente. BRANCH_CREATE comprueba además el rol oficial ADMIN.
No confía en claims de rol congelados, body.user_id ni branch_id sin validar.

## 39. Branch isolation

Filtros SQL por permiso y Branch antes de paginar. Mutaciones concretas requieren
el ámbito seleccionado, aun si el actor es ADMIN en otra Branch.
No se carga toda la empresa para luego filtrar listas en Python.
La única combinación Python financiera suma 3 filas agregadas por Branch,
ya autorizadas por la consulta de scopes.

## 40. IDOR

Branch ajena sin permiso: 403. Customer sin relación con la Branch autorizada:
404. Assignment ID debe coincidir con branch_id; otro ámbito no se modifica.
APIs exigen CurrentRegisteredUser real; Guest, CUSTOMER, KITCHEN, JWT inválido,
expirado o User bloqueado no adquieren acceso administrativo.
Los tests HTTP no sustituyen autenticación con un Principal inventado.

## 41. Audit

SQLAlchemyAuditRecorder comparte AsyncSession de cada escritura.
Acciones: ADMIN_CUSTOMER_CREATED/UPDATED/DELETED, STAFF_ASSIGNED/UPDATED/DEACTIVATED,
BRANCH_CREATED/UPDATED/HOURS_UPDATED/DEACTIVATED y
BRANCH_ORDER_SETTINGS_UPDATED. Actor, Branch, tipo/ID y estado seguro o flags
changed_<field> quedan en audit_logs existente.

No se guardan nombres/contactos completos, direcciones, contraseñas, tokens,
OTP, DSN ni texto externo sensible en after/before de estos casos de uso.
Un fallo de auditoría impide confirmar el negocio. El dashboard no audita
cada lectura ni crea side effects.

## 42. Transactions

Application controla commit/rollback. Adapters no confirman por su cuenta.
Atomicidad de create Branch+hours+settings+assignment+audit; de Customer+User
coherentes+audit; y de cambios de Staff/Branch/settings+audit.
Errores de validación/autorización/DB/audit revierten el use case.
GETs no crean filas ni confirman escrituras.
No se mantiene una transacción dashboard entre requests, SSE o servicios externos.

## 43. Concurrency

Staff: Branch UPDATE → recheck permiso → Assignment UPDATE → audit/commit.
Protección del último ADMIN bajo ese lock común, incluyendo auto-bajas simultáneas.
Branches/settings: Branch → Settings; Customer: Customer → User.
Customer FOR UPDATE bloquea la promoción/edición concurrente normal.

Branch gate SQL: un nuevo pedido activo toma Branch FOR SHARE; deactivation toma
UPDATE y comprueba operaciones con función VOLATILE. Tras espera READ COMMITTED
la comprobación debe observar el commit anterior. Guardas SQL estructuradas
separan INSERT de OLD en UPDATE. Timezone coherence es DEFERRABLE INITIALLY DEFERRED.
Pruebas en memoria son simulaciones; solo la integración opt-in valida locks
PostgreSQL de dos conexiones. No se declara esa ejecución realizada.

## 44. Migration 0010

Archivo `0010_create_admin.py`, revision `0010_admin`, down_revision
`0009_notifications`. Cero nuevas tablas: 50 tablas aplicación/51 con Alembic.
Añade Customer.created_by_branch_id nullable, FK RESTRICT, seis permissions y
grants oficiales, doce índices, cuatro funciones y cuatro triggers.

Sin modificación de 0001–0009, sin CREATE EXTENSION nuevo, backfill destructivo,
autogenerate, stamp, create_all o migración en startup.
Downgrade falla antes de DDL si hay procedencia no NULL para no borrar trazabilidad;
sin datos propios elimina únicamente objetos/grants/columna de esta fase.

## 45. Constraints

Reutiliza unicidad Branch.code, Customer.phone, User.email/phone,
StaffAssignment y BranchHours existentes. Nuevas FK de procedencia RESTRICT,
guardas de deactivation/entrada de pedidos y coherence timezone.
Los triggers no reemplazan authorization, validación API ni servicios propietarios.
Las pruebas offline verifican DDL; ejecución real y semántica de locks pendientes.

## 46. Indexes

Doce índices nuevos, presentes también en metadata:

- ix_customers_admin_origin: procedencia + created_at/id.
- ix_orders_admin_branch_created: Branch + created_at/id.
- ix_orders_admin_customer_branch: Customer + Branch para visibilidad.
- ix_payments_admin_paid: status + paid_at + order_id.
- ix_refunds_admin_refunded: status + refunded_at + order_id.
- ix_customers_admin_name_prefix, ix_customers_admin_email_prefix,
  ix_customers_admin_phone_prefix.
- ix_users_staff_name_prefix, ix_users_staff_lastname_prefix,
  ix_users_staff_email_prefix, ix_users_staff_phone_prefix.

Expresiones/pattern_ops PostgreSQL alineados a búsquedas por prefijo.
No se añade un índice redundante a OrderItems: se reutiliza el índice por
order_id/created_at/id existente. Índices no equivalen a un plan de uso confirmado.

## 47. Performance

Dashboard financiero en UNA sentencia SQL/MVCC: CTEs separados para payments,
refunds y order volume, matriz Branch×3 modalidades y top histórico.
No join de sales×refunds×items que multiplique dinero; no SUM de órdenes
materializadas en Python; sin N+1 por Branch ni materialized view prematura.

Scoping de sucursales: una consulta adicional de autorización.
Overview usa un número fijo de lecturas oficiales (no loop por Orders).
Se preparó EXPLAIN FORMAT JSON dentro de integración TEST; no ejecutado
en el entorno actual. No se promete latencia, índice elegido ni carga benchmark
con datos reales. Límite 31 días/100 Branches y queries paginadas acotan el MVP.

## 48. Tests Domain

Periodos locales, DST 23/25 horas, 31 días y límites half-open; overflow UTC,
reloj naive; siete horarios, overnight, closed, weekday estricto/malformed;
coordenadas/strings, campos prohibidos, identidad del Customer y shapes Guest/
Registered. Domain no necesita HTTP ni PostgreSQL.

## 49. Tests Services

Autorización, scope multibranch, creación coherente, rollback en cada paso de
create Branch (incluido audit), soft delete y operaciones activas, snapshots
sin mutación, sincronización de relojes por ambos puntos de escritura.
Staff: último ADMIN, User actual, reactivación por otro actor,
asignación futura no elegible y simulación de dos bajas serializadas.

## 50. Tests API

JWT firmado y autenticación actuales, 401/403/404/409/422/503; invitados, rol
CUSTOMER/KITCHEN, User bloqueado, scopes ajenos; paginación y prefix limits;
campos extra/identidad inyectados; CRUD, horas, candidates, tipado Decimal,
overview no editable y endpoint histórico sin bypass del último ADMIN.
Promoción de invitado Admin por OTP/registro normal conservando UUID.
Repositorios de negocio en memoria no se presentan como PostgreSQL real.

## 51. Tests Repository

SQL compilado/AsyncSession mocks: scopes y permisos antes de paginate,
Customer→User lock, proyección sin secretos, coherent updates/identifier safety,
unicidad/conflictos, history/FK delete, origin metadata no mapped identity select,
candidatos acotados, last-admin current-account y casefold de código legado.
No se usa sqlite para afirmar compatibilidad PostgreSQL.

## 52. Tests Dashboard

Zero/negative net, Decimal y JSON strings, modalidades/sucursales, una sola
sentencia financiera, fechas paid_at/refunded_at/created_at independientes,
product_id histórico, snapshots y cancelados excluidos del top.
La integración preparada añade un pedido viejo cobrado y devuelto en periodo
nuevo; no inventa un paid_at anterior a created_at para simular ese caso.

## 53. Tests Migration

Head único, cadena lineal 10 revisiones, down9, cero tablas nuevas,
columna/FK, doce índices metadata/DDL, seed/grants solo ADMIN BRANCH,
guardas concurrentes y downgrade sin borrar identidad/históricos.
Pruebas 6/8 conservan su revisión fijada y excluyen únicamente el nuevo índice
propietario de F10 al comparar DDL antiguo con metadata actual.
Prueba 9 fija el segmento hasta9, no exige que9 continúe siendo el head global.

## 54. PostgreSQL integration

Dos pruebas opt-in en `tests/integration/test_phase10_postgresql.py`.
Guard requieren URL TEST distinta de la normal y DB vacía; generan schema
`phase10_test_<uuid>`, validan nombre/propietario y limpian solo lo creado allí.
No abren ni migran la DB normal como fallback.

Primera: upgrade1–10/51 tablas, perfil y promoción, atomicidad/audit failure,
Branch+Hours+Settings+ADMIN, timezone bidireccional, soft deactivation,
finanzas históricas, EXPLAIN y rechazo de downgrade con procedencia.
Segunda: dos conexiones para doble baja de ADMIN y carrera nuevo Order/baja
Branch en ambos órdenes. Preparadas, pero SKIPPED sin TEST_DATABASE_URL.

## 55. Ruff

`ruff check .`: All checks passed!
`ruff format --check .`: 430 files already formatted.
Sin noqa nuevo para esconder errores. Verificación final repetida tras
terminar documentación; no se añaden dependencies.

## 56. Pytest

Baseline antes de Fase 10: 1975 passed, 10 skipped in 319.98s.
Verificación intermedia: 2156 passed, 12 skipped in 596.28s.
Suite actual completa: **2168 passed, 12 skipped in 372.31s (0:06:12)**.
Último bloque de Admin/Customers/Branches/migration10/integration10:
228 passed, 2 skipped in 46.58s.
Los skips no son pases. Resultados finales por comando:

| Comando | Resultado exacto |
| --- | --- |
| pytest -q | 2168 passed, 12 skipped in 372.31s (0:06:12) |
| pytest tests/modules/admin -q | 181 passed in 49.69s |
| pytest tests/modules/customers -q | 24 passed in 0.35s |
| pytest tests/modules/branches -q | 17 passed in 0.13s |
| pytest tests/test_phase10_migration.py -q | 6 passed in 0.12s |
| pytest -q -m integration tests/integration/test_phase10_postgresql.py | 2 skipped in 0.09s |

La ejecución explícita de integración devuelve: TEST_DATABASE_URL is not
configured. La suite normal omite los 12 tests PostgreSQL opt-in existentes.

## 57. Alembic heads/history

`alembic heads`: 0010_admin (head), único.
Historia comprobada:

~~~text
<base> → 0001_phase1 → 0002_catalog → 0003_cart → 0004_orders
→ 0005_kitchen → 0006_payments → 0007_fulfillment
→ 0008_cancellations_refunds → 0009_notifications → 0010_admin
~~~

Es el head de las definiciones del repositorio, NO evidencia de que esté aplicado
en la base normal. No se ejecutó alembic upgrade/current/stamp sobre esa base
durante F10.

## 58. PostgreSQL real validado o skipped

SKIPPED. TEST_DATABASE_URL ausente. Falta validar upgrade/downgrade, parser
PostgreSQL, constraints, triggers, concurrency, EXPLAIN y rendimiento con DB real.
Los tests offline/mocks/JWT HTTP no sustituyen esa evidencia.

La base normal heredada identificada anteriormente tiene 49 tablas y no tiene
versión Alembic; no es el esquema versionado esperado. No se le aplicó 0010 ni
se resolvió esa incompatibilidad de manera destructiva. Requiere procedimiento
explícito de auditoría/adopción separado o una base nueva compatible autorizada.

## 59. CI status

No hay workflows .github ni .gitlab-ci en este checkout. No se lanzó, inspeccionó
ni atribuyó resultado de CI remoto. Evidencia exclusivamente local.
No se crean automatizaciones, workers ni jobs programados fuera de esta fase.

## 60. Git status

`chore/backend-foundation...origin/chore/backend-foundation` con cambios de trabajo
F10 (modificados y untracked); HEAD permanece 6e940f4. Sin cambios staged,
sin commit/push/merge/rebase ni creación de otra rama.
`git diff --check` sin errores. `git diff` de migraciones 0001–0009 vacío.
`git diff --stat` solo incluye tracked; archivos nuevos todavía untracked
también forman parte de la entrega. Inventario funcional en sección7.
Inventario verificado: 19 archivos tracked modificados y 42 archivos nuevos
untracked. Ninguna migración previa ni archivo de dependencias/arranque cambió.

Resultado de git diff --stat (solo tracked):
19 files changed, 599 insertions(+), 57 deletions(-).
git diff --cached --name-only vacío. El total de paths con cambios es 61
usando git status --porcelain=v1 -uall; incluye __init__.py y el informe.

## 61. Riesgos

Validación DB real pendiente es el riesgo principal; ningún resultado offline
prueba por sí solo los nuevos triggers o el plan financiero.
Una devolución fallida bloquea baja hasta resolver su obligación.
Deactivation no borra históricos, pero los grants inactivos no conceden acceso;
reactivación/recuperación de Branch debe tener política explícita.

Callbacks externos tardíos pueden aportar hechos financieros después de una
baja: el ledger debe conservar realidad del proveedor. Las barreras protegen
operaciones conocidas pendientes/reconciliables, no garantizan cerrar toda
posibilidad de eventos externos futuros. No hay corrección monetaria ficticia.
SSE existente avisa de Orders, no garantiza un evento por cada Refund completado:
el dashboard requiere refetch y no presume streaming financiero nuevo.
Posibles timezones heredados divergentes no se backfillean silenciosamente.

## 62. Pendientes

Configurar TEST_DATABASE_URL dedicada/vacía/distinta de normal y ejecutar
integración completa; revisar planes/latencia con volumen representativo.
Auditar base manual antes de cualquier adopción/migración; no stamp a ciegas.
Definir política opcional de Branch reactivation y recuperación del último
ADMIN si se bloquea su User por otro mecanismo.
Promotions queda para su fase; proveedor real de pagos/push y workers conservan
sus pendientes previos. No se crean credenciales bootstrap para esquivar acceso.

Uvicorn se inició con el comando normal en puerto8000; /health responde200 y
Swagger publica las19 operaciones F10. Esto valida arranque/contrato, NO
ejecución administrativa contra la base heredada incompatible.

## 63. Fuera de alcance

Frontend, promociones, marketing, inventario, payroll/HR, contabilidad/impuestos,
PDF/Excel, BI warehouse, exports, superadmin, nuevo realtime/WebSockets,
Kafka/Redis/RabbitMQ, gateway productivo ficticio, Docker y workers infinitos.
Sin CREATE ALL, migraciones en startup, limpieza de historia, schema reset,
nueva rama, commit, push ni avance a Fase11.


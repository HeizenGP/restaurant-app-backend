# Informe de Fase 3 — Carrito y cálculo de precios

Fecha: 2026-10-06, America/Lima. Proyecto Restaurant App / Chifa Asia.
Repositorio: /home/heizen27/proyectos/restaurante-backend.
Rama conservada: chore/backend-foundation. HEAD inicial/final: b2e9de5.

## 1. Resumen ejecutivo

Se implementó Cart completo dentro del alcance de Fase 3, con siete operaciones
HTTP, tres tablas de migración, snapshots monetarios por línea/opción y cálculo
Decimal de totales. Funciona para Customer invitado o registrado y utiliza la
capacidad de selección/precios existente de Catalog.

La revisión previa confirmó Fases 0/1/2 en el historial, árbol limpio y baseline
de 254 pruebas aprobadas/2 omitidas. Se respetó la instrucción directa de seguir
en la misma rama, que prevalece sobre feat/cart del documento adjunto.

Resultado final: 407 pruebas aprobadas, tres integraciones omitidas porque no
hay TEST_DATABASE_URL, Ruff sin errores y un único head 0003_cart. No se
ejecutaron migraciones sobre la base manual antigua. No se declara validación
PostgreSQL real. No se hizo staging/commit/push ni se inició Fase 4.

## 2. Alcance

Crear, consultar y abandonar el carrito activo; agregar, editar y eliminar
líneas; guardar presentación, notas y adicionales elegidos con snapshots
backend-side; recálculo explícito y atómico. Totales derivados de líneas,
cargos/descuentos cero, sin persistir subtotal/total.

Cart no genera pedidos, no reserva stock/precio y no compra. Cada POST item
crea una línea nueva, sin fusionar automáticamente configuraciones iguales.
La sucursal no se cambia: abandonar y crear otro carrito es el flujo explícito.

## 3. CU/RF cubiertos

| Requisito | Evidencia |
| --- | --- |
| CU-05 / CU-12 | Casos de uso y API del carrito actual del Customer |
| RF-15 | Cantidad, notas, presentación, adicionales y eliminación de líneas |
| RF-16 | branch_id solo en Cart; toda selección usa esa sucursal |
| RF-17 | subtotal, charges_total, discount_total, total e item_count calculados |
| RF-12 | Notas normalizadas por item, condicionadas a allows_notes de Catalog |
| RF-13 | Selección de opciones gratuitas/con costo validada y normalizada |
| RF-14 | SOLD_OUT sigue en Catalog pero no puede agregarse/revalidarse |
| RN-04/RN-05 relacionadas | Importes backend-side y aislamiento de sucursal según el alcance dado |

No se atribuyen otras reglas a RN-04/RN-05 fuera de las descritas en los
requisitos suministrados. La UI Flutter no forma parte de esta implementación.

## 4. Arquitectura

Domain es puro: dataclasses, reglas de cantidad/notas/snapshots y totales Decimal.
Application contiene DTO, puertos específicos, servicios y errores.
Infrastructure implementa PostgreSQL y el gateway hacia Catalog.
Presentation contiene schemas HTTP, dependencies y router cart.

~~~text
CurrentCustomer -> CartService -> CartRepository port -> SQLAlchemy adapter
                              -> CatalogSelectionGateway port
                                   -> CatalogService.validate_selection
Domain: Cart / CartItem / SelectedOption / CartTotals
~~~

Catalog no importa Cart. Cart.Application no importa Catalog.Infrastructure,
ORM ni HTTP. No BaseRepository, GenericService, CRUD global ni nuevo decoder JWT.
Se reutilizan get_current_customer, get_session y los errores existentes.

## 5. Archivos creados

28 archivos nuevos, incluido este informe:

~~~text
app/modules/cart/__init__.py
app/modules/cart/domain/__init__.py
app/modules/cart/domain/models.py
app/modules/cart/application/__init__.py
app/modules/cart/application/dtos.py
app/modules/cart/application/errors.py
app/modules/cart/application/ports.py
app/modules/cart/application/services.py
app/modules/cart/infrastructure/__init__.py
app/modules/cart/infrastructure/catalog.py
app/modules/cart/infrastructure/persistence/__init__.py
app/modules/cart/infrastructure/persistence/models.py
app/modules/cart/infrastructure/persistence/repositories.py
app/modules/cart/presentation/__init__.py
app/modules/cart/presentation/dependencies.py
app/modules/cart/presentation/schemas.py
app/modules/cart/presentation/router.py
migrations/versions/0003_create_cart.py
tests/modules/cart/__init__.py
tests/modules/cart/conftest.py
tests/modules/cart/fakes.py
tests/modules/cart/test_domain.py
tests/modules/cart/test_services.py
tests/modules/cart/test_api.py
tests/modules/cart/test_repositories.py
tests/test_phase3_migration.py
tests/integration/test_phase3_postgresql.py
docs/phase3-report.md
~~~

## 6. Archivos modificados

| Archivo | Motivo |
| --- | --- |
| README.md | Arquitectura, contratos, snapshots, migración y testing de Fase 3 |
| app/modules/catalog/application/dtos.py | Resultado compatible selected_options con precio validado por opción |
| app/modules/catalog/application/services.py | Expone opciones seleccionadas durante la validación existente |
| app/presentation/api/v1/router.py | Registra el router Cart |
| migrations/env.py | Importa los modelos Cart en la metadata oficial |
| tests/test_phase1_migration.py | Comprueba también independencia hexagonal de Cart |
| tests/test_phase2_migration.py | Mantiene invariantes de 0002 sin exigir que siga siendo head/fase final |
| tests/integration/test_phase2_postgresql.py | Aísla upgrade de su regresión en 0002_catalog |

No se cambiaron requirements.txt, .env, .env.example, 0001 ni 0002.
No se alteraron Auth, perfiles, sucursales, auditoría administrativa o precios
públicos de Catalog. Los contratos HTTP existentes de Catalog permanecen iguales.

## 7. Modelo de datos

carts.customer_id referencia Customer, carts.branch_id referencia Branch.
cart_items tiene cart_id, producto, presentación y snapshots; no branch_id.
cart_item_addon_options normaliza opciones concretas y su precio snapshot.

Se añade product_addon_id al mínimo solicitado de opciones seleccionadas para
reconstruir la selección original sin consultar ORM de Catalog ni perder el grupo
cuando se archiva. IDs y precio de opción vienen del resultado validado de Catalog.
No se duplican nombres, no hay JSON/arrays persistidos de UUIDs.

## 8. carts

UUID PK, customer_id UUID FK, branch_id UUID FK, status ACTIVE/ABANDONED,
created_at/updated_at TIMESTAMPTZ. Un ACTIVE por Customer protegido por UNIQUE
parcial. No subtotal, total, estado de pedido ni configuración de checkout.

POST crea solo en sucursal activa/no archivada. Segundo ACTIVE devuelve
409 ACTIVE_CART_EXISTS. DELETE marca ABANDONED; mantiene registro y líneas.
GET busca ACTIVE del Customer actual; inexistente devuelve 404 CART_NOT_FOUND.

## 9. cart_items

UUID PK; cart_id/product_id/presentation_id FK; quantity INTEGER;
notes nullable; cuatro importes snapshot NUMERIC(18,2); timestamps.
No deleted_at ni line_total persistido. DELETE físico es válido para este recurso
temporal y elimina las opciones por cascade.

quantity: 1..10000. El máximo es una protección técnica, no límite comercial
del restaurante. Notas máximo 1000 caracteres, trim y blanco -> null; saltos de
línea permitidos. Producto no se cambia en PATCH; presentation/notes/addons sí.

## 10. cart_item_addon_options

UUID PK, cart_item_id, product_addon_id, product_addon_option_id, precio snapshot
NUMERIC(18,2) y created_at. UNIQUE de item/opción, FK de item con CASCADE y FK
de grupo/opción con RESTRICT.

La opción elegida no admite cantidad independiente ni precios enviados por
cliente. Al reemplazar/recalcular selecciones se actualizan todas las filas
en la misma transacción. Opciones conservadas mantienen id y created_at.

## 11. Constraints

CHECK de status válido, quantity entre 1/10000, cada snapshot no negativo,
notes nullable normalizada y longitud limitada. CHECK exacto:
unit_price_snapshot = presentation_price_snapshot + addons_price_snapshot.

FK a Customer/Branch/Product/Presentation y Cart usa RESTRICT; opciones
seleccionadas a CartItem usan CASCADE. No se permite que un DELETE físico de
Catalog destruya carritos. Catalog continúa archivando entidades lógicamente.

La pertenencia presentación/producto y grupo/opción/producto se valida
mediante Catalog; no se añadieron constraints compuestas invasivas a Fase 2.
La suma de opciones igual a addons_price_snapshot se verifica en el dominio
y se mantiene por la transacción; no es un CHECK SQL entre filas.

## 12. Índices

| Tabla | Índice |
| --- | --- |
| carts | uq_carts_active_customer: customer_id WHERE status='ACTIVE' |
| carts | ix_carts_branch_status: branch_id/status |
| cart_items | ix_cart_items_cart_order: cart_id/created_at/id |
| cart_item_addon_options | uq_cart_item_addon_options_item_option: item/opción |

El parcial cubre la búsqueda principal del carrito actual. El de sucursal/estado
permite filtrar configuración de carrito por esa relación sin índices individuales
de estado. La UNIQUE de opciones cubre también carga por item, evitando otro
índice redundante del mismo prefijo. No se indexó cada campo por defecto.

## 13. Snapshot pricing

Catalog entrega base, presentación completa, suma de adicionales, unit y opciones
con su precio. Cart solo conserva ese resultado validado. ProductSelection añadió
selected_options con valor por defecto vacío para mantener compatibilidad.

Los snapshots usan NUMERIC(18,2), no NUMERIC(12,2) de importes individuales de
Catalog: un precio compuesto puede superar el máximo de una columna individual.
Todo cálculo es Decimal exacto; HTTP serializa siempre strings de dos decimales.

Política: ADD/PATCH usan precio actual; GET conserva snapshot; RECALCULATE
actualiza todo. Snapshot no congela precio ni garantiza disponibilidad futura.

## 14. Cálculo de subtotal

line_total = unit_price_snapshot * quantity.
subtotal = SUM(line_total). Son valores derivados, no columnas persistidas.

Prueba RF-17: 20.00 * 2 + 15.50 * 1 = 55.50. item_count = SUM(quantity), no
número de líneas; el ejemplo tiene dos líneas y tres unidades. Vacío: 0.00/0.

## 15. Cargos

charges_total = Decimal("0.00"). Presente en CartResponse, sin tabla ni input
cliente. No delivery_fee, método de pago, servicio, mesa o programación.

## 16. Descuentos

discount_total = Decimal("0.00"). No promociones, cupones o motor de descuentos;
ningún precio/discount recibido del frontend es fuente de verdad o campo aceptado.

## 17. Total

total = subtotal + charges_total - discount_total.
En esta fase total = subtotal. GET refleja snapshots persistidos, no precios
publicados después. Todos los importes del response usan formato fijo de dos
decimales, consistente con Catalog.

## 18. Integración con Catalog

CatalogSelectionGateway en Cart.Application define branch_is_active y
validate_selection. CatalogSelectionAdapter en Infrastructure convierte DTO
de Cart a Catalog y llama al caso de uso existente, sin copiar algoritmo.

La ampliación de Catalog solo expone IDs/precios de opciones ya validadas dentro
de su recorrido actual. No añade query adicional ni depende de Cart.
Cart valida coherencia de snapshots, no recalcula base/delta/availability.

Errores de selección se traducen a conflictos seguros de Cart. Fallos técnicos
SQL/dependency no se convierten en falta de producto o selección inválida:
siguen la política 503. No hay llamada de commit de Catalog desde el gateway.

## 19. Guest/registered

Ambos usan CurrentCustomer y customer_id. No se crea sesión anónima alternativa,
permiso administrativo ni ownership por user_id. Personal sin Customer recibe
rechazo de autenticación/identidad de cliente.

Se probó promoción real por /auth/otp/request, /verify y /register, conservando
customer_id. El nuevo access token registered ve el mismo cart/item; el antiguo
guest deja de validar conforme a Fase 1. No se modificó Auth ni se transfirió
cart manualmente.

## 20. Seguridad/ownership

Todas las rutas derivan Customer de la dependencia existente. No hay GET
/carts/{cart_id}. Consultas incorporan customer_id/status y las líneas se
restringen al Cart actual. Item ajeno e inexistente devuelven 404.

Requests extra=forbid; rechazan customer_id, cart_id, precios, timestamps, roles
y sucursal por item. Query params también se rechazan. PATCH solo admite
quantity, notes, presentation_id y addons; product_id es inmutable.

No body requerido en DELETE/recalculate; un JSON enviado solo puede ser null u
objeto vacío. Los imports monetarios no son aceptados ni siquiera en opciones
anidadas. JWT real, cuentas BLOCKED/DISABLED/deleted y staff sin Customer se
prueban mediante el resolver existente. No se exponen SQL, DSN o constraints.

## 21. Concurrencia

Todas las escrituras sobre Cart existente hacen SELECT FOR UPDATE del ACTIVE
del Customer; después bloquean item cuando corresponde. Orden consistente:
Cart -> CartItem. Add/PATCH/DELETE/abandon/recalculate comparten el mismo padre.

La creación concurrente se protege con índice único parcial, porque todavía no
hay Cart que bloquear. IntegrityError de uq_carts_active_customer se traduce a
ACTIVE_CART_EXISTS. Prueba con prechecks simultáneos verifica un ganador y un
conflicto usando la barrera simulada; la integración comprueba UNIQUE real.

GET es una sola SELECT sobre las tres tablas y un snapshot MVCC coherente, sin
bloqueos de escritura ni N+1. populate_existing evita valores ORM cacheados en
reutilización interna de sesión. No se afirma benchmark de contención real.

## 22. Transacciones

Application controla un commit por escritura y rollback ante error. Repository
no confirma parcialmente items u opciones. Cambios de cliente no generan
audit_logs administrativos.

Add valida antes de persistir. PATCH combina campos presentes con selección
anterior, revalida incluso si solo cambia quantity y reemplaza snapshots/opciones.
Eliminar permite quitar una línea ya inválida sin exigir disponibilidad.
updated_at usa el trigger existente; se refresca en respuestas.

## 23. Recalculate

POST explícito, sin body requerido. Bloquea Cart, carga líneas/opciones, valida
todas contra Catalog y construye candidatos antes de realizar escrituras.
Solo si todo es válido actualiza snapshots/opciones y confirma.

Una línea inválida da 409 CART_RECALCULATION_FAILED: no elimina líneas ni
deja precios parciales. Producto agotado/oculto, presentación inactiva,
grupos/opciones archivados y notas no permitidas se cubren. Fallo en segunda
escritura o commit también revierte las modificaciones anteriores.

GET no revalida, no modifica timestamp ni desaparece líneas. Checkout deberá
hacer revalidación final en su propio flujo futuro; esta fase no compra/reserva.

## 24. API

Todas las rutas tienen tag cart y security del JWT actual del Customer.

| Método y ruta | HTTP |
| --- | --- |
| POST /api/v1/cart | 201 |
| GET /api/v1/cart | 200 |
| DELETE /api/v1/cart | 204 |
| POST /api/v1/cart/items | 201 |
| PATCH /api/v1/cart/items/{item_id} | 200 |
| DELETE /api/v1/cart/items/{item_id} | 204 |
| POST /api/v1/cart/recalculate | 200 |

CartResponse: id, branch_id, status, items, subtotal, charges_total,
discount_total, total, item_count, created_at, updated_at. ItemResponse: IDs,
quantity, notes, selected_options con IDs/snapshot por opción, cuatro snapshots,
line_total y timestamps. No se devuelve ORM directamente.

Orden de líneas: created_at ASC, id ASC; opciones: created_at ASC, id ASC.
PATCH omitido conserva; notes=null limpia; addons=[] borra selección si Catalog
lo permite. quantity=0 es 422, nunca DELETE implícito. No admin-cart ni checkout.

## 25. Errores

| Código | Semántica |
| --- | --- |
| CART_NOT_FOUND | 404; no hay ACTIVE propio |
| CART_ITEM_NOT_FOUND | 404; línea ajena/inexistente |
| ACTIVE_CART_EXISTS | 409; segundo ACTIVE |
| CART_BRANCH_INVALID | 409; crear en sucursal inexistente/inactiva |
| CART_SELECTION_INVALID | 409; presentación/opciones/notas/estado inválidos |
| CART_PRODUCT_UNAVAILABLE | 409; agotado en sucursal del Cart |
| CART_RECALCULATION_FAILED | 409; revalidación inválida, sin repricing parcial |
| CART_CONFLICT | 409; integridad persistente traducida sin detalles internos |
| INVALID_CART_DATA | 422; datos inválidos en Application |
| VALIDATION_ERROR | 422; schema HTTP inválido, envelope existente |
| Códigos Auth/dependency existentes | 401/403/503 según Fases 0/1 |

No se añadieron decenas de códigos innecesarios. No se exponen observaciones
completas en logging; unexpected handler conserva solo tipos/ubicaciones.
Los secretos configurados no aparecen en el diff.

## 26. Migración 0003

Archivo migrations/versions/0003_create_cart.py.
revision=0003_cart; down_revision=0002_catalog. Upgrade explícito de tres
tablas, CHECK/FK/UNIQUE/índices y dos triggers reutilizando
restaurant_phase1_set_updated_at. Sin permisos, usuarios, extensiones o nueva
función duplicada. No create_all ni migraciones al startup.

Downgrade: cart_item_addon_options -> cart_items -> carts y sus triggers.
Conserva Customer/Branch/Catalog/permissions/audit_logs. 0001/0002 sin diff.

Los tests offline verifican tablas exactamente, invariantes, únicos, CASCADE,
cadena y downgrade acotado. La integración opt-in comprueba upgrade/head,
constraints, adaptadores y downgrade 0003 -> 0002 en transacción TEST.

## 27. Resultado Ruff

Comando: ruff check .

~~~text
All checks passed!
~~~

Exit code 0. No dependencias nuevas ni noqa para ocultar problemas.

## 28. Resultado format

Comando: ruff format --check .

~~~text
173 files already formatted
~~~

Exit code 0 con configuración existente. También se comprobó whitespace de
archivos seguidos y nuevos; no hay errores.

## 29. Resultado pytest

Pruebas nuevas sin DB: 153. Desglose:

| Archivo | Casos |
| --- | --- |
| tests/modules/cart/test_domain.py | 23 |
| tests/modules/cart/test_services.py | 56 |
| tests/modules/cart/test_api.py | 54 |
| tests/modules/cart/test_repositories.py | 16 |
| tests/test_phase3_migration.py | 4 |

Una integración opt-in nueva en tests/integration/test_phase3_postgresql.py.
Incluye 16 violaciones de constraints con SQLSTATE comprobado, carga real,
snapshots/precios, mutaciones y downgrade conservando Catalog.

~~~text
pytest tests/modules/cart -q
149 passed in 32.56s

pytest
407 passed, 3 skipped in 73.24s (0:01:13)

pytest -q -m integration
3 skipped, 407 deselected in 0.44s
~~~

Motivo de omisión explícito: TEST_DATABASE_URL is not configured. Los tres
skips son integraciones de Fases 1/2/3. Las 254 pruebas anteriores siguen
aprobadas. No se contabilizan fakes como validación PostgreSQL.

## 30. Resultado Alembic heads/history

~~~text
0003_cart (head)

0002_catalog -> 0003_cart (head), Create customer carts and backend-generated price snapshots.
0001_phase1 -> 0002_catalog, Create global catalog, branch overrides and transactional audit.
<base> -> 0001_phase1, Create Phase 1 identity, customer and branch persistence.
~~~

Un único head y cadena lineal; exit code 0. No se ejecutó alembic current,
upgrade, stamp ni downgrade contra la base normal en esta fase.

## 31. Estado PostgreSQL real

No validado. TEST_DATABASE_URL no está configurado; la integración PostgreSQL
se omitió expresamente. La compilación offline, mocks de SQL e inspección de
metadata no sustituyen ejecución de constraints PostgreSQL real.

Se reutilizó la guarda: opt-in pytest -m integration, nombre TEST, base distinta
de la normal y completamente vacía. DDL/datos viven en una transacción externa
que revierte todo; no se crean/eliminan bases, esquemas temporales o Docker.

La base manual antigua de 49 tablas/no baseline se dejó intacta; no se intentó
reconciliar ni aprovecharla para hacer pasar tests. Este problema sigue fuera
de Fase 3 y requiere una decisión independiente.

Smoke del servidor ya activo: /docs 200, /api/v1/health 200 y GET /api/v1/cart
sin JWT 401. OpenAPI muestra las siete operaciones nuevas. Esto no demuestra
funcionamiento del Cart contra el esquema manual incompatible. Uvicorn quedó
activo, sin cambiar puertos.

## 32. Git status final

Cambios sin staging en la misma rama; HEAD b2e9de5, commit de Fase 2 ya realizado
por el usuario. El agente no ejecutó switch/add/commit/push ni operaciones de
historial.

~~~text
## chore/backend-foundation...origin/chore/backend-foundation
 M README.md
 M app/modules/catalog/application/dtos.py
 M app/modules/catalog/application/services.py
 M app/presentation/api/v1/router.py
 M migrations/env.py
 M tests/integration/test_phase2_postgresql.py
 M tests/test_phase1_migration.py
 M tests/test_phase2_migration.py
?? app/modules/cart/
?? docs/phase3-report.md
?? migrations/versions/0003_create_cart.py
?? tests/integration/test_phase3_postgresql.py
?? tests/modules/cart/
?? tests/test_phase3_migration.py
~~~

Ocho archivos seguidos modificados y 28 nuevos, detallados en sección 5.

## 33. Git diff --stat

La salida no incluye los archivos nuevos porque no hubo staging.

~~~text
README.md                                   | 225 +++++++++++++++++++++++++++-
app/modules/catalog/application/dtos.py     |   8 +
app/modules/catalog/application/services.py |  11 ++
app/presentation/api/v1/router.py           |   2 +
migrations/env.py                           |   2 +
tests/integration/test_phase2_postgresql.py |   2 +-
tests/test_phase1_migration.py              |   2 +-
tests/test_phase2_migration.py              |  10 +-
8 files changed, 248 insertions(+), 14 deletions(-)
~~~

git diff --check: exit code 0, sin salida. .env, .env.example, requirements,
0001 y 0002 no tienen cambios.

## 34. Riesgos

- Falta validar online migración/adaptadores/constraints contra PostgreSQL TEST.
  Los tests están preparados, no ejecutados en esa base.
- El esquema manual antiguo no es compatible con la cadena oficial; no aplicar
  upgrade o stamp a ciegas. No se resuelve este baseline en Fase 3.
- Un carrito no reserva disponibilidad, inventario o precio; cambios de Catalog
  pueden invalidar líneas. GET conserva esas líneas, recalculate detecta el
  problema y el cliente decide modificarlas/eliminarlas.
- No se realizaron benchmarks o contención real entre conexiones PostgreSQL;
  tests estructurales verifican locks, orden y barreras únicas.
- Recalculate valida por línea con Catalog; puede requerir consultas adicionales.
  GET no tiene N+1 y carga todo en una consulta, pero el tamaño crece con líneas.
- Los IDs/snapshots quedan al abandonar el Cart, sin tarea de limpieza histórica
  automática. Su política de retención requerirá definición futura.

## 35. Pendientes

Configurar TEST_DATABASE_URL de PostgreSQL TEST vacía y ejecutar pytest -m
integration. Aplicar las migraciones solo en una base compatible, tras verificar
el entorno/baseline elegido. Reconciliación de la base manual, si se solicita,
debe ser un trabajo independiente y no destructivo.

Checkout futuro deberá reutilizar recalculate/validación final, definir su propia
transacción y política de disponibilidad/precios. No se implementa en esta fase.
Se conservan pendientes productivos previos (proveedor SMS/upload), sin ampliarlos.

## 36. Fuera de alcance

Checkout, Orders/order_items, números/estados de pedidos, Payments/métodos o
pasarelas, Delivery/tarifas/zonas, modalidades LOCAL/PICKUP/DELIVERY, mesas/QR,
direcciones de entrega/pickup scheduling, Kitchen, inventario cuantitativo,
Promotions/Coupons/Roulette, Notifications, Reviews, facturas, cancelaciones y
reembolsos. No Fase 4.

No motor de promociones ni descuentos ficticios, no cargos inventados, no nueva
sesión anónima, permiso CART_MANAGE o auditoría administrativa de cada interacción.
No cambios Docker/puertos, nuevas librerías, secretos reales, baseline manual
o commits/pushes del agente.

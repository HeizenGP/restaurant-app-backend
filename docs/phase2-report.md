# Informe de Fase 2 — Catálogo y menú

Fecha: 2026-10-06. Proyecto Restaurant App / Chifa Asia.
Repositorio local: /home/heizen27/proyectos/restaurante-backend.
Rama: chore/backend-foundation. HEAD inicial y final: bad88ee.

## 1. Resumen ejecutivo

Se implementó Catalog con arquitectura hexagonal y vertical slice: catálogo
global, menú por sucursal, administración, presentaciones, adicionales, imágenes
URL y auditoría transaccional. Se añadieron ocho modelos/tablas de migración y
25 operaciones HTTP. Se reutilizaron las capacidades de Fases 0/1.

Resultado automatizado: 254 pruebas aprobadas, 2 integraciones omitidas,
Ruff sin errores, formato correcto y cadena Alembic lineal. No se añadieron
dependencias, usuarios, credenciales, Docker ni módulos posteriores.

La implementación está lista para revisión de código, pero la aceptación
PostgreSQL online queda pendiente. No hay TEST_DATABASE_URL. La base normal
respondió al cierre, tiene 49 tablas preexistentes y no tiene alembic_version;
su esquema no es equivalente a las migraciones. No se ejecutó upgrade, stamp,
downgrade ni escrituras sobre esa base. No se presenta la compilación offline
como validación PostgreSQL real.

Se respetó la petición directa de seguir en la misma rama, que prevalece sobre
feat/catalog mencionado en el documento. No se cambió historia ni se realizó
git add, commit o push. Fase 3 no se inició.

## 2. Alcance implementado

Categorías, productos globales, metadata de imágenes, presentaciones
configurables, grupos y opciones de adicionales, disponibilidad y override
base por sucursal, menú público agrupado y detalle completo. CRUD administrativo
con archivado lógico y validación de relaciones; auditoría persistente
reutilizable para estas acciones.

Observaciones: solo allows_notes y validación interna, sin persistir notas.
Imágenes: solo URL y metadata, sin upload físico ni proveedor inventado.
El producto puede crearse incompleto, pero sin presentación activa no es público.

## 3. Requerimientos cubiertos

| Requisito | Implementación |
| --- | --- |
| CU-03 / RF-09 | Menú público agrupado y ordenado por categoría |
| RF-10 | Datos, presentación, precio efectivo y disponibilidad en detalle |
| RF-11 | Presentaciones administrables y selección validada internamente |
| RF-12 | allows_notes; notas no persistidas en Catalog |
| RF-13 | Grupos/opciones normalizados, gratuitos y con costo, límites validados |
| RF-14 | SOLD_OUT sigue visible; selección interna lo rechaza |
| CU-20 / RF-45 | Administración de categorías, productos, precios, imágenes y configuración |
| RF-02 | Mismo catálogo global, overrides sin duplicar productos por sucursal |
| RNF-09 | Auditoría de las 19 clases de escritura administrativa |

El soporte backend y los contratos están implementados. No se desarrolló UI de
selección ni persistencia de compras. La verificación online de constraints sigue
pendiente de una base TEST dedicada.

## 4. Arquitectura final

Presentation usa schemas explícitos y convierte a DTO. Application implementa
casos de uso y puertos específicos. Domain usa dataclasses/Decimal y reglas
puras, sin Pydantic, FastAPI, SQLModel, SQLAlchemy o HTTP. Infrastructure
implementa repositorio, autorización y auditoría con la sesión existente.

~~~text
app/modules/catalog/
  domain/models.py
  application/{dtos,errors,ports,services}.py
  infrastructure/authorization.py
  infrastructure/persistence/{models,repositories}.py
  presentation/{schemas,dependencies,router}.py
app/shared/application/audit.py
app/shared/infrastructure/audit/{models,repository}.py
~~~

No BaseRepository, GenericRepository, GenericService ni controlador global CRUD.
Los helpers privados de persistencia no son una abstracción CRUD pública.
La autorización y auditoría tienen puertos reemplazables; no hay otro decoder JWT.

## 5. Archivos creados

Son 31 archivos nuevos, incluido este informe. Los archivos __init__.py son
marcadores de paquetes con responsabilidades reales, no carpetas vacías.

~~~text
app/modules/catalog/__init__.py
app/modules/catalog/domain/__init__.py
app/modules/catalog/domain/models.py
app/modules/catalog/application/__init__.py
app/modules/catalog/application/dtos.py
app/modules/catalog/application/errors.py
app/modules/catalog/application/ports.py
app/modules/catalog/application/services.py
app/modules/catalog/infrastructure/__init__.py
app/modules/catalog/infrastructure/authorization.py
app/modules/catalog/infrastructure/persistence/__init__.py
app/modules/catalog/infrastructure/persistence/models.py
app/modules/catalog/infrastructure/persistence/repositories.py
app/modules/catalog/presentation/__init__.py
app/modules/catalog/presentation/dependencies.py
app/modules/catalog/presentation/router.py
app/modules/catalog/presentation/schemas.py
app/shared/application/audit.py
app/shared/infrastructure/audit/__init__.py
app/shared/infrastructure/audit/models.py
app/shared/infrastructure/audit/repository.py
migrations/versions/0002_create_catalog.py
tests/modules/catalog/__init__.py
tests/modules/catalog/conftest.py
tests/modules/catalog/fakes.py
tests/modules/catalog/test_services.py
tests/modules/catalog/test_api.py
tests/modules/catalog/test_repositories.py
tests/test_phase2_migration.py
tests/integration/test_phase2_postgresql.py
docs/phase2-report.md
~~~

## 6. Archivos modificados

| Archivo | Cambio |
| --- | --- |
| README.md | Documentación de Catalog, migraciones, contratos y pendientes |
| app/presentation/api/v1/router.py | Registro de routers público y administrativo |
| app/presentation/errors.py | Mapeo de RequestDataError a HTTP 422 |
| app/shared/application/exceptions.py | Error semántico de datos inválidos, sin HTTP |
| migrations/env.py | Importación explícita de metadata Catalog/auditoría |
| tests/test_phase1_foundation.py | Comprueba conservación de las doce tablas, admitiendo nuevas |
| tests/test_phase1_migration.py | Aísla pruebas de 0001 y comprueba independencia del dominio |
| tests/integration/test_phase1_postgresql.py | Upgrade explícito a 0001 para mantener su regresión aislada |

No se modificaron .env, .env.example, requirements.txt ni la migración 0001.
No se duplicó ni cambió comportamiento de autenticación/perfil/personal.
El error nuevo conserva el envelope y los HTTP de errores previos.

## 7. Modelo de datos

products pertenece a categories y no tiene branch_id. Sus imágenes,
presentaciones y grupos referencian product_id. Las opciones referencian
product_addon_id. branch_products relaciona el mismo producto con una sucursal.
No se almacenan listas de adicionales en JSON dentro de products.

UUID como PK en las ocho tablas nuevas; timestamps TIMESTAMPTZ. Dinero
NUMERIC(12,2)/Decimal. Seis tablas de catálogo usan deleted_at. branch_products
es configuración reemplazable, sin archivado independiente. audit_logs es
registro de eventos con actor y snapshots JSONB, no estado comercial del producto.

## 8. Tablas creadas

Estas tablas se crearán al aplicar 0002 sobre una base compatible; no se crearon
en la base normal durante el trabajo.

| Tabla | Campos principales |
| --- | --- |
| categories | name CITEXT, slug, description, sort_order, is_active, deleted_at |
| products | category_id, name, slug, description, base_price, allows_notes, estado/orden |
| product_images | product_id, url, alt_text, sort_order, is_primary, deleted_at |
| product_presentations | product_id, name, price_delta, is_default, is_active, orden |
| product_addons | product_id, name, is_required, min_select, max_select, estado/orden |
| product_addon_options | product_addon_id, name, additional_price, estado/orden |
| branch_products | branch_id, product_id, is_available, price_override |
| audit_logs | actor_user_id, branch_id nullable, action, entity_type/id, before/after_state |

La metadata final contiene veinte tablas de aplicación: doce previas más ocho.
No incluye tablas de carrito, pedidos, pagos u otros módulos posteriores.

## 9. Constraints

CHECK de precios no negativos, sort_order no negativo, nombres no vacíos, slug
válido y límites min_select >= 0, max_select >= 1, min_select <= max_select.
Todas las columnas monetarias son NUMERIC, no FLOAT/REAL/DOUBLE.

UNIQUE de categories.slug, categories.name CITEXT, products.slug y
(branch_id, product_id). Archivado no libera slug ni nombre de categoría:
se evita reutilizar una identidad lógica que pueda tener referencias históricas.

FK RESTRICT de todas las relaciones de Catalog, actor a users y branch de
auditoría a branches. entity_id de auditoría es polimórfico, sin FK a una tabla
específica. La aplicación impide escrituras cross-product y cross-group además
de la integridad referencial de PostgreSQL.

Índices únicos parciales protegen primary/default; filtros descritos en sección 10.
Los tests de integración contienen violaciones reales para estas invariantes,
pero no se ejecutaron contra una base TEST en esta sesión.

## 10. Índices

| Tabla | Índices adicionales a PK/UNIQUE |
| --- | --- |
| categories | ix_categories_public_order |
| products | ix_products_category_order |
| product_images | ix_product_images_product_order, uq_product_images_primary |
| product_presentations | ix_product_presentations_public_order, uq_product_presentations_default |
| product_addons | ix_product_addons_public_order |
| product_addon_options | ix_product_addon_options_public_order |
| branch_products | ix_branch_products_product |
| audit_logs | ix_audit_logs_actor_created, ix_audit_logs_entity_created |

Índices públicos filtran deleted_at y, donde corresponde, is_active, y ordenan
por padre/orden/nombre. uq_product_images_primary aplica a is_primary=true y
deleted_at IS NULL; imágenes no tienen is_active. El default de presentación
aplica a is_default=true, is_active=true y deleted_at IS NULL.

La UNIQUE branch/product cubre búsquedas por sucursal y par; el índice adicional
por producto cubre el sentido inverso. Auditoría prioriza las consultas por actor
y entidad con fecha. No se añadieron índices aislados redundantes de booleanos.

## 11. Migración Alembic

Archivo: migrations/versions/0002_create_catalog.py.
revision = 0002_catalog; down_revision = 0001_phase1.

Upgrade explícito y autocontenido: ocho tablas, constraints, índices, siete
triggers que reutilizan restaurant_phase1_set_updated_at y seed idempotente
CATALOG_MANAGE -> ADMIN BRANCH. No importa modelos actuales para definir DDL,
no usa create_all ni inventa otra función updated_at.

Downgrade elimina únicamente los links/permiso CATALOG_MANAGE, los siete
triggers y las ocho tablas nuevas, en orden inverso de dependencias. Conserva
0001, roles/permissions base, usuarios, clientes, sucursales, funciones y
extensiones compartidas. No se ejecutó downgrade online.

Validación offline: SQL de upgrade 0001_phase1:0002_catalog y downgrade
0002_catalog:0001_phase1, comprobando objetos, filtros e independencia de Fase 1.
No se marca ninguna base como migrada automáticamente.

## 12. Endpoints públicos

Ambos GET devuelven 200, no requieren login y exigen branch_id UUID de sucursal
activa como query parameter.

| Ruta | Contrato |
| --- | --- |
| /api/v1/catalog/menu?branch_id={uuid} | Array de categorías con productos y configuración seleccionable |
| /api/v1/catalog/products/{product_id}?branch_id={uuid} | Detalle del producto en la sucursal elegida |

Incluyen precios efectivos calculados, estado, disponibilidad, allows_notes,
imágenes/primary, presentaciones/default y grupos/options. Productos ocultos o
borrador devuelven 404. Categorías sin productos publicables se omiten.

Se consultan hasta cinco lotes más la validación de sucursal, no una consulta
por cada producto. Una prueba con cincuenta productos verifica el número
constante y el SQL con EXISTS de presentaciones, sin filtrar agotados.

## 13. Endpoints administrativos

Prefijo: /api/v1/admin/catalog. Son 23 operaciones.

| Métodos | Ruta relativa |
| --- | --- |
| GET, POST | /categories |
| PATCH, DELETE | /categories/{category_id} |
| GET, POST | /products |
| GET, PATCH, DELETE | /products/{product_id} |
| POST | /products/{product_id}/images |
| PATCH, DELETE | /products/{product_id}/images/{image_id} |
| POST | /products/{product_id}/presentations |
| PATCH, DELETE | /products/{product_id}/presentations/{presentation_id} |
| POST | /products/{product_id}/addons |
| PATCH, DELETE | /products/{product_id}/addons/{addon_id} |
| POST | /products/{product_id}/addons/{addon_id}/options |
| PATCH, DELETE | /products/{product_id}/addons/{addon_id}/options/{option_id} |
| GET, PUT | /branches/{branch_id}/products/{product_id} |

POST 201, GET/PATCH/PUT 200 y DELETE lógico 204. PUT usa UPSERT. GET de
configuración sin registro devuelve disponibilidad true y override null.
PATCH no admite body vacío ni campos extra; null solo limpia description/alt_text.
PUT exige is_available; price_override omitido o null restablece herencia.

Detalle administrativo contiene raw product/category y colecciones no archivadas,
incluidas inactivas, con is_publicable. Los listados excluyen archivados. No se
exponen ORM directamente. OpenAPI incluye response models, errores y tags
catalog/admin-catalog; prueba automatizada verifica las 25 operaciones.

## 14. Seguridad

Se reutilizan CurrentPrincipal, Bearer, decoder JWT, firma/tipo/expiración y
validación actual de cuenta de Fase 1. Los tests HTTP usan JWT reales firmados
con configuración exclusivamente de test; no sustituyen el principal por UUID
arbitrario. No se introdujo otra librería de autenticación.

No autenticado: 401. Guest, cliente sin autorización y personal sin permiso:
403. Cuenta BLOCKED/DISABLED/eliminada: rechazo inmediato. Asignación terminada,
inactiva, permiso revocado o sucursal no válida tampoco autoriza.

Los schemas excluyen id/timestamps/deleted_at, roles, permisos y auditoría de las
entradas. IntegrityError se traduce a conflictos seguros; SQL y DSN no salen al
cliente. URLs no permiten credenciales embebidas. Se comprobó que los cambios
no contienen los secretos configurados; .env permanece fuera del diff.

## 15. Autorización por sucursal

Global: cuenta registrada activa y al menos una asignación ADMIN BRANCH
activa/no terminada con CATALOG_MANAGE en una sucursal activa/no archivada.
Esto permite administrar el menú común sin crear SUPERADMIN ni rol global
nuevo. Se exige ADMIN explícitamente además del permiso.

Configuración de sucursal: autorización actual con CATALOG_MANAGE en
exactamente branch_id de la ruta, reutilizando SQLAlchemyBranchRepository.
Un ADMIN de A recibe 403 al intentar cambiar la configuración de B.
Sucursales inexistentes/inactivas responden 404 antes de leer/escribir productos.

Los permisos no se toman del JWT. La revocación se refleja en la siguiente
petición aunque el access token no expire. El puerto de autorización permite
incorporar una política global futura sin reescribir los casos de uso.

## 16. Modelo de precios

~~~text
base efectiva = COALESCE(branch_products.price_override, products.base_price)
precio presentación = base efectiva + product_presentations.price_delta
precio selección interna = precio presentación + suma de additional_price
~~~

Con base 20.00 y delta 15.00: 35.00; override 22.00: 37.00.
Delta/override/additional_price son Decimal no negativos, máximo dos decimales.
Los importes almacenados caben en NUMERIC(12,2); sumas calculadas no se guardan
en esas columnas y pueden superar el máximo de una columna individual.

Las respuestas serializan strings con dos decimales. No existe entrada de
precio efectivo o total del frontend. validate_selection usa únicamente IDs y
datos actuales del repositorio como fuente de verdad.

## 17. Disponibilidad

Sin configuración por sucursal, disponibilidad true y precio global.
Con is_available=false, estado SOLD_OUT y producto visible. Un override no
duplica products ni cambia otra sucursal.

INACTIVE y ARCHIVED son globales y ocultos; ARCHIVED tiene prioridad al derivar
estado. Categorías inactivas/archivadas ocultan sus productos. Archivar categoría
con productos activos no archivados devuelve 409 CATEGORY_HAS_ACTIVE_PRODUCTS,
sin cascade silencioso. Los tests cubren estas diferencias y aislamiento de
override entre dos sucursales.

## 18. Presentaciones

Se administran nombres y deltas, sin hardcodear Personal/Familiar. Producto
publicable necesita al menos una presentación activa/no archivada. Crear
producto sin ella es válido como borrador; no aparece en menú/detalle público.

Como máximo una default activa/no archivada. Cambiar default desmarca la
anterior transaccionalmente; reactivar una default también aplica esa regla.
Archivar la última presentación oculta el producto sin archivarlo.
Una presentación no puede seleccionarse ni modificarse con otro product_id.

## 19. Adicionales

Grupos y opciones normalizados, configurables y ordenados. additional_price
0.00 es gratuito; valores positivos tienen costo. Solo grupos/opciones activos
no archivados se exponen públicamente.

validate_selection comprueba grupo del producto, opción del grupo, duplicados,
mínimo/máximo y obligatoriedad. Un grupo required exige al menos una opción,
aunque min_select sea cero. No obliga a completar grupos al crear el producto;
el mínimo de publicación exigido por la especificación es una presentación.
Si la configuración required no tiene suficientes opciones, la selección falla.

PATCH parcial combina límites nuevos con persistidos antes de validar; min > max
responde 422 INVALID_CATALOG_DATA. No se persiste selección de adicionales.

## 20. Imágenes

URL HTTP(S), alt_text opcional, sort_order e is_primary. Pydantic valida URL,
longitud y ausencia de username/password. Domain también protege esquema HTTP(S).
Solo metadata se almacena en PostgreSQL; la API no descarga las URLs.

Cambiar primary desmarca otras imágenes no archivadas en la misma transacción,
bloqueando el producto. No hay upload, binarios en DB, carpeta productiva ni
S3/Cloudinary/Firebase/MinIO. El proveedor físico queda para otro adaptador cuando
se decida explícitamente.

## 21. Auditoría

Puerto AuditRecorder en shared/application y adaptador SQLAlchemy en
shared/infrastructure/audit. Comparte AsyncSession con la operación; recorder
solo agrega el evento, sin commit independiente.

Acciones: CATEGORY, PRODUCT, PRODUCT_IMAGE, PRODUCT_PRESENTATION, PRODUCT_ADDON
y PRODUCT_ADDON_OPTION, cada una con CREATED/UPDATED/ARCHIVED; además
BRANCH_PRODUCT_UPDATED. Total: 19 clases de evento.

Actor de principal autorizado, entidad/id, snapshots antes/después y fecha.
branch_id solo se informa para configuración por sucursal; global usa null.
UUID y Decimal se representan como strings y fechas como ISO. No incluye
secretos, hashes, OTP, JWT o encabezados. Las pruebas comprueban snapshots,
eventos de las operaciones y rollback sin evento huérfano.

## 22. Transacciones

Cada escritura autoriza, valida, bloquea padres necesarios, aplica cambios,
agrega auditoría y confirma una sola vez. Error de regla, integridad, auditoría
o commit provoca rollback de la operación completa.

Producto FOR UPDATE serializa edición de hijos, archivo y UPSERT por sucursal.
Categoría FOR UPDATE protege archivo y altas/movimientos de productos. En
ediciones de producto se toma primero categoría y después producto; si la
categoría cambia concurrentemente respecto a la lectura inicial, se devuelve
conflicto seguro en vez de bloquear en orden inverso.

populate_existing evita usar estado ORM anterior al bloqueo. Los índices únicos
parciales son la última defensa de primary/default y ON CONFLICT garantiza el
par branch/product. updated_at procede del trigger existente y refresh recoge
su valor. No se añadieron locks de tablas ni locks sin relación con la escritura.

Estas protecciones se comprobaron en tests de SQL y fakes transaccionales. No se
afirma prueba de contención concurrente contra PostgreSQL real.

## 23. Tests creados

| Archivo | Casos parametrizados / cobertura |
| --- | --- |
| tests/modules/catalog/test_services.py | 47: reglas, menú, estados, precios, selección, ownership, autorización y rollback |
| tests/modules/catalog/test_api.py | 44: contratos HTTP, JWT real, CRUD, auditoría, permisos y payloads inválidos |
| tests/modules/catalog/test_repositories.py | 18: SQL, lotes, filtros, bloqueos, UPSERT, integridad y recorder |
| tests/test_phase2_migration.py | 4: metadata, cadena, upgrade/downgrade offline |
| tests/integration/test_phase2_postgresql.py | 1 opt-in: upgrade head, constraints reales y adaptador/auditoría |

Total nuevo: 113 pruebas sin DB y una integración opt-in. Se mantienen las
141 pruebas anteriores y su integración. La integración nueva rechaza precios
negativos, slugs/nombre/par duplicados, dos primary/default, límites inválidos,
FK inválida y comprueba las ocho tablas y CATALOG_MANAGE.

Las integraciones requieren base TEST vacía distinta de la normal, no crean
bases ni contenedores y revierten DDL/datos con una transacción externa.
El adaptador real se ejecutaría dentro de savepoints de esa transacción.

## 24. Resultado ruff check

Comando: ruff check .

~~~text
All checks passed!
~~~

Exit code 0. Sin noqa añadidos para ocultar problemas ni cambios de dependencias.

## 25. Resultado ruff format --check

Comando: ruff format --check .

~~~text
145 files already formatted
~~~

Exit code 0. El formateo usa la configuración existente.

## 26. Resultado pytest

Comando final: pytest.

~~~text
254 passed, 2 skipped in 20.74s
~~~

Ambas omitidas son integraciones opt-in. pytest -q -m integration:

~~~text
2 skipped, 254 deselected in 0.18s
~~~

Motivo explícito: TEST_DATABASE_URL is not configured. Se verificaron también
las 109 pruebas del módulo Catalog por separado: 109 passed in 22.80s;
Catalog y migración juntos: 113 passed in 14.11s.
Todos los tests de Fases 0/1 siguen pasando. No se sustituyó PostgreSQL real por
SQLite ni se contabilizan fakes como constraints PostgreSQL ejecutados.

## 27. Resultado alembic heads

~~~text
0002_catalog (head)
~~~

Exit code 0, un único head.

## 28. Resultado alembic history

~~~text
0001_phase1 -> 0002_catalog (head), Create global catalog, branch overrides and transactional audit.
<base> -> 0001_phase1, Create Phase 1 identity, customer and branch persistence.
~~~

Exit code 0; cadena lineal. alembic current contra la base normal respondió
sin revision ID, coherente con la ausencia de alembic_version.

## 29. Estado de prueba PostgreSQL real

No se validó el upgrade ni los constraints nuevos contra PostgreSQL de test.
TEST_DATABASE_URL no está configurado; ambas integraciones se omitieron.
La inspección de la base normal fue solo lectura, no una prueba de migración.

Al cierre TCP 127.0.0.1:5432, conexión SQL y readiness respondieron. La inspección
mostró 49 tablas preexistentes, las doce tablas con nombres de Fase 1, cinco
nombres que se solapan con Fase 2 y muchos objetos de fases posteriores.
No se crearon esos objetos en esta implementación. No hay alembic_version.
Hay diferencias que impiden tratar ese esquema como equivalente:

| Objeto existente | Diferencia relevante con modelos/migraciones |
| --- | --- |
| categories | Falta slug; existe parent_id |
| products | Faltan slug, allows_notes y sort_order; existen sku/estimated_prep_minutes |
| product_images | image_url en lugar de url; faltan updated_at/deleted_at |
| branch_products | Sin id UUID; campo extra unavailable_reason |
| audit_logs | PK BIGINT; before_data/after_data en lugar de before_state/after_state |
| product_presentations, product_addons, product_addon_options | No existen |
| Algunas tablas Fase 1 | Diferencias de nullability; equivalencia tampoco demostrada |

No se aplicó 0001 ni 0002 sobre esta base, ni stamp, rename, drops o reconciliación.
La mera existencia de tablas o readiness=200 no garantiza compatibilidad del
catálogo. Se necesita TEST_DATABASE_URL para validar online y, para usar la
base preexistente, una reconciliación no destructiva aprobada, con backup y
comparación completa de constraints/índices/datos.

Smoke del proceso Uvicorn activo: /docs 200, /api/v1/health 200,
/api/v1/health/ready 200. OpenAPI expone 25 operaciones de Catalog. Menú sin
branch_id devuelve 422; con UUID inexistente devuelve 404 BRANCH_NOT_FOUND;
administración sin JWT devuelve 401. Estas comprobaciones no demuestran un
menú funcional contra el esquema incompatible ni una compra.

## 30. Git status final

Rama y HEAD conservados, cambios sin staging/commit. La salida usa ?? para
directorios completos, por lo que el inventario de la sección 5 detalla sus archivos.

~~~text
## chore/backend-foundation...origin/chore/backend-foundation
 M README.md
 M app/presentation/api/v1/router.py
 M app/presentation/errors.py
 M app/shared/application/exceptions.py
 M migrations/env.py
 M tests/integration/test_phase1_postgresql.py
 M tests/test_phase1_foundation.py
 M tests/test_phase1_migration.py
?? app/modules/catalog/
?? app/shared/application/audit.py
?? app/shared/infrastructure/audit/
?? docs/phase2-report.md
?? migrations/versions/0002_create_catalog.py
?? tests/integration/test_phase2_postgresql.py
?? tests/modules/catalog/
?? tests/test_phase2_migration.py
~~~

No git add, commit, push, merge, rebase, reset o cambios destructivos.

## 31. Git diff --stat

Salida de archivos ya seguidos por Git; los nuevos no aparecen porque se dejaron
sin staging. El inventario de la sección 5 incluye los 31 nuevos por separado.

~~~text
README.md                                   | 283 ++++++++++++++++++++++++++--
app/presentation/api/v1/router.py           |   4 +
app/presentation/errors.py                  |   3 +
app/shared/application/exceptions.py        |   6 +
migrations/env.py                           |  12 +-
tests/integration/test_phase1_postgresql.py |   2 +-
tests/test_phase1_foundation.py             |   4 +-
tests/test_phase1_migration.py              |  18 +-
8 files changed, 306 insertions(+), 26 deletions(-)
~~~

git diff --check: exit code 0, sin errores de whitespace.

## 32. Riesgos y pendientes

1. Ejecutar pytest -m integration con TEST_DATABASE_URL de una base PostgreSQL
   TEST vacía. Hasta entonces la migración y los constraints no tienen
   validación online y la aceptación completa queda pendiente.
2. La base normal preexistente no es equivalente a 0001/0002. No ejecutar upgrade
   ni stamp a ciegas. Reconciliar requiere un trabajo autorizado aparte, backup y
   análisis de datos/objetos; no borrar tablas de fases posteriores.
3. Aplicar la migración en el entorno elegido solo tras validar su baseline,
   con permisos de extensiones heredados de Fase 1. No se hizo despliegue.
4. Para administración real, aprovisionar un User/asignación ADMIN por el flujo
   seguro existente; la migración no crea cuentas ni contraseña por defecto.
5. Un producto requiere al menos una presentación activa para ser público;
   grupos obligatorios incompletos impedirán selección hasta completarse.
6. Imágenes son URLs suministradas, no servicio de almacenamiento. Upload,
   permisos de acceso del proveedor y disponibilidad externa son futuros.
7. La validación interna no reserva disponibilidad ni congela precios. Cart/Orders
   deberán revalidar en su propio flujo; no se garantiza stock desde una lectura.
8. El catálogo global permite gestión desde cualquier ADMIN válido de sucursal,
   conforme a la decisión explícita del requerimiento. Un rol global futuro debe
   incorporarse en el puerto, no en claims JWT.
9. El menú no implementa paginación; consultas son por lotes constantes, pero
   el volumen de respuesta crece con el catálogo.
10. Persisten los pendientes históricos de Fase 1, como el proveedor SMS
    productivo, sin ser reimplementados o ampliados por Catalog.

## 33. Funcionalidades explícitamente fuera de alcance

Carrito/cart_items, checkout, pedidos/order_items, pagos, cocina, delivery,
promociones, ruleta, reseñas, notificaciones, cancelaciones, reembolsos,
cálculo de delivery, programación de recojo y estados de pedidos.

Favoritos RF-08 quedan pendientes. La mención previa de incorporarlos con
Catalog no asignaba explícitamente una implementación a esta Fase 2; prevalece
el alcance actual CU-03/CU-20, RF-09 a RF-14 y RF-45. Se corrigió la documentación
para no sugerir que están implementados.

Tampoco se implementó almacenamiento físico de imágenes, ni notas en pedidos,
ni actores nuevos, ni nuevos usuarios/secrets, ni modificaciones Docker/puertos.
No se inició Fase 3.

# Restaurant App Backend

Backend asíncrono para una aplicación de restaurante, construido con FastAPI,
PostgreSQL, SQLModel y SQLAlchemy 2.x. La Fase 1 incorpora identidad,
autenticación, clientes, direcciones, sucursales y autorización de personal por
sucursal sobre la base profesional creada en la Fase 0. La Fase 2 añade el
catálogo global, el menú público, su administración y los overrides por sucursal.

> **Rama de trabajo.** El requerimiento inicial mencionaba
> **feat/auth-and-users**, pero por instrucción directa posterior se continuó en
> la rama que ya estaba activa: **chore/backend-foundation**. No se cambió de
> rama ni se realizó commit, merge, rebase o push por parte del agente. Para
> Fase 2 también prevalece la instrucción directa de continuar en esta misma
> rama sobre el nombre feat/catalog del documento de requisitos.

## Alcance de la Fase 1

La fase cubre:

- cuentas registradas con login por email o teléfono y contraseña;
- clientes invitados sin User;
- promoción transaccional de invitado a usuario registrado sin duplicar el
  Customer;
- verificación de teléfono mediante OTP;
- JWT separados por propósito: access, refresh y phone verification;
- rotación y revocación persistente de refresh tokens;
- perfil del cliente y direcciones con ownership;
- listado y selección lógica de sucursales;
- roles globales, roles por sucursal, permisos y asignaciones de personal;
- una migración base de Alembic para las doce tablas de esta fase.

No formaban parte de Fase 1 catálogo, productos, favoritos, carrito, pedidos,
pagos, cocina, delivery, promociones ni notificaciones. En particular, el
historial de pedidos y los favoritos de RF-08 quedan deliberadamente pendientes
para fases posteriores. Fase 2 implementa Catalog, pero no incorpora favoritos.

## Stack y requisitos

- Python 3.11 o superior; validado localmente con Python 3.14.
- FastAPI y Uvicorn.
- PostgreSQL administrado externamente.
- SQLAlchemy 2.x con AsyncEngine, AsyncSession y asyncpg.
- SQLModel para los modelos de persistencia.
- Alembic, Pydantic y pydantic-settings.
- PyJWT para JWT.
- pwdlib con Argon2 para contraseñas.
- Pytest, HTTPX/HTTPX2 y Ruff.

requirements.txt fija las versiones verificadas. SQLModel se utiliza como capa
de mapeo y metadata; el acceso asíncrono y las transacciones usan las APIs de
SQLAlchemy. El proyecto no crea ni administra Docker.

## Arquitectura

El código combina Vertical Slice Architecture con arquitectura hexagonal:

~~~text
Presentation -> Application -> Domain
                         ^
                         |
                 Infrastructure
~~~

- domain contiene entidades y reglas puras, sin FastAPI, ORM, HTTP ni PyJWT.
- application contiene casos de uso y puertos específicos.
- infrastructure implementa persistencia y seguridad.
- presentation contiene dependencias FastAPI, schemas y routers.

No existen BaseRepository, GenericService ni controladores genéricos. Cada
slice declara únicamente los puertos que necesita.

~~~text
app/
├── main.py
├── lifespan.py
├── shared/
│   ├── domain/
│   ├── application/
│   └── infrastructure/
│       ├── config/
│       ├── database/
│       ├── audit/
│       └── logging/
├── modules/
│   ├── auth/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   ├── persistence/
│   │   │   └── security/
│   │   └── presentation/
│   ├── customers/
│   │   ├── application/
│   │   ├── infrastructure/persistence/
│   │   └── presentation/
│   ├── branches/
│   │   ├── application/
│   │   ├── infrastructure/persistence/
│   │   └── presentation/
│   ├── catalog/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   ├── authorization.py
│   │   │   └── persistence/
│   │   └── presentation/
│   └── health/
│       ├── application/
│       ├── infrastructure/
│       └── presentation/
└── presentation/
    ├── api/
    └── errors.py
migrations/
├── env.py
└── versions/
    ├── 0001_create_phase1_identity_branches_customers.py
    └── 0002_create_catalog.py
~~~

Lifespan crea un único engine y una fábrica de sesiones. Cada petición recibe
su propia sesión; los casos de uso controlan commit y rollback. El startup no
ejecuta create_all ni aplica migraciones automáticamente.

## Modelo de identidad

User y Customer tienen responsabilidades diferentes:

- User es una cuenta autenticable y contiene el hash de contraseña, estado y
  datos de login.
- Customer es la identidad comercial que conservará direcciones, pedidos y
  preferencias.
- un invitado tiene customers.user_id = NULL;
- un registrado tiene customers.user_id = users.id;
- customers.is_guest es una columna generada a partir de user_id IS NULL.

Cuando un invitado se registra con el mismo teléfono, el caso de uso bloquea y
reutiliza el Customer, crea el User, enlaza ambos y asigna el rol global
CUSTOMER dentro de una sola transacción. Así no se pierden direcciones ni los
futuros pedidos.

## Persistencia de Fase 1

La revisión 0001_phase1 crea exactamente estas tablas:

| Área | Tabla | Propósito |
| --- | --- | --- |
| Seguridad | roles | Roles GLOBAL o BRANCH |
| Seguridad | permissions | Permisos atómicos |
| Seguridad | role_permissions | Relación rol-permiso |
| Seguridad | users | Cuentas autenticables |
| Seguridad | user_roles | Roles globales de un usuario |
| Seguridad | refresh_tokens | Hashes y revocación de refresh tokens |
| Sucursales | branches | Sucursales activas/inactivas |
| Sucursales | branch_hours | Horario único por día y sucursal |
| Sucursales | staff_assignments | Personal, rol y sucursal |
| Clientes | customers | Cliente invitado o registrado |
| Clientes | otp_challenges | Challenges OTP, intentos y consumo |
| Clientes | customer_addresses | Direcciones pertenecientes al cliente |

La migración habilita idempotentemente citext y pgcrypto, usa UUID,
TIMESTAMPTZ, CITEXT y SMALLINT IDENTITY, y crea:

- checks de teléfono, estado de cuenta, rango geográfico y horario;
- unicidad de email/teléfono y de las relaciones de negocio;
- un índice único parcial que permite solo una dirección default por cliente;
- triggers de updated_at;
- triggers que aceptan solo roles GLOBAL en user_roles;
- triggers que aceptan solo roles BRANCH en staff_assignments;
- protección ante cambios de roles.scope que invalidarían asignaciones.

Se insertan idempotentemente CUSTOMER, ADMIN, KITCHEN, STAFF_MANAGE y la
relación ADMIN a STAFF_MANAGE. No se inserta ningún usuario ni contraseña.

## Instalación y configuración

Desde la raíz:

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
~~~

Reutiliza .venv y .env si ya existen. .env está ignorado por Git y nunca debe
incluirse en commits. Las variables reales del entorno prevalecen sobre el
archivo.

### Variables generales y de PostgreSQL

| Variable | Uso |
| --- | --- |
| APP_NAME, APP_VERSION | Identidad del servicio |
| APP_ENV | development, test, staging o production |
| APP_DEBUG | Logging de desarrollo; no expone trazas HTTP |
| API_V1_PREFIX | Prefijo, por defecto /api/v1 |
| DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD | Conexión PostgreSQL |
| DATABASE_URL | Alternativa prioritaria a DB_* |
| DATABASE_TIMEOUT_SECONDS | Timeout de conexión/readiness |
| CORS_ORIGINS | Orígenes HTTP(S) explícitos separados por comas |

DATABASE_URL se normaliza a postgresql+asyncpg. CORS rechaza * cuando se usan
credenciales.

### Variables JWT y OTP

| Variable | Valor de ejemplo | Uso |
| --- | --- | --- |
| JWT_SECRET | placeholder de 32+ caracteres | Secreto de firma; reemplazar |
| JWT_ALGORITHM | HS256 | Algoritmo permitido |
| JWT_ISSUER | restaurant-app-backend | Emisor esperado |
| JWT_AUDIENCE | restaurant-app | Audiencia esperada |
| ACCESS_TOKEN_EXPIRE_MINUTES | 15 | Vida del access token |
| REFRESH_TOKEN_EXPIRE_DAYS | 30 | Vida del refresh token |
| PHONE_VERIFICATION_TOKEN_EXPIRE_MINUTES | 10 | Vida de la prueba OTP |
| OTP_PEPPER | placeholder de 32+ caracteres | Pepper HMAC del OTP |
| OTP_EXPIRE_MINUTES | 5 | Expiración del challenge |
| OTP_MAX_ATTEMPTS | 5 | Intentos máximos |
| OTP_RESEND_COOLDOWN_SECONDS | 60 | Espera entre reenvíos |
| OTP_DEBUG_EXPOSE_CODE | false | Exposición controlada solo en dev/test |

En APP_ENV=production, Settings rechaza secretos débiles o placeholders y
rechaza OTP_DEBUG_EXPOSE_CODE=true. No se registran secretos, contraseñas,
hashes, OTP, tokens ni el header Authorization.

Las mismas restricciones se aplican a staging. Si development/test omite
JWT_SECRET u OTP_PEPPER, se generan valores aleatorios efímeros: al reiniciar
dejarán de validar las sesiones/challenges anteriores. Configura secretos
independientes y estables en el entorno o .env para desarrollo persistente;
reemplaza siempre los placeholders de .env.example.

## Ejecución y OpenAPI

~~~bash
uvicorn app.main:app --reload
~~~

OpenAPI queda disponible en http://127.0.0.1:8000/docs.

### Salud

| Método y ruta | Descripción |
| --- | --- |
| GET /api/v1/health | Liveness sin acceder a PostgreSQL |
| GET /api/v1/health/ready | Ejecuta SELECT 1; responde 503 si falla |
| GET / | Endpoint legado |
| GET /health | Health legado |

### Autenticación

| Método y ruta | Descripción |
| --- | --- |
| POST /api/v1/auth/otp/request | Solicita OTP; respuesta no enumera cuentas |
| POST /api/v1/auth/otp/verify | Consume OTP y entrega phone verification token |
| POST /api/v1/auth/guest | Crea/reutiliza invitado y entrega access token limitado |
| POST /api/v1/auth/register | Registra o promueve invitado |
| POST /api/v1/auth/login | Login por email/teléfono y contraseña |
| POST /api/v1/auth/refresh | Rota refresh y access tokens |
| POST /api/v1/auth/logout | Revoca el refresh presentado |
| POST /api/v1/auth/password/change | Cambia contraseña y revoca refresh activos |
| POST /api/v1/auth/phone/change | Cambia teléfono con prueba OTP PHONE_VERIFY |

### Perfil y direcciones

| Método y ruta | Descripción |
| --- | --- |
| GET /api/v1/customers/me | Perfil derivado del principal |
| PATCH /api/v1/customers/me | Campos seguros de perfil |
| GET /api/v1/customers/me/addresses | Direcciones propias |
| POST /api/v1/customers/me/addresses | Crea una dirección propia |
| PATCH /api/v1/customers/me/addresses/{address_id} | Actualiza con ownership |
| DELETE /api/v1/customers/me/addresses/{address_id} | Elimina con ownership |

El cliente nunca envía un customer_id para decidir propiedad. El backend lo
obtiene del principal autenticado. El teléfono no se cambia mediante el PATCH
de perfil.

### Sucursales y personal

| Método y ruta | Descripción |
| --- | --- |
| GET /api/v1/branches | Lista únicamente sucursales activas |
| GET /api/v1/branches/{branch_id} | Obtiene una sucursal activa y su horario |
| GET /api/v1/branches/{branch_id}/staff | Lista personal autorizado |
| POST /api/v1/branches/{branch_id}/staff | Asigna personal autorizado |
| PATCH /api/v1/branches/{branch_id}/staff/{assignment_id} | Actualiza asignación |

## Flujos de autenticación

### OTP

1. El cliente solicita un challenge para GUEST_ACCESS, REGISTER, LOGIN o
   PHONE_VERIFY.
2. Se genera un código criptográficamente aleatorio.
3. Solo se persiste un HMAC-SHA-256 con OTP_PEPPER.
4. Se controlan cooldown, expiración, intentos, consumo y no reutilización.
5. Al verificarlo se marca consumed_at y se emite un token de verificación de
   teléfono, corto y ligado a teléfono y propósito.

El adaptador incluido de entrega en memoria existe exclusivamente para
development/test y no escribe OTP en logs. Producción debe aportar una
implementación real del puerto OtpSender; no se inventa un proveedor SMS.
Mientras no exista ese adaptador, staging/production responde 503
OTP_DELIVERY_UNAVAILABLE y revierte el challenge. El código solo aparece en la
respuesta con OTP_DEBUG_EXPOSE_CODE=true en development/test.

Los challenges son de un solo uso. La prueba JWT resultante es válida para su
teléfono y propósito hasta expirar; no es un access token. LOGIN se conserva
como propósito compatible, sin implementar login mediante OTP en esta fase.

### Invitado

1. Verifica el teléfono con propósito GUEST_ACCESS.
2. Envía el verification token y full_name.
3. El teléfono se toma del token, nunca de otro campo arbitrario.
4. Se crea o reutiliza un Customer con user_id = NULL.
5. Si el teléfono ya pertenece a un registrado, se devuelve un error seguro.
6. Se emite solo access token de guest; no hay refresh token.

Crear cuenta no es obligatorio para comprar. Los módulos futuros de carrito y
pedidos podrán asociar la operación al customer_id del principal guest.

### Registro y promoción de invitado

1. Verifica teléfono con propósito REGISTER.
2. Valida el verification token y obtiene el teléfono.
3. Comprueba duplicados de teléfono/email.
4. Hashea la contraseña con Argon2.
5. Crea User activo y asigna CUSTOMER en user_roles.
6. Bloquea el Customer por teléfono; si era guest, enlaza su user_id; si no
   existía, lo crea.
7. Confirma todo en una transacción.
8. Entrega access y refresh token.

### Login

Acepta email o teléfono más contraseña. Usuario inexistente y contraseña
incorrecta producen el mismo error Invalid credentials, evitando enumeración.
Se rechazan cuentas BLOCKED, DISABLED o con deleted_at; después del éxito se
actualiza last_login_at dentro de la transacción.

### Contraseña y teléfono

Las contraseñas usan Argon2 mediante el puerto PasswordHasher; nunca MD5,
SHA-1, SHA-256 directo ni texto plano. La política aplica longitud razonable y
límites de 8 a 128 caracteres sin exigir combinaciones arbitrarias. El trabajo
Argon2 se ejecuta fuera del event loop y permite rehash al autenticar. Al cambiar contraseña se
verifica la actual y se revocan los refresh tokens activos.

El cambio de teléfono exige un OTP PHONE_VERIFY, verifica unicidad y actualiza
coherentemente users.phone, customers.phone y phone_verified_at en una
transacción.

## JWT, refresh rotation y logout

Todos los JWT validan firma, exp, iat, iss, aud, jti y token_type. Los access
tokens identifican un Principal seguro:

- registrado: principal_type=registered, user_id y, si corresponde,
  customer_id;
- invitado: principal_type=guest y customer_id.

Los access y refresh no contienen contraseña, hash, teléfono ni email. El
phone_verification incluye necesariamente teléfono y propósito; es una prueba
de identidad de corta duración, no cifrada, y debe tratarse como dato sensible.
Los tipos access, refresh y phone_verification no son intercambiables.

- El access token tiene vida corta, no se guarda en la base y se usa como
  Authorization: Bearer.
- El refresh token solo se entrega a registrados. La base guarda únicamente su
  SHA-256, apropiado para un token aleatorio de alta entropía.
- En refresh se valida JWT y estado actual, se bloquea el registro, se comprueba
  hash, revocación y expiración, se revoca el token anterior y se crea un par
  nuevo en una sola transacción.
- Reutilizar un refresh rotado o revocado falla.
- Logout busca el hash del refresh y persiste revoked_at; no usa listas en
  memoria.

Logout y cambio de contraseña revocan refresh tokens; un access token ya emitido
conserva su validez corta hasta expirar, salvo bloqueo/desactivación/eliminación
de cuenta, que se comprueba en cada petición. Las cuentas de personal pueden
autenticarse sin Customer; las rutas de perfil/direcciones requieren esa
identidad comercial.

El JWT identifica, pero la base autoriza. Las rutas protegidas vuelven a
comprobar estado de cuenta y, para administración, asignación, rol y permiso.

## Roles, permisos y autorización por sucursal

| Código | Scope | Uso |
| --- | --- | --- |
| CUSTOMER | GLOBAL | Cuenta de cliente registrado |
| ADMIN | BRANCH | Administración de una sucursal |
| KITCHEN | BRANCH | Personal de cocina de una sucursal |

ADMIN recibe STAFF_MANAGE. Para gestionar personal se exige simultáneamente:

1. principal registrado y cuenta activa;
2. staff_assignment activa;
3. rol BRANCH;
4. permiso STAFF_MANAGE;
5. la misma branch_id de la ruta.

Un administrador de la sucursal A no puede administrar la B. Un guest y un
usuario con solo CUSTOMER tampoco pueden hacerlo. Los triggers PostgreSQL
impiden insertar roles de scope incorrecto incluso si se omite la validación de
aplicación.

## Selección de sucursal en frontend

Al iniciar la experiencia, el frontend:

1. consulta GET /api/v1/branches;
2. muestra solo las sucursales activas;
3. guarda el branch_id elegido en el estado de la aplicación;
4. conserva la selección localmente si la experiencia lo requiere;
5. envía ese branch_id de forma explícita a los futuros módulos de carrito y
   pedidos.

La selección no concede permisos y no debe tratarse como una sucursal global
del servidor. Cada módulo valida que la sucursal siga activa y cada operación
administrativa consulta autorización actual en base de datos. El catálogo común
y la disponibilidad por sucursal están implementados en Fase 2: el frontend
envía también branch_id a las dos consultas públicas de Catalog.

## Perfil y direcciones

El perfil funciona para registrado y guest autenticado:

- un registrado puede modificar first_name, last_name y email seguro;
- un guest solo puede modificar full_name;
- ningún schema HTTP expone hashes, tokens ni campos internos.

Las operaciones de direcciones filtran siempre por customer_id del principal.
Las coordenadas se validan y el índice parcial garantiza una sola dirección
is_default=true por cliente incluso bajo concurrencia.
Se bloquea el Customer antes de cambiar la dirección default. El cambio de email
sincroniza User/Customer y elimina una verificación de email anterior.

La DB actualiza updated_at mediante triggers con clock_timestamp(); los adapters
no introducen un segundo mecanismo. UNIQUE protege las altas concurrentes,
refresh bloquea User antes de sus tokens, OTP serializa teléfono/propósito con un
advisory lock transaccional incluso cuando todavía no existe un challenge, y la
actualización de personal bloquea su asignación.

## Bootstrap seguro del primer ADMIN

La migración crea roles y permisos, pero **no crea usuarios administrativos**.
No existe una contraseña por defecto ni credencial versionada.

Procedimiento recomendado:

1. Aprovisiona una sucursal mediante una operación administrativa controlada.
2. Registra al primer operador por el flujo normal de OTP y registro. Así su
   contraseña ya queda hasheada con Argon2 y su teléfono verificado.
3. Con una conexión DBA auditada a la base correcta, asigna a ese user_id el rol
   ADMIN únicamente para la sucursal elegida.
4. Verifica la asignación y cierra la sesión DBA.
5. Desde entonces, usa los endpoints protegidos de staff para nuevas
   asignaciones.

Ejemplo para una sesión interactiva de psql; los UUID y el código de empleado se
introducen en el momento y no son credenciales:

~~~sql
\prompt 'User UUID ya registrado: ' bootstrap_user_id
\prompt 'Branch UUID activa: ' bootstrap_branch_id
\prompt 'Employee code: ' bootstrap_employee_code

BEGIN;

INSERT INTO staff_assignments (
    user_id,
    branch_id,
    role_id,
    employee_code
)
SELECT
    :'bootstrap_user_id'::uuid,
    :'bootstrap_branch_id'::uuid,
    role.id,
    :'bootstrap_employee_code'
FROM roles AS role
JOIN users AS app_user
  ON app_user.id = :'bootstrap_user_id'::uuid
 AND app_user.account_status = 'ACTIVE'
 AND app_user.deleted_at IS NULL
JOIN branches AS branch
  ON branch.id = :'bootstrap_branch_id'::uuid
 AND branch.is_active IS TRUE
 AND branch.deleted_at IS NULL
WHERE role.code = 'ADMIN'
  AND role.scope = 'BRANCH'
ON CONFLICT (user_id, branch_id, role_id) DO NOTHING;

SELECT user_id, branch_id, role_id, employee_code, is_active
FROM staff_assignments
WHERE user_id = :'bootstrap_user_id'::uuid
  AND branch_id = :'bootstrap_branch_id'::uuid;

COMMIT;
~~~

Antes de COMMIT, si el SELECT no devuelve una asignación válida, ejecuta ROLLBACK e investiga el
usuario, sucursal, rol o conflictos de código. Nunca insertes un hash manual,
una contraseña temporal ni ADMIN en user_roles: ADMIN es un rol de sucursal y
pertenece a staff_assignments.

## Alembic y bases existentes

migrations/env.py importa explícitamente los modelos de auth, customers,
branches, catalog y auditoría compartida antes de leer SQLModel.metadata.
El filtro de autogenerate evita proponer drops de tablas
externas que todavía no pertenecen a los modelos.

Comandos de inspección:

~~~bash
alembic current
alembic heads
alembic history
~~~

La cadena es base -> 0001_phase1 -> 0002_catalog, con un único head:
0002_catalog. La revisión 0001 no se modificó. No ejecutes alembic upgrade head sobre una
base existente sin inspeccionarla primero.

### Base limpia o exclusiva de test

1. Confirma que DATABASE_URL apunta a la base correcta.
2. Comprueba que está vacía o es desechable.
3. Verifica que el rol puede crear extensiones; si no, un DBA debe instalar
   citext y pgcrypto.
4. Ejecuta alembic upgrade head.
5. Verifica tablas, constraints, índices, triggers, seeds y alembic current.

alembic downgrade base solo se considera en una base exclusiva de test. El
downgrade no elimina extensiones compartidas.

### Base existente con tablas previas

1. Toma backup y detén escrituras durante la evaluación.
2. Inspecciona information_schema, constraints, índices, extensiones, triggers
   y datos maestros.
3. Compara cada objeto con 0001_phase1.
4. Si faltan objetos o difieren, crea una migración de reconciliación explícita
   y no destructiva; no renombres, recrees ni borres datos automáticamente.
5. Solo si el esquema es realmente equivalente y tras autorización humana,
   puede evaluarse alembic stamp 0001_phase1.

Nunca se ejecuta stamp automáticamente. Una tabla con el mismo nombre no
demuestra equivalencia. Durante la implementación de Fase 1 PostgreSQL no estuvo
accesible en 127.0.0.1:5432; por seguridad no se aplicó upgrade ni stamp.
Al cierre de Fase 2 la conexión sí respondió: hay 49 tablas preexistentes y no
existe alembic_version. El esquema no equivale a las revisiones: faltan slug en
categories, allows_notes/slug/sort_order en products, y tres tablas de Catalog;
audit_logs usa BIGINT y before_data/after_data, no el contrato UUID y
before_state/after_state. No se modificó esa base ni se realizó stamp.
Antes de usarla se necesita una reconciliación no destructiva expresamente
revisada; upgrade head no es seguro sobre ese esquema existente.

## Tests y calidad

~~~bash
pytest
ruff check .
ruff format --check .
~~~

Los tests normales usan fakes, mocks y dependency overrides; no deben acceder a
la base de desarrollo. La cobertura incluye la infraestructura de Fase 0,
primitivas Argon2/JWT/OTP, principals, perfil, ownership de direcciones y
límites transaccionales. Los casos de auth cubren registro nuevo,
promoción guest, login, estados de cuenta, OTP, rotación/reutilización de
refresh, logout y cambios sensibles. También se comprueban autorización entre
sucursales, scopes, conflictos seguros, consultas con bloqueos, metadata y
compilación offline del upgrade/downgrade sin ejecutar DDL.

Las pruebas PostgreSQL se habilitan exclusivamente con:

~~~bash
pytest -m integration
~~~

Requiere TEST_DATABASE_URL en el entorno, un nombre con test_ o _test, una base
vacía y distinta de la habitual. Sin esa configuración se omite; pytest normal
siempre las omite. La prueba de Fase 1 apunta explícitamente a 0001_phase1 y
comprueba sus doce tablas, claves, seeds, columna generada e índice default.
La prueba de Fase 2 aplica head, comprueba las veinte tablas, constraints reales,
CATALOG_MANAGE y operaciones del adaptador con auditoría. Cada prueba trabaja
dentro de una transacción externa que revierte todo el DDL al terminar.
No crean/eliminan bases, no ejecutan downgrade y nunca modifican objetos
previos. No apuntes TEST_DATABASE_URL a desarrollo o producción.

## Errores y privacidad

Los errores usan un sobre estable:

~~~json
{"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid credentials"}}
~~~

Se emplean estados HTTP coherentes: 400 para solicitudes inválidas, 401 para
autenticación, 403 para autorización, 404 para recursos fuera del ownership,
409 para conflictos, 422 para validación y 429 para cooldown cuando
corresponda. Las respuestas no revelan si una cuenta concreta existe ni
devuelven teléfono, email, direcciones, hashes o tokens salvo cuando el contrato
lo exige.

## Matriz de trazabilidad

| Requisito | Estado | Evidencia de Fase 1 |
| --- | --- | --- |
| RF-01 | IMPLEMENTADO | Listado de sucursales activas y selección lógica por branch_id |
| RF-02 | IMPLEMENTADO EN FASE 2 | Catálogo común y overrides por sucursal, sin duplicar productos |
| RF-03 | IMPLEMENTADO | staff_assignments, roles BRANCH y autorización por sucursal |
| RF-04 | IMPLEMENTADO | Guest representado por Customer sin User |
| RF-05 | IMPLEMENTADO | Guest requiere nombre y teléfono verificado |
| RF-06 | IMPLEMENTADO | Challenges OTP seguros; proveedor SMS real es un adaptador pendiente de producción |
| RF-07 | IMPLEMENTADO | Registro, promoción de invitado y login |
| RF-08 | PARCIAL | Perfil y direcciones implementados |

Pendientes explícitos de RF-08:

- historial de pedidos, que se implementará con Orders;
- favoritos, pendientes de una fase futura expresamente autorizada; no forman
  parte de Fase 2.

## Fase 2 — Catálogo y menú

El slice Catalog cubre CU-03/CU-20, RF-09 a RF-14 y RF-45. Mantiene dominio
puro, DTO de aplicación, puertos concretos, adaptadores SQLAlchemy async y
schemas/routers HTTP separados. Reutiliza autenticación, sesiones, autorización
por sucursal y errores de Fase 1. No introduce dependencias ni modifica .env.

### Tablas y migración

| Tabla | Responsabilidad |
| --- | --- |
| categories | Categorías globales ordenadas, activación y archivado |
| products | Producto global; categoría, precio base y allows_notes |
| product_images | URL y metadata; una primary no archivada por producto |
| product_presentations | Presentaciones configurables, delta y default |
| product_addons | Grupos de opciones y límites de selección |
| product_addon_options | Opciones gratuitas o con costo |
| branch_products | Disponibilidad y override base por sucursal/producto |
| audit_logs | Auditoría administrativa reutilizable, dentro de la transacción |

0002_catalog depende de 0001_phase1 y crea solamente estas ocho tablas.
Reutiliza restaurant_phase1_set_updated_at en siete triggers; no crea otra
función equivalente. Las FK usan RESTRICT. Hay CHECK de precios no negativos,
orden, nombres, slug y límites de selección; UNIQUE de slug de categoría y
producto, nombre de categoría CITEXT y par sucursal/producto. Los índices
parciales garantizan una imagen primary no archivada y una presentación default
activa no archivada por producto. Los índices de lectura priorizan padres,
estado y orden; auditoría indexa actor/fecha y entidad/fecha.

La migración inserta idempotentemente CATALOG_MANAGE y lo asigna al ADMIN
BRANCH existente, sin crear usuarios ni SUPERADMIN. El downgrade hasta
0001_phase1 retira solo tablas, triggers y permiso de Fase 2; conserva tablas,
roles, permisos base, extensiones y función updated_at de Fase 1.

En una base que ya tenga Fase 1, verifica primero alembic current y equivalencia
del esquema. Con backup y la base correcta, alembic upgrade head añade Fase 2.
No se aplicó online durante esta implementación: la base local tiene un esquema
preexistente incompatible, sin revisión Alembic, y no hay TEST_DATABASE_URL.
La compilación offline y heads/history no sustituyen una prueba PostgreSQL real.

### Precios y disponibilidad

Todo importe persistido es NUMERIC(12,2); las reglas usan Decimal, nunca float.
Enviar importes como strings decimales es la forma recomendada; las respuestas
los serializan siempre con dos decimales.

~~~text
effective_base_price = price_override si existe; en otro caso products.base_price
presentation.effective_price = effective_base_price + presentation.price_delta
selección interna = precio de presentación + suma de additional_price elegido
~~~

Un precio base global de 20.00 y deltas de 0.00/15.00 producen 20.00/35.00.
Con override de sucursal 22.00 producen 22.00/37.00. El override cambia la base,
no reemplaza el precio final de cada presentación. Sin branch_products se
heredan disponibilidad true y precio global. price_override=null restablece la
herencia; is_available=false solo afecta a la sucursal indicada.

| Estado | Menú público |
| --- | --- |
| AVAILABLE | Visible, is_available=true |
| SOLD_OUT | Visible, is_available=false |
| INACTIVE | Oculto |
| ARCHIVED | Oculto |

El producto necesita categoría activa/no archivada, estar activo/no archivado y
tener al menos una presentación activa/no archivada. Se puede crear como
borrador y completar después; no se inventa una presentación. El detalle
administrativo expone is_publicable. No se exige que exista una default, solo
que haya como máximo una activa. Las categorías sin productos publicables se
omiten del menú.

Los resultados ordenan por sort_order, nombre cuando corresponde, y UUID como
último desempate. El menú no filtra por is_available. La lectura completa usa
hasta cinco consultas por lotes más la comprobación de sucursal, con independencia
del número de productos; no carga relaciones una a una ni hace un join cartesiano
de todas las colecciones. Esta versión no implementa paginación del menú.

### Endpoints públicos

No requieren login. branch_id es un query parameter UUID obligatorio y debe
identificar una sucursal activa.

| Método y ruta | Resultado |
| --- | --- |
| GET /api/v1/catalog/menu?branch_id={uuid} | Categorías con productos, imágenes, presentaciones y adicionales |
| GET /api/v1/catalog/products/{product_id}?branch_id={uuid} | Detalle con precios efectivos calculados por el backend |

El detalle contiene categoría, estado, precio base efectivo, disponibilidad,
allows_notes, imágenes/primary, presentaciones/default y grupos con options.
No revela auditoría, permisos ni estados internos de archivado. Un producto
oculto, borrador o inexistente devuelve 404.

### Endpoints administrativos

Todas las rutas siguientes tienen el prefijo /api/v1/admin/catalog.
En conjunto hay 23 operaciones administrativas y dos públicas, etiquetadas
admin-catalog y catalog en OpenAPI.

| Métodos | Ruta | Operación |
| --- | --- | --- |
| GET, POST | /categories | Listar o crear categorías |
| PATCH, DELETE | /categories/{category_id} | Editar o archivar categoría |
| GET, POST | /products | Listar o crear productos |
| GET, PATCH, DELETE | /products/{product_id} | Detalle administrativo, editar o archivar |
| POST | /products/{product_id}/images | Crear metadata de imagen |
| PATCH, DELETE | /products/{product_id}/images/{image_id} | Editar o archivar imagen |
| POST | /products/{product_id}/presentations | Crear presentación |
| PATCH, DELETE | /products/{product_id}/presentations/{presentation_id} | Editar o archivar presentación |
| POST | /products/{product_id}/addons | Crear grupo |
| PATCH, DELETE | /products/{product_id}/addons/{addon_id} | Editar o archivar grupo |
| POST | /products/{product_id}/addons/{addon_id}/options | Crear opción |
| PATCH, DELETE | /products/{product_id}/addons/{addon_id}/options/{option_id} | Editar o archivar opción |
| GET, PUT | /branches/{branch_id}/products/{product_id} | Consultar o hacer UPSERT de disponibilidad/precio |

GET/PATCH/PUT responden 200; POST responde 201; DELETE lógico responde 204
sin body. Sin JWT: 401; sin permiso: 403; recurso inexistente/no perteneciente
al padre: 404; conflicto: 409; payload inválido: 422; base no disponible: 503.
Los errores mantienen el envelope existente y no exponen SQL, DSN o constraints.

El detalle administrativo incluye producto, categoría y colecciones no
archivadas, incluso inactivas; las opciones conservan product_addon_id. Es útil
para completar productos que todavía no son públicos. Los listados
administrativos incluyen inactivos y excluyen archivados.

PATCH rechaza campos extra y body vacío. id, timestamps, deleted_at,
actor_user_id, roles y auditoría nunca son asignables. Solo description y
alt_text pueden limpiarse con null; otros campos PATCH no aceptan null. Los
límites de adicionales se comprueban también contra el valor actual cuando el
PATCH modifica solo min_select o max_select.

~~~json
{"is_available": false, "price_override": "22.00"}
~~~

El PUT crea o actualiza la misma configuración, sin duplicar el par. Exige
is_available y acepta price_override nullable; omitir este último equivale a
null, porque PUT representa la configuración completa. El GET sin override
persistido devuelve los valores heredados.

### Autorización actual y ownership

El JWT identifica, pero los permisos se consultan en persistencia en cada
operación. Se reutilizan CurrentPrincipal, decoder y validación de cuenta de
Fase 1; guest y CUSTOMER sin permiso administrativo no pueden gestionar Catalog.

Para el catálogo global se exige cuenta registrada activa/no eliminada y al
menos una asignación ADMIN BRANCH activa/no terminada, con CATALOG_MANAGE, en
una sucursal activa/no archivada. Esa es la decisión funcional de esta fase:
un ADMIN válido puede modificar el menú común, sin inventar SUPERADMIN.

Para branch_products se exige permiso CATALOG_MANAGE en exactamente la
sucursal de la ruta. ADMIN de A no modifica disponibilidad o precio de B.
Una sucursal inexistente/inactiva devuelve 404. La revocación de asignación se
refleja en la siguiente petición; no depende de expiración del JWT.

Imágenes y presentaciones verifican product_id; grupos y opciones verifican
producto -> grupo -> opción. Cambiar UUID en una URL no permite cruzar padres.
El puerto de autorización puede extenderse con un rol global futuro sin cambiar
las reglas de catálogo ni duplicar autenticación.

### Presentaciones, adicionales, notas e imágenes

Presentaciones, grupos y opciones son datos configurables, no constantes.
additional_price=0.00 significa gratuito. Los grupos exponen is_required,
min_select y max_select; el mínimo efectivo es al menos uno cuando el grupo es
obligatorio. Se validan pertenencia, opciones activas, duplicados y máximos.

CatalogService.validate_selection es un caso de uso interno sin endpoint de
compra: verifica sucursal, estado, presentación, opciones, límites y allows_notes,
y calcula el precio desde datos del backend. No persiste notas ni selecciones,
no crea carrito/pedido y no reserva stock. Una compra futura deberá volver a
validar dentro de su propio flujo transaccional.

Las imágenes solo almacenan URL HTTP(S), alt_text, orden y primary. No se
aceptan credenciales embebidas en URL; no se descarga el recurso ni se persisten
binarios. No se añadió upload, S3, Cloudinary, MinIO ni otro proveedor.

### Archivado, auditoría y concurrencia

DELETE es soft delete de categorías, productos y sus cuatro tipos de hijos.
No existe eliminación física de catálogo. Archivar categoría con productos
activos/no archivados devuelve 409 CATEGORY_HAS_ACTIVE_PRODUCTS; no hay cascade
soft-delete. Inactivar una categoría oculta sus productos, sin archivarlos.

Cada alta, edición o archivado registra actor, entidad, antes/después y fecha.
BRANCH_PRODUCT_UPDATED incluye branch_id; las operaciones globales usan null.
Hay 19 acciones de auditoría; UUID/Decimal/fecha se serializan de forma segura.
El recorder reutilizable comparte AsyncSession y no confirma por separado:
si falla la escritura, auditoría o commit, se revierte toda la operación.

Se bloquea el producto al modificar hijos, archivarlo o configurar sucursal;
las categorías se bloquean antes de crear/mover productos o archivarlas.
Los índices únicos son la última defensa para primary/default. Los cambios
desmarcan el indicador anterior y marcan el nuevo en la misma transacción.
El UPSERT usa ON CONFLICT sobre la clave sucursal/producto. updated_at viene
del trigger existente y se refresca antes de responder.

### Validación de Fase 2 y pendientes

~~~bash
pytest -q tests/modules/catalog tests/test_phase2_migration.py
pytest
ruff check .
ruff format --check .
git diff --check
alembic heads
alembic history
pytest -m integration
~~~

Las pruebas de Catalog cubren dominio, casos de uso, API con JWT real,
autorización actual, archivado, consultas, constraints offline y auditoría
atómica. La integración opt-in aplica migraciones a una base TEST vacía y
verifica constraints PostgreSQL y el adaptador real. Sin TEST_DATABASE_URL
se omite de forma explícita; no se declara migración online validada.

El detalle de resultados, archivos y riesgos está en
[docs/phase2-report.md](docs/phase2-report.md). Pendientes: prueba PostgreSQL real
y aplicación controlada de migración en una base compatible o reconciliación
autorizada del esquema preexistente. Favoritos, uploads
físicos, carrito, pedidos, pagos, cocina, delivery y los demás módulos posteriores
quedan expresamente fuera de esta fase.

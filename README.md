# Restaurant App Backend

Backend asíncrono para una aplicación de restaurante, construido con FastAPI,
PostgreSQL, SQLModel y SQLAlchemy 2.x. La Fase 1 incorpora identidad,
autenticación, clientes, direcciones, sucursales y autorización de personal por
sucursal sobre la base profesional creada en la Fase 0. La Fase 2 añade el
catálogo global, el menú público, su administración y los overrides por sucursal.
La Fase 3 incorpora carritos de invitados/registrados y cálculo de precios con
snapshots generados exclusivamente por el backend.
La Fase 4 incorpora pedidos históricos LOCAL/PICKUP/DELIVERY, checkout atómico,
idempotencia y configuración de mesas, recojo y cobertura por sucursal.
La Fase 5 añade la cola de cocina, preparación, tiempos y transiciones auditadas
sobre el estado y el historial existentes de Orders.
La Fase 6 añade el ledger financiero, confirmación de efectivo y orquestación
online con webhook verificado mediante un puerto de proveedor todavía no elegido.
La Fase 7 añade liberación de recojos programados, entrega con identidad histórica,
asignaciones de delivery, despacho/entrega y revisión humana de retrasos.
La Fase 8 incorpora cancelaciones y obligaciones de reembolso completo.
La Fase 9 añade notificaciones in-app, registro de dispositivos, outbox push y
SSE autenticado para clientes, administración y cocina.
La Fase 10 añade administración de clientes, personal y sucursales, overview
de configuración existente y dashboard financiero de solo lectura.
La Fase 11 incorpora favoritos, reviews de pedidos completados, solicitudes
fiscales mediante un puerto todavía sin proveedor y ruleta promocional gratuita.
La Fase 12 añade hardening, gates CI, contratos OpenAPI, revisión de seguridad,
pruebas PostgreSQL/E2E/carreras/performance y runbooks de release/recuperación.

## Estado de release — Fase 12

**RELEASE BLOCKED.** Rama actual: chore/backend-foundation; HEAD inicial F12:
309ade6. Se respeta la instrucción directa de trabajar en la misma rama; no se
creó chore/release-hardening. Sin staging, commit, push, tag o deploy del agente.

Calidad/seguridad local probadas. PostgreSQL real pendiente: TEST_DATABASE_URL
no está configurada; skips no son validación. CI con PostgreSQL 17 está configurado,
**no ejecutado aún**; requiere commit/push del usuario. No migrar/stamp/resetear
la base normal para ejecutar tests. Proveedores reales payment/refund/push/fiscal/
OTP, worker/scheduler productivos y restore drill siguen pendientes.

- [Informe y resultados F12](docs/phase12-report.md).
- [RNF y decisión de release](docs/release-readiness.md).
- [Permisos, IDOR y seguridad](docs/security-review.md).
- [Trazabilidad F0–12](docs/release-traceability.md).
- [Guía API](docs/api-guide.md), [OpenAPI](docs/openapi.json)
  e [inventario generado](docs/api-inventory.md).
- [Despliegue/migraciones/rollback](docs/release-runbook.md).
- [Backup/restore](docs/backup-restore-runbook.md) y
  [metodología de performance](docs/performance-report.md).

Validación local offline:

~~~bash
source .venv/bin/activate
ruff check .
ruff format --check .
python -m pip check
python -m compileall -q app tests scripts
pytest -m "not integration"
python scripts/export_openapi.py --check
python scripts/release_check.py
~~~

Solo con una DB PostgreSQL **TEST dedicada, vacía y distinta de normal** y URL
configurada mediante entorno seguro:

~~~bash
pytest -m integration -rP
pytest -m performance -s
~~~

No hacer upgrade antes: el harness controla Alembic y su propio schema TEST.
F12 corrige el gap probado LOCAL READY → SERVED con operación admin específica
ORDER_MANAGE; no agrega estado/migration ni autorización genérica para cambiar estado.

> **Rama de trabajo.** El requerimiento inicial mencionaba
> **feat/auth-and-users**, pero por instrucción directa posterior se continuó en
> la rama que ya estaba activa: **chore/backend-foundation**. No se cambió de
> rama ni se realizó commit, merge, rebase o push por parte del agente. Para
> Fase 2 también prevalece la instrucción directa de continuar en esta misma
> rama sobre el nombre feat/catalog del documento de requisitos.
> Para Fase 3 se mantiene igualmente chore/backend-foundation, por instrucción
> directa, aunque el documento mencione feat/cart. Fase 2 ya estaba committeada
> por el usuario en b2e9de5; el agente no crea commits ni pushes de Fase 3.
> Fase 3 está ahora en 902014f. Para Fase 4 también prevalece la instrucción
> directa de mantener chore/backend-foundation sobre feat/orders del adjunto.
> El usuario guardó Fase 4 en 7201466. Fase 5 quedó consolidada en
> **chore/backend-foundation**, commit 43af19e. Por instrucción directa,
> Fase 6 se implementa en esa misma rama, aunque el adjunto indique feat/payments.
> Fase 6 fue guardada en ff8f304. Fase 7 continúa en la misma rama por instrucción
> directa, aunque el adjunto mencione feat/fulfillment. Los cambios de Fase 7
> quedan sin staging, commit ni push.
> Fase 8 fue guardada por el usuario en 87ec588. Fase 9 mantiene esta rama por
> instrucción directa, aunque el adjunto mencione feat/notifications; sus cambios
> quedan sin staging, commit ni push.

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
│   ├── kitchen/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   ├── authorization.py
│   │   │   └── orders.py
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
│   ├── cart/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   ├── catalog.py
│   │   │   └── persistence/
│   │   └── presentation/
│   ├── orders/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/persistence/
│   │   └── presentation/
│   ├── payments/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   ├── gateway.py
│   │   │   ├── orders.py
│   │   │   └── persistence/
│   │   └── presentation/
│   ├── fulfillment/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   ├── authorization.py
│   │   │   ├── orders.py
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
    ├── 0002_create_catalog.py
    ├── 0003_create_cart.py
    ├── 0004_create_orders.py
    ├── 0005_create_kitchen.py
    ├── 0006_create_payments.py
    └── 0007_create_fulfillment.py
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
branches, catalog, cart y auditoría compartida antes de leer SQLModel.metadata.
El filtro de autogenerate evita proponer drops de tablas
externas que todavía no pertenecen a los modelos.

Comandos de inspección:

~~~bash
alembic current
alembic heads
alembic history
~~~

La cadena es base -> 0001_phase1 -> 0002_catalog -> 0003_cart -> 0004_orders
-> 0005_kitchen, con un único head: 0005_kitchen. Las revisiones 0001–0004
no se modificaron.
No ejecutes alembic upgrade head sobre una
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
La prueba de Fase 2 apunta a 0002_catalog y comprueba veinte tablas, constraints,
CATALOG_MANAGE y operaciones del adaptador con auditoría. La de Fase 3 aplica
0003_cart, comprueba las tres tablas de carrito, constraints y adaptadores reales,
y hace downgrade exclusivo a 0002 dentro de la transacción de test. Cada prueba trabaja
dentro de una transacción externa que revierte todo el DDL al terminar.
No crean/eliminan bases ni modifican objetos preexistentes. Los downgrades de
prueba solo se ejecutan dentro de esas transacciones TEST, nunca contra
desarrollo/producción. Fase 4 valida también checkout y su rollback, constraints,
seeds, permisos y downgrade de 0004 a 0003 con rechazo seguro de CHECKED_OUT.

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

## Fase 3 — Carrito y cálculo de precios

Cart cubre CU-05/CU-12, RF-15/16/17 y las dependencias RF-12/13/14. Está separado
en Domain, Application, Infrastructure y Presentation, con puertos concretos.
Catalog sigue siendo dueño de disponibilidad, presentaciones, reglas de
adicionales y precios. Cart es dueño de cantidad, notas elegidas, snapshots y
totales. No hay dependencia Catalog -> Cart ni otro sistema de login/sesiones.

### Propiedad y sucursal

El propietario persistente es customers.id, no users.id. Se reutiliza la
dependencia get_current_customer, con JWT guest o registered y validación actual
de Fase 1. Personal sin Customer no tiene carrito. No se crea CART_MANAGE.

Cada Cart tiene una única branch_id. Ningún item tiene branch_id; toda selección
se valida usando cart.branch_id. No hay cambio de sucursal ni traslado automático
de líneas: para cambiar se abandona el carrito y se crea otro. Solo puede existir
un ACTIVE por Customer. DELETE /cart cambia a ABANDONED, conserva sus líneas y
permite crear otro; un abandonado nunca se reutiliza.

GET y las escrituras obtienen el carrito desde el Customer autenticado. No
aceptan customer_id/cart_id en body ni query. Un item ajeno devuelve 404, sin
revelar su propietario. La promoción guest -> registered conserva automáticamente
el carrito al mantener customer_id; se probó mediante OTP/registro reales del
servicio existente, sin cambiar Auth.

### Persistencia y migración 0003

| Tabla | Responsabilidad |
| --- | --- |
| carts | Customer, sucursal, ACTIVE/ABANDONED y timestamps |
| cart_items | Producto, presentación, cantidad, notas y cuatro snapshots |
| cart_item_addon_options | Grupo/opción seleccionados y snapshot de precio por opción |

cart_item_addon_options añade product_addon_id además de la opción, para reconstruir
la selección incluso si Catalog archiva el grupo. Ambos IDs provienen de Catalog,
nunca de un precio del request. La relación es normalizada, sin arrays/JSON de
selecciones persistidas. No se duplican nombres del catálogo.

0003_cart depende de 0002_catalog. Crea solo tres tablas, índices y dos triggers
que reutilizan restaurant_phase1_set_updated_at(). No modifica 0001/0002 ni crea
funciones/roles/permisos. Downgrade a 0002 elimina solo estos objetos de Cart.

CHECK protege estado, cantidad, notas y snapshots no negativos, y exige
unit_price_snapshot = presentation_price_snapshot + addons_price_snapshot.
UNIQUE parcial de customer_id WHERE status='ACTIVE' protege creación concurrente.
UNIQUE de cart_item_id/product_addon_option_id impide seleccionar una opción
duplicada. Las FK a Customer/Branch/Catalog y cart_items -> carts usan RESTRICT;
las opciones seleccionadas usan CASCADE al eliminar físicamente su cart item.

El máximo técnico de quantity es 10000, no una regla comercial del restaurante.
Notas: máximo 1000 caracteres, trim, espacios solos -> null; se permiten saltos
de línea. El HTTP limita cada request a 100 grupos y 100 IDs por grupo como
protección de tamaño, sin inventar opciones de negocio.

Snapshots usan NUMERIC(18,2), ampliando la capacidad respecto a importes
individuales NUMERIC(12,2) de Catalog: una presentación y una suma de adicionales
pueden superar el máximo de una columna individual del catálogo. Todo cálculo
usa Decimal y dos decimales. No se persisten line_total ni totales en carts.

### Integración con Catalog y snapshots

CatalogSelectionGateway es el puerto de Cart. El adaptador llama al
CatalogService.validate_selection existente; no consulta manualmente productos
para recalcular precios. Se amplió ProductSelection de forma compatible con
selected_options, incluyendo IDs de grupo/opción y precio validado de cada una.
Así Cart puede persistir snapshots por opción sin copiar el algoritmo ni volver
a buscar precios.

~~~text
Catalog valida IDs/disponibilidad/presentación/adicionales/notas y calcula precios
    -> base_price_snapshot
    -> presentation_price_snapshot
    -> addons_price_snapshot
    -> unit_price_snapshot
Cart: unit_price_snapshot * quantity = line_total
subtotal = suma(line_total)
charges_total = 0.00
discount_total = 0.00
total = subtotal + charges_total - discount_total
item_count = suma(quantity), no número de líneas
~~~

Los importes HTTP son strings con dos decimales, igual que Catalog. Flutter
envía IDs, quantity y notes; precios, snapshots, line_total, total, descuentos y
cargos se rechazan con 422. Tampoco se admite precio en los grupos del request.

Cada POST /cart/items crea una línea independiente; no se fusionan configuraciones
iguales automáticamente. Producto agotado, inactivo o archivado no se agrega.
No se reserva producto, inventario ni precio indefinido.

### Endpoints

Todos usan JWT de un Customer actual, tag cart y el envelope de errores existente.

| Método y ruta | Resultado |
| --- | --- |
| POST /api/v1/cart | 201; crea con body branch_id |
| GET /api/v1/cart | 200; lee snapshots actuales, sin escrituras/repricing |
| DELETE /api/v1/cart | 204; abandona el ACTIVE |
| POST /api/v1/cart/items | 201; crea línea validada |
| PATCH /api/v1/cart/items/{item_id} | 200; edita/revalida línea propia |
| DELETE /api/v1/cart/items/{item_id} | 204; elimina línea y sus opciones |
| POST /api/v1/cart/recalculate | 200; revalida todo y actualiza snapshots |

Cart inexistente y línea inexistente/ajena: 404. Sin JWT/Customer: 401;
cuenta rechazada por Auth conserva sus códigos existentes. Conflictos de
selección/disponibilidad/ACTIVE duplicado: 409. Datos inválidos: 422.
Indisponibilidad técnica PostgreSQL/Catalog: 503, no se convierte en 404/409.

Ejemplo de POST item; sustituir IDs por recursos reales:

~~~json
{
  "product_id": "00000000-0000-0000-0000-000000000001",
  "presentation_id": "00000000-0000-0000-0000-000000000002",
  "quantity": 2,
  "notes": "Sin cebolla",
  "addons": [
    {
      "addon_id": "00000000-0000-0000-0000-000000000003",
      "option_ids": ["00000000-0000-0000-0000-000000000004"]
    }
  ]
}
~~~

PATCH admite únicamente quantity, notes, presentation_id y addons. Omitido
conserva valor; notes=null limpia observación; addons=[] elimina opciones si
Catalog permite la selección vacía. quantity=0 no elimina: devuelve 422.
PATCH revalida incluso al cambiar solo quantity y actualiza todos los snapshots
de la línea. No permite cambiar product_id.

DELETE y recalculate no requieren body; si se envía JSON, solo se admite un objeto
vacío o null. Campos extra de identidad/precio se rechazan. Ninguna ruta admite
query parameters de identidad/sucursal.

CartResponse contiene id, branch_id, status, items, subtotal, charges_total,
discount_total, total, item_count y timestamps. Cada item contiene IDs, quantity,
notes, opciones seleccionadas con snapshots, los cuatro snapshots, line_total
y timestamps. GET conserva líneas inválidas: el cliente decide eliminarlas.

### Recalculate, atomicidad y concurrencia

GET obtiene las tres tablas en una sola SELECT con LEFT JOIN y ownership,
evitando N+1 y lecturas monetarias mezcladas bajo concurrencia. No consulta Catalog,
no toma FOR UPDATE y no confirma escrituras. Orden de líneas: created_at, id;
opciones: created_at, id.

Todas las mutaciones de un carrito existente bloquean primero el Cart ACTIVE
del Customer, luego la línea cuando corresponde. Así PATCH, DELETE, abandon,
add y recalculate se serializan sobre el mismo padre. PostgreSQL UNIQUE es la
barrera final de creación, donde aún no hay fila Cart para bloquear.

Recalculate valida todas las líneas contra Catalog antes de escribir cualquier
snapshot. Después actualiza líneas y opciones y hace un solo commit. Si una línea
falla, responde CART_RECALCULATION_FAILED 409; no hay cambios parciales ni
eliminación automática. También se revierte todo si falla una escritura/commit.
Los adaptadores no deciden commits de negocio; Application controla la transacción.

Los snapshots de opciones se actualizan junto con el item; IDs/created_at de
opciones conservadas se mantienen. updated_at de Cart/CartItem viene del trigger
existente. Agregar/eliminar una línea también actualiza el timestamp del padre.

Si Catalog cambia entre peticiones: ADD/PATCH usan precio actual; GET conserva
snapshot previo; RECALCULATE actualiza todo. No se garantiza disponibilidad
futura ni se congela precio. Checkout deberá revalidar de nuevo en su propia fase.
Los cambios de clientes no llenan audit_logs administrativos.

### Tests y límites de validación

~~~bash
pytest tests/modules/cart -q
pytest
ruff check .
ruff format --check .
git diff --check
alembic heads
alembic history
pytest -m integration
~~~

La suite añade pruebas de dominio, servicio con Catalog real sobre fakes,
API/JWT/guest->registered, SQL/ownership/locks/consulta única, migración offline
y una integración PostgreSQL opt-in. La integración aplica 0003_cart en TEST vacía,
prueba constraints reales, adaptadores y downgrade 0003 -> 0002, conservando
Catalog y revirtiendo todo en la transacción externa.

Sin TEST_DATABASE_URL las integraciones se omiten. Fase 3 no intenta reconciliar
ni modifica la base manual antigua de 49 tablas; no se ejecuta upgrade/stamp
sobre ella. Los resultados exactos y pendientes están en
[docs/phase3-report.md](docs/phase3-report.md).

Fuera de alcance: checkout, Orders, Payments, Delivery, modalidades/mesa/dirección,
pickup scheduling, Kitchen, inventario cuantitativo, Promotions/Coupons/Roulette,
Notifications y los demás módulos de Fase 4 o posteriores. No hay dependencias
nuevas ni cambios de requirements.txt, .env o puertos.

## Fase 4 — Orders

Orders cubre la creación y consulta de pedidos históricos, CU-06/CU-13 y las
reglas locales de RF-18..37 dentro de los límites de Payments/Kitchen/Notifications.
No implementa la pasarela, despacho real a cocina ni notificaciones.

### Cart → Order, snapshots e idempotencia

POST /api/v1/orders obtiene Customer desde el JWT existente y la sucursal desde
su ACTIVE Cart. Bloquea contexto Customer/Cart, revalida todas las líneas con
la misma política de Catalog, valida la modalidad, persiste Order, líneas,
adicionales, detalle, cálculo horario e historial, marca Cart CHECKED_OUT y
hace un único commit. Cualquier fallo revierte todo. Nunca llama al recalculate
público de Cart ni hace commits desde gateways.

Cart CHECKED_OUT no se modifica, abandona, recalcula ni reactiva. Puede crearse
otro ACTIVE. Sus snapshots originales no se reescriben: el precio final validado
y los totales definitivos pertenecen al Order histórico.

Cada Order conserva nombres de producto/presentación/grupo/opción, importes,
notas/cantidad, contacto del Customer y configuración efectiva de sucursal.
Delivery conserva dirección, destinatario, zona, fee y ETA; Local conserva
etiqueta de mesa y política de confirmación. Cambiar Catalog, perfil, dirección,
mesa o configuración no recalcula un pedido anterior.

Idempotency-Key es obligatorio: 1..128 caracteres ASCII alfanuméricos o . _ : -.
Se recomienda un UUID nuevo para cada intento lógico, conservado en sus retries;
nunca usar un JWT. Mismo Customer/key/payload canónico devuelve el mismo Order.
Payload diferente devuelve 409 IDEMPOTENCY_KEY_REUSED. Tanto creación como
replay responden 201. La huella SHA-256 incluye Customer, source_cart_id,
modalidad y campos pertinentes; normaliza timestamps a UTC. No incluye tokens
ni precios enviados por Flutter. El replay sigue apuntando al pedido original
aunque ya exista un nuevo carrito activo.

UNIQUE(source_cart_id) y UNIQUE(customer_id,idempotency_key) son barreras
PostgreSQL finales. Se resuelve la carrera UNIQUE con rollback y lectura del
ganador. order_number usa BIGINT GENERATED BY DEFAULT AS IDENTITY, no MAX+1;
puede tener huecos por rollback y no es un contador por sucursal.

Los locks son Customer → Cart → CartItems → Branch → Category → Product →
settings/modalidad. Catalog mantiene locks SHARE de categoría/producto hasta
el commit, compatibles con lecturas y excluyentes con administración. Todas las
consultas de selección/nombres se agrupan: cinco consultas Catalog para los
productos seleccionados, no por línea. Una carrera de cambio de categoría
rechaza el checkout y permite reintentar sin adquirir locks fuera de orden.
Lectura de pedidos carga colecciones en lotes, sin N+1 por pedido.

### Contratos de creación y estados iniciales

Se usa discriminated union con mode y extra=forbid. No se aceptan branch_id,
customer_id, IDs del pedido, precios, status, payment_status ni timestamps
administrativos. Pickup/Delivery no admiten payment_method; ONLINE es implícito.

~~~json
{"mode":"LOCAL","table_qr_token":"UUID-del-QR","payment_method":"CASH"}
~~~

~~~json
{"mode":"PICKUP","requested_pickup_at":"2026-10-07T18:30:00-05:00"}
~~~

~~~json
{"mode":"DELIVERY","address_id":"UUID-direccion-propia"}
~~~

| Modalidad | Método | Estado inicial |
| --- | --- | --- |
| LOCAL | ONLINE | PENDING_PAYMENT |
| LOCAL | CASH, confirmación requerida | PENDING_CASH_CONFIRMATION |
| LOCAL | CASH, confirmación no requerida | WAITING |
| PICKUP | ONLINE | PENDING_PAYMENT |
| DELIVERY | ONLINE | PENDING_PAYMENT |

payment_status siempre inicia PENDING. Liberar CASH cambia a WAITING, agrega
history y confirmed_at, pero NO lo marca PAID. Todas las transiciones ejecutadas
se registran en la misma transacción. OrderStatus modela los estados futuros
SCHEDULED, PREPARING, READY, READY_FOR_PICKUP, OUT_FOR_DELIVERY, SERVED,
PICKED_UP, DELIVERED y CANCELLED. La política de dominio limita transiciones por
modalidad y exige PAID antes de activar un ONLINE; también existe CHECK de gating.
No hay endpoints para mark-paid, editar status arbitrario, recalculate Order,
Kitchen, entregas ni cancelaciones.

### LOCAL y administración de mesas

El cliente envía qr_token UUID de alta entropía generado por backend, nunca un
table_id arbitrario. Mesa inexistente/inactiva: 404 TABLE_NOT_FOUND; mesa de
otra sucursal: 409 TABLE_BRANCH_MISMATCH. La mesa no es exclusiva: admite
múltiples pedidos independientes. DELETE desactiva; PATCH rotate_qr_token=true
rota el QR explícitamente. Los pedidos anteriores mantienen su table_label.

### PICKUP, horarios y scheduling

requested_pickup_at exige timezone y una fecha futura suficientemente lejana.
Todos los timestamps se persisten TIMESTAMPTZ; cálculos internos en UTC.
branch_hours usa 0=lunes, 6=domingo, convertido a la timezone de
branch_order_settings. Cierre es exclusivo; admite intervalos nocturnos.
Sin ningún horario configurado no se inventa cierre; si hay horarios parciales,
los días no cubiertos no admiten pickup. Fecha pasada, demasiado próxima o fuera
de horario: 409 PICKUP_TIME_UNAVAILABLE.

KitchenLoadEstimator es un port reemplazable. La implementación determinista
cuenta únicamente WAITING y PREPARING de la sucursal. PENDING_PAYMENT,
PENDING_CASH_CONFIRMATION, SCHEDULED, listos y terminales no cuentan como cola.

~~~text
queue_delay = queue_depth * queue_delay_per_order_minutes
estimated_prep = default_prep_minutes + queue_delay
estimated_ready_at = requested_pickup_at - pickup_buffer_minutes
calculated_kitchen_release_at = estimated_ready_at - estimated_prep
~~~

Se persisten entradas/resultados en order_schedule_calculations, y nombre/teléfono
de recojo en order_pickup_details. Calcular el release no despacha a cocina:
el pedido sigue PENDING_PAYMENT. La política futura de Payments elige SCHEDULED
si aún no es hora, o WAITING si corresponde. El port/repository ya permite
consultar pickups SCHEDULED/PAID vencidos; no se instaló un scheduler falso.

### DELIVERY, cobertura, mínimo, fee y ETA

address_id se consulta por id + customer_id: dirección ajena/inexistente da el
mismo 404 DELIVERY_ADDRESS_NOT_FOUND. Se copia todo el contacto/dirección/lat/lng;
la FK al address usa SET NULL para permitir eliminarlo conservando snapshots.

Migración 0004 siembra políticas globales gratuitas idempotentes: Tarapoto,
Morales y La Banda de Shilcayo. trim y CITEXT evitan diferencias por capitalización.
Una política global gratuita activa precede un override pagado de sucursal.
Las zonas de sucursal permiten fee y travel_minutes configurables. Los ADMIN de
sucursal no pueden editar ni eliminar las políticas globales. Sin cobertura:
409 DELIVERY_ZONE_UNAVAILABLE; nunca se inventa una tarifa ni se hace geocoding.

delivery_minimum_order se compara con el subtotal de productos ANTES del fee.
Incumplimiento: 409 DELIVERY_MINIMUM_NOT_MET. El fee no permite alcanzar el mínimo.
Para esta fase discount_total=0.00 y charges_total=delivery_fee:
total=subtotal+charges_total-discount_total. LOCAL/PICKUP tienen delivery_fee=0.00.
Importes NUMERIC(18,2)/Decimal; API serializa dinero como cadenas de dos decimales.

estimated_delivery_at = now + estimated_prep + estimated_travel_minutes,
con travel de la zona si existe, o default de sucursal. Se guarda como estimación
inicial, no garantía ni recalculado silencioso. No se implementan GPS/mapas,
asignación de repartidores ni tracking en vivo.

### Configuración efectiva y permisos

Defaults conservadores, no reglas inmutables del restaurante:

| Configuración | Default |
| --- | --- |
| cash_payment_requires_confirmation | true |
| delivery_minimum_order | 0.00 |
| default_prep_minutes | 20 |
| queue_delay_per_order_minutes | 5 |
| pickup_buffer_minutes | 5 |
| delivery_default_travel_minutes | 20 |
| timezone | America/Lima |

Minutos configurables 0..1440; prep mínimo 1. Son límites técnicos documentados.
GET de settings sin fila devuelve defaults sin escribir; PATCH inicial hace
UPSERT. Timestamps de defaults no persistidos indican la construcción de esa
configuración efectiva; Order guarda la fotografía usada en su checkout.
La timezone de Orders prima para sus reglas de horario.

ORDER_SETTINGS_MANAGE administra settings/tables/zones;
ORDER_MANAGE permite confirm-cash-release. Ambos se siembran para ADMIN de forma
idempotente y branch-scoped. Se reutilizan permisos/asignación/cuenta actuales
de BD, nunca roles embebidos en el JWT. ADMIN de A no opera sobre B.

### Endpoints y consulta histórica

| Métodos | Ruta /api/v1 | Uso |
| --- | --- | --- |
| POST, GET | /orders | Checkout; historial propio limit=1..100, offset>=0 |
| GET | /orders/{order_id} | Detalle propio; ajeno/inexistente 404 |
| POST | /admin/orders/{order_id}/confirm-cash-release | Liberar CASH LOCAL pendiente |
| GET, PATCH | /admin/orders/branches/{branch_id}/settings | Configuración efectiva |
| GET, POST | /admin/orders/branches/{branch_id}/tables | Listar/crear mesas |
| PATCH, DELETE | /admin/orders/branches/{branch_id}/tables/{table_id} | Editar/rotar/desactivar |
| GET, POST | /admin/orders/branches/{branch_id}/delivery-zones | Listar globales+propias/crear propias |
| PATCH, DELETE | /admin/orders/branches/{branch_id}/delivery-zones/{zone_id} | Editar/desactivar propias |

14 operaciones en 8 paths. POST=201, GET/PATCH/cash release=200, DELETE=204.
401 sin autenticación, 403 sin autorización (incluye cuenta bloqueada según Auth
existente), 404 recurso ajeno/inexistente, 409 conflicto, 422 payload inválido,
503 dependencia técnica caída. Lista ordena created_at DESC, id DESC. El error
envelope existente no revela SQL, DSN, secretos ni valores de input rechazados.
Idempotency-Key/fingerprint/configuración interna no se exponen en OrderResponse.

### Migración 0004 y validación

Once tablas nuevas: orders, order_items, order_item_addon_options,
order_status_history, order_local_details, order_pickup_details,
order_delivery_details, restaurant_tables, branch_order_settings, delivery_zones,
order_schedule_calculations. Junto a fases anteriores son 34 tablas de aplicación.

0004_orders depende de 0003_cart y altera solo su constraint de status para
añadir CHECKED_OUT; 0001/0002/0003 permanecen intactas. Añade constraints, índices,
cuatro triggers reutilizando la función existente, permisos y free-zone seeds.
Downgrade 0004→0003 se niega ANTES de borrar objetos si hay CHECKED_OUT; no
reescribe carritos históricos para hacerlo pasar.

~~~bash
pytest -q tests/modules/orders
pytest -q tests/test_phase4_migration.py
pytest
ruff check .
ruff format --check .
git diff --check
alembic heads
alembic history
pytest -m integration
~~~

Las pruebas PostgreSQL son opt-in, exclusivamente TEST_DATABASE_URL vacía,
marcada como test y distinta de la normal. Sin ella se omiten. No se migra,
altera, borra o stampea la base manual antigua de aproximadamente 49 tablas.
No se valida checkout real contra ella. El servidor puede mostrar Swagger sin
que esa base esté preparada: disponibilidad HTTP no equivale a migración aplicada.

Resultados exactos, archivos y riesgos: [docs/phase4-report.md](docs/phase4-report.md).
Pendiente validación PostgreSQL real y despliegue controlado en base compatible.
RF-25/26/28/34/35/36 quedan parcialmente preparados por depender de Kitchen,
Notifications y Payments; no se atribuye finalización operativa a esas fases.
En el cierre de Fase 4 no se inició Fase 5; su implementación se documenta abajo.

## FASE 5 — KITCHEN: cocina y estados

Kitchen es un slice hexagonal de lectura y preparación. Orders sigue siendo
dueño de `orders.status`, `order_status_history` y su máquina de estados.
No existen nuevas tablas Kitchen, estados paralelos ni timers persistidos.
`KitchenOrdersGateway` y `KitchenAuthorization` separan los casos de uso del ORM.
Orders ofrece un contrato público interno mínimo (`OrderTransitionContext`,
`lock_preparation_order`, `record_preparation_transition`); Kitchen no llama
métodos privados de otro slice ni reconstruye el agregado financiero para leer.

### Endpoints y permisos

Todos están bajo `/api/v1/kitchen/branches/{branch_id}`:

| Método | Ruta | Permiso |
| --- | --- | --- |
| GET | `/queue` | KITCHEN_VIEW |
| GET | `/orders/{order_id}` | KITCHEN_VIEW |
| POST | `/orders/{order_id}/start-preparation` | KITCHEN_MANAGE |
| POST | `/orders/{order_id}/mark-ready` | KITCHEN_MANAGE |

Los POST admiten cuerpo ausente, `null` o `{}`, siguiendo la política existente;
cualquier campo funcional o query desconocida devuelve 422. No se admite
status, actor, reason, timestamp ni payment_status enviado por el cliente.

ADMIN y KITCHEN reciben ambos permisos para asignaciones de sucursal vigentes.
Un JWT no basta: Auth comprueba la cuenta y la autorización consulta User,
Branch, StaffAssignment, Role y Permission actuales. No se confía en roles del
token. KITCHEN no recibe ORDER_MANAGE ni ORDER_SETTINGS_MANAGE.
Sin token: 401; sin permiso, usuario bloqueado o sucursal inactiva: 403.
Sucursal inexistente también devuelve 403 al no existir permiso vigente, sin
revelar recursos. Un pedido de otra sucursal bajo una sucursal autorizada: 404.

### Cola, snapshots y datos mínimos

Respuesta: `generated_at`, `waiting[]`, `preparing[]`, `ready[]`, `limit`,
`offset`, `has_more`. Cola y detalle se limitan a pedidos operativos confirmados:
WAITING, PREPARING, READY para LOCAL/DELIVERY y READY_FOR_PICKUP para PICKUP.
ONLINE exige PAID internamente; CASH LOCAL confirmado mantiene su payment_status.
Se excluyen impagos, pendientes de caja, SCHEDULED y todos los estados fuera de
cocina. Consultar nunca libera ni modifica pedidos programados.

La cola prioriza waiting, preparing y ready; dentro de cada columna usa entrada
al estado ASC, order_number ASC e id ASC. `limit=100` por defecto, máximo 200;
offset 0–100000. Filtros opcionales `mode` y `status`, solo valores de cocina.
Para una cola mayor, el consumidor recorre las páginas indicadas por has_more.
Cada página es una lectura coherente; el polling vuelve a offset 0 porque una
cola cambiante no garantiza continuidad de snapshots entre páginas.

Items y adicionales usan exclusivamente los nombres históricos de Orders.
LOCAL muestra table_label, PICKUP fechas de recojo/listo estimado y DELIVERY ETA.
No hay precios, totales, teléfonos, customer_id, direcciones, coordenadas, QR,
idempotency key, fingerprint ni actor de auditoría en los responses Kitchen.
El detalle y los POST incluyen historial; las tarjetas de cola no lo exponen.

Una consulta operacional PostgreSQL agrega items, addons e historial en el mismo
snapshot MVCC que el estado. No N+1 ni joins a Catalog. La consulta de autorización
y las consultas de Auth son independientes de esa única consulta de proyección.
Polling read-only, sin locks de escritura, WebSocket ni nuevas dependencias.

### Transiciones y tiempos

WAITING → PREPARING; PREPARING → READY (LOCAL/DELIVERY) o READY_FOR_PICKUP
(PICKUP). Se usa FOR UPDATE por id+sucursal, validación oficial Orders y UPDATE
condicionado al estado anterior. Estado e INSERT de history se confirman juntos;
los fallos hacen rollback. confirmed_at, pagos y snapshots no cambian.
History es append-only, con actor obtenido del principal y motivo interno seguro.

Reintento de start mientras PREPARING, o mark-ready en su target correcto:
200 sin INSERT duplicado. Estado incompatible: 409, sin saltos ni retrocesos.
No existen comandos de cancelación, pagos, servir, recoger ni entregar.

Los tiempos se calculan con clock inyectable y timestamps aware del historial:

- waiting_seconds: ahora−WAITING mientras espera; PREPARING−WAITING después;
- preparation_seconds: 0 antes de preparar; ahora−PREPARING preparando;
  READY/READY_FOR_PICKUP−PREPARING una vez listo;
- current_status_seconds: ahora−entrada al estado actual.

Segundos enteros, nunca negativos. No se toma created_at como inicio de espera.
Falta, duplicación o desorden de historia requerido devuelve
503 KITCHEN_HISTORY_INCONSISTENT: no se fabrica un timestamp.

### Migración 0005 y validación

0005_kitchen depende de 0004_orders. Añade dos permisos, sus cuatro relaciones
ADMIN/KITCHEN y dos índices: ix_orders_kitchen_queue parcial por sucursal/estado,
e ix_order_status_history_entry por pedido/estado/fecha/id. Conserva 34 tablas
de aplicación. Downgrade retira solo esos índices y permisos; no modifica pedidos,
historiales ni las migraciones anteriores. No hay create_all ni DDL en startup.

~~~bash
pytest
pytest tests/modules/kitchen -q
pytest tests/test_phase5_migration.py -q
pytest -m integration -q
ruff check .
ruff format --check .
alembic heads
alembic history
git diff --check
~~~

La integración utiliza exclusivamente TEST_DATABASE_URL distinta de la normal,
con nombre de test y esquema vacío, y revierte DDL/datos mediante transacción
externa. Sin esta variable se omite: eso NO valida PostgreSQL real. No tocar la
base manual incompatible ni usar stamp para reconciliarla.

Resultados, archivos, índices, riesgos y pendientes:
[docs/phase5-report.md](docs/phase5-report.md). La Fase 5 no implementó Payments,
scheduler, atención local, entrega pickup/delivery ni Notifications.

## FASE 6 — PAYMENTS

ONLINE PAYMENT ORCHESTRATION: IMPLEMENTADA.
REAL EXTERNAL PAYMENT PROVIDER: NO IMPLEMENTADO / PENDIENTE DE SELECCIÓN.

El adapter productivo falla cerrado con 503 PAYMENT_PROVIDER_UNAVAILABLE.
No se elige pasarela, instala SDK o inventan firmas. El proveedor simulado y su
firma de ejemplo existen únicamente en tests, nunca en la aplicación productiva.

Payments usa el total histórico de Orders, Decimal en PEN; no recalcula desde
Cart/Catalog. Orders conserva su lifecycle, Kitchen observa Orders sin llamadas
directas desde Payments. La deuda histórica Orders.Domain → Cart.Domain se
mantiene; no se amplía mediante dependencias nuevas desde Payments.

### Ledger e intentos

- payments: un pago lógico por Order; CASH/ONLINE; PENDING/PROCESSING/PAID/FAILED,
  paid_at y señal interna reconciliation_required.
- payment_attempts: operaciones externas separadas, key del cliente por pago,
  key propia payment-attempt:<UUID> para proveedor, referencia, estado,
  importe y tiempos. Máximo un intento CREATED/PROCESSING por Payment.
- payment_status_history: cambios financieros con fuente, actor de caja,
  intento, evento y timestamp del backend.
- payment_provider_events: evidencia autenticada mínima y hash del body.
  No se guarda raw payload, firma, tarjetas, headers ni secretos.

Misma Idempotency-Key repite intento. Otra key con intento activo da 409.
Timeout ambiguo mantiene CREATED recuperable con la misma key del proveedor;
un rechazo confirmado conserva FAILED y permite nueva key. PAID no se degrada.
Las garantías externas dependen de la idempotencia real del futuro proveedor.

### API y autorización

| Método | Ruta |
| --- | --- |
| POST | /api/v1/payments/orders/{order_id}/online |
| GET | /api/v1/payments/orders/{order_id} |
| POST | /api/v1/payments/webhooks/{provider_code} |
| POST | /api/v1/admin/payments/branches/{branch_id}/orders/{order_id}/cash/confirm |

Online/GET requieren JWT de CurrentCustomer dueño del Order (guest o registrado).
Online exige Idempotency-Key y body ausente o {}. Body/query extras dan 422:
no admite importe, moneda, PAID ni datos de tarjeta. Initiation no confirma dinero.
Decline devuelve 200 con intento FAILED. Una acción cliente solo puede ser
REDIRECT HTTPS sin credenciales o token PÚBLICO SDK, nunca secreto de proveedor.

GET aplica ownership en SQL, no crea ledger y devuelve 404 si todavía no existe.
Incluye hasta 100 intentos recientes, sin keys/referencias/acciones/historial
interno. No se implementa listado admin ni permiso PAYMENT_VIEW innecesario.

Cash exige usuario activo y PAYMENT_CASH_MANAGE en asignación activa de la
sucursal. Solo ADMIN BRANCH recibe el permiso, no KITCHEN/CUSTOMER. Cobra
LOCAL+CASH no cancelado por el total histórico. Conserva status, confirmed_at e
historial operacional de Orders: no sustituye confirm-cash-release. Reintento
retorna el mismo pago sin nueva historia.

### Webhook y activación

Sin JWT: el adapter autentica los bytes ANTES de construir VerifiedPaymentEvent
y acceder a la base. Hash SHA-256 es trazabilidad, no autenticación. Máximo 64 KiB.
Evento duplicado procesado devuelve 200 sin cambios; mismo ID con otro body, 409.
Mismatch verificado de monto/moneda queda REJECTED y ACK 200 sin pagar.
Referencia desconocida conserva evidencia y devuelve 503
PAYMENT_PROVIDER_EVENT_PENDING para pedir reintento; el mismo evento puede
procesarse cuando la referencia se persista. No fabrica Payment.

Confirmación valida Order/Payment/Attempt, importe y moneda. Guarda pago,
intento, evento, Orders y ambos historiales en una única transacción:

- LOCAL ONLINE y DELIVERY: PENDING_PAYMENT → WAITING, confirmed_at del backend.
- PICKUP: SCHEDULED antes de calculated_kitchen_release_at, WAITING desde ese
  instante, usando reloj backend. Kitchen excluye SCHEDULED.
- CANCELLED: conserva CANCELLED y no entra a cocina; registra verdad financiera
  y marca conciliación. No implementa refund.
- Segundo intento capturado tras PAID conserva evidencia y marca conciliación,
  sin segunda historia PAID ni reactivación. Fallo tardío nunca degrada PAID.

Locks Order → Payment → Attempt; dedupe evento precede esos locks.
Reserva se confirma antes de la red; respuesta se guarda tras bloquear/revalidar.
No se mantiene transacción de DB durante la llamada externa.

### Migración y validación

0006_payments depende de 0005_kitchen, crea cuatro tablas (38 de aplicación),
checks/índices/triggers y permiso de caja. Migraciones 0001–0005 intactas;
sin create_all ni DDL en startup. Downgrade rechaza ledger/eventos no vacíos
ANTES de cualquier DDL para proteger auditoría; solo esquema TEST vacío permite
retirar estas tablas. Nunca elimina Orders/Cart/Catalog/Kitchen.

~~~bash
ruff check .
ruff format --check .
pytest -q
pytest tests/modules/payments -q
pytest tests/test_phase6_migration.py -q
pytest tests/integration/test_phase6_postgresql.py -m integration -q
alembic heads
alembic history
git diff --check
~~~

Integración exige TEST_DATABASE_URL distinta de la normal, nombre TEST y esquema
vacío; revierte todo. Omitida no significa validada. No aplicar upgrade/stamp
a la base manual incompatible. Alembic es la única vía de cambios de esquema
en una base compatible administrada y revisada.

[Informe de Fase 6](docs/phase6-report.md): resultados, archivos y pendientes.
Se conserva chore/backend-foundation, sin staging/commit/push.
No Fase 7, scheduler PICKUP, caja contable, refunds, pagos parciales,
cancelaciones, conciliación automática, notificaciones ni entrega.

## Fase 7 — Fulfillment: delivery y recojo programado

Orders conserva el único estado operacional y order_status_history. Fulfillment
usa un contrato público mínimo de Orders para cuatro acciones explícitas,
autorización de Branches y el grabador de auditoría compartido. No llama a
Payments/Kitchen/Cart/Catalog ni accede a métodos privados de sus repositorios.
Kitchen continúa siendo el único responsable de PREPARING y READY/READY_FOR_PICKUP.
Todas las operaciones de esta fase exigen ONLINE, PAID y confirmed_at del backend.

### Recojos

La recomendación se calcula desde requested_pickup_at, settings actuales y el
conteo actual WAITING/PREPARING de la sucursal:

~~~text
estimated_ready_at = requested_pickup_at - pickup_buffer_minutes
recommended_release_at = estimated_ready_at
                         - default_prep_minutes
                         - queue_depth * queue_delay_per_order_minutes
~~~

No reemplaza calculated_kitchen_release_at ni estimated_ready_at históricos.
GET muestra ambas referencias, minutos hasta liberar e is_due, sin escribir.
SCHEDULED → WAITING solo desde la recomendación actual; antes devuelve 409
PICKUP_NOT_DUE. El lote de hasta 100 usa una sola foto de cola y FOR UPDATE OF
orders SKIP LOCKED; cada pedido liberado queda auditado en Orders con actor,
fecha y motivo. Pedidos bloqueados se revisan en el siguiente ciclo.

READY_FOR_PICKUP → PICKED_UP exige nombre y teléfono completos contra los
snapshots originales. El nombre ignora mayúsculas y espacios repetidos; el
teléfono admite + y separadores de formato, no sufijos ni país inferido. No se
guarda el input de identidad, ni se sustituye por datos del perfil actual.

PICKUP SCHEDULING LOGIC: IMPLEMENTADA.
AUTOMATIC PERIODIC WORKER: NO IMPLEMENTADO / PREPARADO PARA INTEGRACIÓN.
READY_FOR_PICKUP STATE: IMPLEMENTADO.
PUSH NOTIFICATION: PENDIENTE.

### Delivery y retrasos

La cola muestra WAITING/PREPARING/READY/OUT_FOR_DELIVERY de la sucursal, snapshots
de dirección y ETA comprometida. Asignar/reasignar/desasignar requiere personal
activo de esa sucursal; no se crea rol DRIVER. Reasignar cierra el registro
anterior, no lo elimina. Solo hay una asignación activa por Order.

READY → OUT_FOR_DELIVERY exige asignación activa y revalida el personal asignado.
OUT_FOR_DELIVERY → DELIVERED es explícito, conserva historia y cierra la
asignación atómicamente. No se permite reasignar una entrega ya despachada.
Completar sigue autorizado para ADMIN aunque el repartidor haya sido desactivado
después del despacho. No altera tarifas, total, dirección ni ETA histórica.

Retraso es estrictamente referencia > ETA + 15 minutos: exactamente 15 no basta.
La referencia es reloj backend si está activo y la fecha histórica DELIVERED si
terminó; consultar días después no crea un retraso artificial. Un historial
DELIVERED ausente/ambiguo se rechaza de forma segura.

POST detect crea como máximo una incidencia OPEN por Order, con evidencia
inmutable. GET nunca crea incidencias. Aprobar/rechazar requiere acción humana;
customer_responsibility es bool/null explícito, sin inferencia ni compensación
financiera. APPROVED exige descripción; REJECTED no la acepta. Reintento idéntico
del mismo evaluador es idempotente; una decisión diferente devuelve 409.

### Endpoints y permisos

Prefijo común: /api/v1/admin/fulfillment/branches/{branch_id}.

| Método | Sufijo | Permiso |
| --- | --- | --- |
| GET | /pickup/due | FULFILLMENT_VIEW |
| POST | /pickup/release-due | FULFILLMENT_MANAGE |
| POST | /pickup/orders/{order_id}/release | FULFILLMENT_MANAGE |
| POST | /pickup/orders/{order_id}/complete | FULFILLMENT_MANAGE |
| GET | /delivery/queue | FULFILLMENT_VIEW |
| PUT | /delivery/orders/{order_id}/assignment | DELIVERY_ASSIGN |
| DELETE | /delivery/orders/{order_id}/assignment | DELIVERY_ASSIGN |
| POST | /delivery/orders/{order_id}/dispatch | FULFILLMENT_MANAGE |
| POST | /delivery/orders/{order_id}/complete | FULFILLMENT_MANAGE |
| POST | /delivery/delays/detect | DELIVERY_DELAY_REVIEW |
| GET | /delivery/delays | FULFILLMENT_VIEW |
| POST | /delivery/delays/{incident_id}/approve | DELIVERY_DELAY_REVIEW |
| POST | /delivery/delays/{incident_id}/reject | DELIVERY_DELAY_REVIEW |

Solo ADMIN BRANCH recibe estos cuatro permisos; no KITCHEN/CUSTOMER. JWT real y
usuario activo se consultan en cada petición, sin confiar en roles del token.
Consulta de recursos fuera de una sucursal autorizada devuelve 404. Body/query
extras dan 422; precio, estado, actor, dirección, schedule y ETA no son inputs.

Listados: limit 1..100 (50 por defecto), offset >= 0. La cola filtra status solo
por los cuatro estados operacionales. Incidencias filtran OPEN/APPROVED/REJECTED.
Detección usa limit y after_order_number (0 inicial): seguir next_order_number
hasta null, y volver a 0 en el siguiente ciclo para reevaluar pedidos antiguos.
Los segundos positivos fraccionarios se redondean hacia arriba (900.1 → 901),
con saturación a INT32; la comparación del umbral usa fechas sin redondeo.

### Migración y ejecución segura

0007_fulfillment depende de 0006_payments y crea delivery_assignments y
delivery_delay_incidents: 40 tablas de aplicación, 41 con alembic_version.
Incluye UNIQUE parcial de asignación activa, UNIQUE de incidencia por Order,
checks de evidencia/evaluación, seis índices y trigger updated_at compartido.
Se reutilizan los índices existentes de la cola de Orders, sin duplicarlos.
Downgrade aborta antes de cualquier DDL si hay historia de fulfillment.
Migraciones 0001–0006 intactas; sin create_all ni cambios en startup/lifespan.

~~~bash
ruff check .
ruff format --check .
pytest -q
pytest tests/modules/fulfillment -q
pytest tests/test_phase7_migration.py -q
pytest tests/integration/test_phase7_postgresql.py -m integration -q
alembic heads
alembic history
git diff --check
~~~

La integración usa exclusivamente TEST_DATABASE_URL, PostgreSQL dedicado y vacío
distinto de la base normal; revierte DDL y datos. Sin esa variable se omite y no
se declara validación PostgreSQL real. Las carreras probadas en memoria no
sustituyen contención real entre conexiones. La base manual incompatible se
preserva: no upgrade/stamp/autogenerate destructivo ni reconciliación automática.

No scheduler instalado ni bucle en lifespan. Un worker futuro debe invocar los
casos de uso con un actor y permisos vigentes, cerrar su sesión por lote y seguir
el cursor de detección. No se entrega mapa/GPS, proveedor de delivery, refunds,
cupones, stock, notificaciones ni Fase 8.

[Informe de Fase 7](docs/phase7-report.md): alcance, arquitectura, archivos,
13 operaciones, pruebas, límites y pendientes. Misma rama chore/backend-foundation,
sin staging, commit ni push por el agente.

## Fase 8 — Cancellations & Refunds

REFUND ORCHESTRATION: IMPLEMENTADA.
REAL ONLINE REFUND WITH FINANCIAL PROVIDER: PENDIENTE.

El cliente (también Guest con identidad vigente) solicita cancelación; no la
ejecuta. ADMIN evalúa/acepta/rechaza y puede cancelar directamente por
OUT_OF_STOCK u OTHER. Una solicitud PENDING por Order; reintento exacto es
idempotente. Rechazo deja el pedido intacto y conserva historia. Cancelación
directa también resuelve una solicitud pendiente, sin borrar evidencias.

Cancelables: PENDING_PAYMENT, PENDING_CASH_CONFIRMATION, SCHEDULED, WAITING,
PREPARING, READY, READY_FOR_PICKUP, OUT_FOR_DELIVERY.
SERVED/PICKED_UP/DELIVERED no son cancelables. CANCELLED no se reactiva.
Se conserva validate_transition; validate_cancellation es política separada.
Cancelación en ruta cierra la asignación histórica con actor/fecha/reason,
no elimina asignación ni llama a KitchenService.

Paid cancellation obliga a Refund.amount = Payment.amount = Order.total, PEN y
Decimal: sin importe ingresado por cliente, porcentaje o refund parcial.
Order/Payment/items/snapshots/importes históricos no se recalculan.
Payment sigue PAID incluso después de Refund REFUNDED.
Unpaid no crea Refund. Order PAID sin evidencia Payment coherente devuelve 503
y rollback, nunca inventa un cobro. Cero pagado tiene obligación PENDING de 0.00,
sin transferencia ficticia.

CASH: ADMIN confirma devolución efectiva, PENDING → REFUNDED y audit.
ONLINE: reserva/commit → OnlineRefundGateway → persistencia/commit; sin HTTP
dentro de cancelación ni lock DB durante llamada externa. Idempotency-Key
obligatoria; key externa estable deriva de RefundAttempt UUID. Timeout deja
reserva recuperable. Captura original ambigua requiere conciliación.
Proveedor no configurado devuelve 503 sin fingir devolución. Fake solo en tests.

Webhook de reembolso (máximo 64 KiB) se verifica antes de DB, deduplica evento/hash,
rechaza amount/currency mismatch y conserva evidencia. Éxito tardío tras FAILED
registra verdad financiera; fallo tras REFUNDED no la revierte. Múltiples éxitos
señalan conciliación. El webhook de pago original registra Refund en la misma
transacción si confirma dinero sobre CANCELLED, sin reactivar el pedido.

### Operaciones y permisos de Fase 8

Todas usan /api/v1. Nuevos permisos solo ADMIN BRANCH existente:
CANCELLATION_VIEW, CANCELLATION_MANAGE, REFUND_MANAGE.
JWT e identidad actual reales; ownership y sucursal se filtran antes de IDs.
Customer Refund oculta referencias bancarias, keys, payloads, hashes y notas.

| Método | Ruta sin prefijo /api/v1 | Acceso |
| --- | --- | --- |
| POST / GET | /orders/{order_id}/cancellation-requests | Customer propietario |
| GET | /admin/cancellations/branches/{branch_id}/requests | CANCELLATION_VIEW |
| POST | /admin/cancellations/branches/{branch_id}/requests/{request_id}/approve | CANCELLATION_MANAGE |
| POST | /admin/cancellations/branches/{branch_id}/requests/{request_id}/reject | CANCELLATION_MANAGE |
| POST | /admin/cancellations/branches/{branch_id}/orders/{order_id}/cancel | CANCELLATION_MANAGE |
| GET | /admin/cancellations/branches/{branch_id}/orders/{order_id} | CANCELLATION_VIEW |
| GET | /payments/orders/{order_id}/refund | Customer propietario |
| GET | /admin/refunds/branches/{branch_id} | REFUND_MANAGE |
| GET | /admin/refunds/branches/{branch_id}/{refund_id} | REFUND_MANAGE |
| POST | /admin/refunds/branches/{branch_id}/{refund_id}/cash/confirm | REFUND_MANAGE |
| POST | /admin/refunds/branches/{branch_id}/{refund_id}/online/process | REFUND_MANAGE + Idempotency-Key |
| POST | /payments/refund-webhooks/{provider_code} | Firma/protocolo gateway, sin JWT |

Bodies extra_forbid: solicitud {"reason":"..."}, evaluación {} o
{"evaluation_note":"..."}, cancelación {"reason_code":"OUT_OF_STOCK"} o
{"reason_code":"OTHER","reason":"..."}. Confirmar/procesar Refund admite
body vacío/{} exclusivamente. Listas limit 1..100 (default 50), offset >= 0,
filtros status y method_type donde corresponda. Customer create 201, retry 200.
Errores: 401/403/404/409/422/503, envelope seguro sin inputs/secretos.

### Migración y pruebas de Fase 8

0008_cancellations_refunds depende de 0007_fulfillment, seis tablas:
cancellation_requests, order_cancellations, refunds, refund_attempts,
refund_status_history, refund_provider_events. 46 tablas de aplicación, 47 con
alembic_version. FK RESTRICT, NUMERIC(18,2), checks, diez índices, updated_at
compartido en tres tablas y protección histórica/financiera por triggers.
Downgrade aborta antes de cualquier DDL si alguna tabla F8 contiene historia.
0001–0007 intactas. Sin create_all ni DDL en startup.

~~~bash
ruff check .
ruff format --check .
pytest -q
pytest tests/modules/cancellations -q
pytest tests/modules/payments -q
pytest tests/test_phase8_migration.py -q
pytest tests/integration/test_phase8_postgresql.py -m integration -q
alembic heads
alembic history
git diff --check
git status --short --branch
git diff --stat
~~~

Integración solo con TEST_DATABASE_URL explícita, dedicada/vacía y distinta de
normal. Si falta, skip explícito; memoria/SQL compilado no equivale a PostgreSQL
real ni carreras entre conexiones. No aplicar sobre la base manual incompatible
ni stamp/autogenerate/reconciliar automáticamente.
Sin proveedor real no se mueve dinero bancario. Notificaciones se añaden en Fase 9.

[Informe completo de Fase 8](docs/phase8-report.md): arquitectura, archivos,
13 operaciones, invariantes, evidencias y límites. Misma rama
chore/backend-foundation, sin staging/commit/push.

## FASE 9 — NOTIFICATIONS & REALTIME

In-app y SSE implementados en `chore/backend-foundation`. Push orchestration
implementada; entrega móvil real pendiente de proveedor y despliegue de worker.
Sin FCM/APNs ficticio, SDK nuevo, worker infinito ni tareas en lifespan.

Orders conserva el estado/historial y Fulfillment los incidentes de retraso.
Triggers PostgreSQL generan eventos durables, notificaciones y push outbox
en la misma transacción. Ningún servicio de negocio llama NotificationService.
Siete tipos RF-53: recibido, preparación, listo LOCAL/DELIVERY, listo para recojo,
en camino, entregado DELIVERY y retraso desde un incidente existente.
WAITING, SCHEDULED, CANCELLED, SERVED, PICKED_UP, pagos y reembolsos no añaden
notificaciones al cliente; cambios de status/payment_status sí generan señales SSE.

### API de Fase 9

Prefijo `/api/v1`; Authorization Bearer obligatorio, identidad actual y permisos
consultados en DB. Invitados y registrados usan su Customer estable.
ORDER_REALTIME_VIEW solo ADMIN BRANCH; cocina reutiliza KITCHEN_VIEW.

| Método | Ruta sin prefijo | Acceso |
| --- | --- | --- |
| GET | /notifications | Customer propietario |
| GET | /notifications/unread-count | Customer propietario |
| POST | /notifications/{notification_id}/read | Customer propietario |
| POST | /notifications/read-all | Customer propietario |
| GET | /notifications/stream | Customer propietario |
| PUT / DELETE | /notifications/devices/{installation_id} | Customer, reglas de reasignación |
| GET | /admin/realtime/branches/{branch_id}/orders | ORDER_REALTIME_VIEW |
| GET | /admin/realtime/branches/{branch_id}/orders/events | ORDER_REALTIME_VIEW |
| GET | /admin/realtime/branches/{branch_id}/orders/stream | ORDER_REALTIME_VIEW |
| GET | /kitchen/branches/{branch_id}/orders/stream | KITCHEN_VIEW |

Lista: `limit=50` (1..100), `before_sequence_id` descendente; devuelve
`items`, `latest_sequence_id`, `next_before_sequence_id`.
Lectura idempotente, primer read_at irreversible; read-all devuelve marked_count.
El unread es COUNT SQL por propietario. Leer no cancela push ni cambia Orders.
Admin snapshot: limit 100 (1..200), status opcional, after_order_number; por
defecto ocho estados activos y cursor latest_event_id tomado antes de los datos.
Eventos: after_id 0, limit 100 (1..200), orden ascendente.
Errores 401/403/404/409/422/503 con envelope seguro. Bodies/queries extra_forbid.

PUT device devuelve 200 y acepta exclusivamente:
`{"platform":"ANDROID","provider_code":"<proveedor-configurado>","push_token":"<token-SDK>"}`.
IOS también permitido. Provider vacío/no configurado: 503 antes de escrituras.
Instalación UUID estable: PUT repetible, rotación sin duplicar device,
DELETE propietario 204 lógico/idempotente. Token nunca aparece en responses/logs.
Reasignación/rotación cancela outbox no enviado, incrementa generación y no
reenvía historia. Un lease de envío activo bloquea cambio significativo con
409 NOTIFICATION_DEVICE_BUSY. DELETE conserva la barrera hasta vencer el lease.
Un dispositivo nuevo no recibe push retroactivo.

### SSE y reconexión

`text/event-stream`, ready, IDs durables, heartbeat comentario cada 15 s,
poll 1 s, lotes 100; revalida identidad/permisos cada 15 s y entre filas si
el consumidor es lento. Cierra al desconectar, expirar JWT o cumplir 300 s;
el cliente reconecta. Sin transacciones/conexiones DB abiertas durante la espera.
No se admite access_token en URL.

`after_id` explícito prevalece sobre `Last-Event-ID`; ambos son BIGINT >= 0.
Con cursor se reproduce solo el ámbito autorizado; ready conserva ese cursor.
Sin cursor inicia desde MAX comprometido de ese ámbito y ready incluye
resync_required=true: refrescar snapshot/lista/queue después de ready.
Los gaps son válidos, no hay purga/backfill automático.
Un advisory lock transaccional antes de asignar IDs evita que un commit tardío
quede por debajo de un cursor ya consumido; serialización global MVP documentada.

REST es la fuente de verdad, SSE una señal de cambio. Flutter: listar/unread,
abrir customer SSE con latest_sequence_id, deduplicar IDs y refrescar.
Admin: snapshot y stream con latest_event_id. Cocina: cola existente y stream;
sin cursor, refrescar cola tras ready para cerrar la ventana de arranque.
Tras reconexión enviar último ID; si no se conserva, refrescar estado completo.

### Outbox, migración y pruebas

PushGateway + registry sin proveedor productivo. Dispatcher interno reserva
FOR UPDATE SKIP LOCKED en transacciones cortas, commit, envío externo y resultado
fenced por claim_token/generación. Timeout de envío 30 s, lease 120 s;
máximo cinco intentos; backoff
30/120/600/1800 s entre intentos, sin sexto. INVALID_TOKEN desactiva device y
cancela envíos restantes; errores externos no se guardan como texto libre.
Clave externa estable por delivery UUID; entrega externa es al menos una vez,
no exactamente una vez sin deduplicación del proveedor/cliente.

0009_notifications depende de 0008_cancellations_refunds: cuatro tablas
(realtime_order_events, customer_notifications, notification_devices,
notification_push_deliveries), nueve índices, nueve triggers y siete funciones.
50 tablas de aplicación, 51 con alembic_version; FK RESTRICT, identidades
BIGINT ALWAYS, unicidad source/kind y notification/device, históricos inmutables.
Reutiliza updated_at de Fase 1 en dos tablas; 0001–0008 intactas.
Downgrade rechaza cualquier dato F9 antes de DDL. Sin cambios en startup/Docker.

~~~bash
ruff check .
ruff format --check .
pytest -q
pytest tests/modules/notifications -q
pytest tests/test_phase9_migration.py -q
alembic heads
alembic history
git diff --check
git status --short --branch
git diff --stat
# Solo TEST_DATABASE_URL dedicada/vacía/distinta de normal:
pytest -m integration -q
~~~

No ejecutar migración/stamp/autogenerate sobre la base normal manual incompatible.
Sin TEST_DATABASE_URL, integración omitida explícitamente; tests en memoria y
SQL compilado no sustituyen PostgreSQL real. El test de concurrencia real prepara
un schema TEST único y elimina solo sus propios objetos al terminar.
[Informe completo de Fase 9](docs/phase9-report.md) incluye evidencias,
contratos, límites de privacidad/entrega, archivos y pendientes.
Sin staging, commit, push ni Fase 10.

## FASE 10 — ADMINISTRATION & DASHBOARD

Implementada en `chore/backend-foundation` por instrucción directa; el nombre
`feat/admin` del adjunto no provoca un cambio de rama. Fase 9 estaba guardada en
`6e940f4`. Todos los cambios F10 quedan sin staging, commit ni push.

Customers conserva la identidad comercial; Branches conserva personal,
sucursales y horarios; Orders conserva su configuración; Admin aporta únicamente
dashboard y overview de solo lectura. No se duplican User, Customer, Products,
Orders, Payments ni tablas de configuración. Catalog, Orders, Cancellations y
Admin realtime existentes se reutilizan.

### API nueva y permisos

Prefijo `/api/v1`; access JWT registrado obligatorio. Permisos se consultan
actualmente en DB por User activo, assignment vigente, Branch activa y rol BRANCH.
Seis nuevos permisos, concedidos solo a ADMIN BRANCH; se reutiliza STAFF_MANAGE.

| Métodos | Ruta sin prefijo | Permiso |
| --- | --- | --- |
| GET / POST | /admin/branches | BRANCH_VIEW / BRANCH_CREATE |
| GET / PATCH / DELETE | /admin/branches/{branch_id} | BRANCH_VIEW / BRANCH_MANAGE |
| GET / PUT | /admin/branches/{branch_id}/hours | BRANCH_VIEW / BRANCH_MANAGE |
| GET / POST | /admin/branches/{branch_id}/customers | CUSTOMER_VIEW / CUSTOMER_MANAGE |
| GET / PATCH / DELETE | /admin/branches/{branch_id}/customers/{customer_id} | CUSTOMER_VIEW / CUSTOMER_MANAGE |
| GET / POST | /admin/branches/{branch_id}/staff | STAFF_MANAGE |
| PATCH / DELETE | /admin/branches/{branch_id}/staff/{assignment_id} | STAFF_MANAGE |
| GET | /admin/branches/{branch_id}/staff/candidates | STAFF_MANAGE |
| GET | /admin/branches/{branch_id}/configuration | BRANCH_VIEW |
| GET | /admin/dashboard | DASHBOARD_VIEW |

19 operaciones nuevas; aliases de Staff usan el mismo servicio de las rutas
anteriores. POST 201, DELETE 204, otras 200; errores seguros
401/403/404/409/422/503. No nuevos grants a CUSTOMER/KITCHEN ni superadmin.

### Clientes, personal y sucursales

Customer es visible por pedido en la Branch o por procedencia administrativa
`created_by_branch_id` opcional. No se asigna artificialmente una sucursal a
identidades previas. Listas filtradas en SQL antes de paginar: limit=50
(1..100), offset=0 (0..10000), search opcional por prefijo literal de 2..80.

Crear contacto produce Guest sin User/contraseña/verificación/JWT.
Registro y OTP normales promueven el mismo CustomerUUID. Invitado edita
full_name/email; registrado first_name/last_name/email con actualización
Customer+User atómica y revocación de verificación email previa si cambia.
Teléfono y campos de identidad/seguridad no son editables. Nunca se elimina
Registered; Guest solo se borra si procede de esa Branch y no tiene prueba
telefónica ni historia/relaciones. Conflictos no destruyen direcciones/OTP.

Candidates requiere search de 2..80, limit=20 (1..100), devuelve únicamente perfil
seguro de Users ACTIVE/no borrados e indicador already_assigned.
Staff se desactiva con ended_at y se reactiva solo por un actor autorizado,
sin borrar User/assignment. Último ADMIN actual no puede desactivarse/demoverse:
409 LAST_BRANCH_ADMIN, protegido por lock común de Branch y permiso revalidado.

New Branch exige ADMIN activo en otra Branch y crea Branch+7Hours+OrderSettings
oficiales+assignment ADMIN del creador+audit en una transacción.
Code uppercase/único/inmutable; timezone IANA; horas locales, siete días,
overnight permitido y closed con horas NULL. PATCH no acepta is_active/deleted_at.
DELETE es soft y rechaza operaciones activas, pagos/reconciliación pendientes,
refunds sin resolver, cancelaciones pendientes y delivery assignments abiertos.
Branch reactivation opcional no implementada; no existe bypass global de recuperación.

### Configuración y dashboard

GET configuration compone Branch/Hours, BranchOrderSettings, conteos de Tables y
DeliveryZones aplicables y resumen Catalog. Sin JSON genérico editable.
Las APIs existentes de Catalog y de Orders/settings/tables/delivery-zones siguen
siendo los únicos puntos de escritura. Ambos cambios explícitos de timezone
(Branch y settings legacy) sincronizan los relojes por puertos públicos y
mismo commit. No reescriben snapshots/horas UTC de pedidos previos.

Dashboard acepta branch_id/from_date/to_date; sin timezone del frontend.
Día actual por timezone de cada Branch; máximo31 días y100 Branches autorizadas,
bounds UTC [start,end), DST correcto. Más de100 sin filtro produce422,
no ventas truncadas. Devuelve summary, sales_by_mode (LOCAL/PICKUP/DELIVERY),
sales_by_branch con periodos explícitos y top10 productos históricos.

- Gross: SUM Payments.amount PAID por paid_at; no Order.total ni pagos pendientes.
- Refunds: SUM Refunds.amount REFUNDED por refunded_at, aunque el cobro sea viejo.
- Net: gross - refunded; puede ser negativo.
- orders_count: Orders creados por created_at; paid_orders_count: cobros por paid_at.
- Top: SUM OrderItems.quantity por product_id y snapshot, Orders no CANCELLED.

Una sentencia SQL financiera separa agregados para evitar multiplicar money
al unir refunds/items; sin N+1, orders materializadas en Python ni float.
Importes Decimal serializados como strings. No materialized view/BI prematuro.
SSE de F9 se reutiliza como señal de Orders/refetch; no se promete un evento
financiero por cada refund ni se crea otro canal realtime.

### Migración, validación y límites

`0010_admin` depende de `0009_notifications`: cero tablas nuevas (50 aplicación/
51 con Alembic), procedencia Customer nullable RESTRICT, seis permissions,
doce índices, cuatro funciones/cuatro triggers de gates/coherencia timezone.
Downgrade rechaza procedencia no NULL antes de DDL para preservar trazabilidad.
0001–0009 intactas; sin startup migration/create_all/autogenerate/Docker.

~~~bash
ruff check .
ruff format --check .
pytest -q
pytest tests/modules/admin -q
pytest tests/modules/customers -q
pytest tests/modules/branches -q
pytest tests/test_phase10_migration.py -q
alembic heads
alembic history
git diff --check
git status --short --branch
git diff --stat
# Solo URL TEST dedicada, vacía y distinta de la normal:
pytest -m integration -q
~~~

Head de DEFINICIONES: `0010_admin`; no es una afirmación de migración aplicada.
Sin TEST_DATABASE_URL, PostgreSQL real, locks/trigger parser/EXPLAIN quedan
SKIPPED. La base normal manual de49 tablas sin versión Alembic sigue intacta
e incompatible: no ejecutar upgrade/stamp/reset allí sin plan explícito.
Servidor de desarrollo en [Swagger](http://localhost:8000/docs); arranque y
OpenAPI no equivalen a validar operaciones contra esa base.

RF-45/47/48 reutilizados; RF-49 implementado. RF-46 PARCIAL:
Customer/Staff/Branches implementados, Orders previo, Promotions pendiente.
Sin frontend, exports, inventario, contabilidad ni Fase11.
[Informe completo y resultados exactos](docs/phase10-report.md) con63 secciones,
arquitectura, archivos, contratos, pruebas, riesgos y pendientes.

## FASE 11 — FAVORITES, REVIEWS, RECEIPTS & PROMOTIONS

Implementada en `chore/backend-foundation`, desde Fase 10 `87202f0`, por petición
directa del usuario. Sin nueva rama, staging, commit ni push. Cuatro slices propios;
sin God Service customer_extras ni copias de Catalog/Orders/Payments/identidad.

### Funcionalidad y autoridad

Favorites: User registrado, PUT 200/DELETE 204 idempotentes, GET con branch_id y
catálogo público batch. Guest: 403 REGISTERED_ACCOUNT_REQUIRED. Productos ocultos
se omiten sin borrar registro; sold-out visible como no disponible.

Reviews: Customer propietario (Registered/Guest), una reseña por Order. Rating
entero 1..5, comentario plano opcional <=1000. Solo LOCAL/SERVED, PICKUP/PICKED_UP,
DELIVERY/DELIVERED. Sin edición/borrado. REVIEW_VIEW por Branch con filtros y
paginación SQL scoped, sin PII en la proyección administrativa.

Receipts: BOLETA/FACTURA sobre Order pagado, ledger Payment PAID e importe
histórico coincidente; amount/PEN server-owned. FACTURA exige estructura RUC de
11 dígitos, nombre/dirección. Una solicitud por pedido y fingerprint normalizado.
Idempotency-Key requerido en request/process, solo hash en almacenamiento.
RECEIPT_VIEW/MANAGE por Branch. Historia preservada tras cancelación/refund.

RF-55 dominio/gestión implementados; EMISIÓN FISCAL REAL PENDIENTE DE PROVEEDOR.
FiscalDocumentGateway con issue/lookup; default Unconfigured devuelve 503
FISCAL_PROVIDER_UNAVAILABLE sin mutar PENDING. No PDF/XML/CDR/serie/número
fiscal fake. Reserva corta+commit, llamada externa sin transacción, finalización
atómica. Timeout permanece PROCESSING; mismo key concilia con lookup, no reemite.

Promotions: ruleta gratuita RN-23, campañas por Branch draft/configure/activate,
terms visibles, cooldown>=0, máximo diario opcional por timezone de Branch,
vigencia opcional. Prizes product-backed con probability_bps 0..10000,
SUM activos<=10000, secrets.randbelow(10000) servidor. Resto/exhausted/hidden
es NO_PRIZE; no normalización de otros premios. Sin cobro, tokens o compra previa.
Spin idempotente/histórico, Reward único con product_name_snapshot. Expiry lazy,
sin escritura en GET. Solo ADMIN PROMOTION_REDEEM; retry no duplica audit.
Permisos VIEW/MANAGE/REDEEM actuales, no desde claims del JWT. No descuentos en Cart.

### API nueva

22 operaciones bajo `/api/v1`; access JWT siempre obligatorio.

| Métodos | Ruta sin prefijo | Autoridad |
| --- | --- | --- |
| GET | /favorites?branch_id=UUID | Cuenta registrada |
| PUT, DELETE | /favorites/{product_id} | Cuenta propietaria |
| POST, GET | /orders/{order_id}/review | Customer propietario |
| GET | /admin/reviews/branches/{branch_id} | REVIEW_VIEW |
| POST, GET | /orders/{order_id}/receipt | Customer propietario |
| GET | /admin/receipts/branches/{branch_id} | RECEIPT_VIEW |
| POST | /admin/receipts/branches/{branch_id}/{receipt_id}/process | RECEIPT_MANAGE |
| GET | /promotions/roulette?branch_id=UUID | CurrentCustomer |
| POST | /promotions/roulette/spins | CurrentCustomer |
| GET | /promotions/rewards | Customer propietario |
| GET, POST | /admin/promotions/branches/{branch_id}/roulette/campaigns | PROMOTION_VIEW / MANAGE |
| GET, PATCH | /admin/promotions/branches/{branch_id}/roulette/campaigns/{campaign_id} | PROMOTION_VIEW / MANAGE |
| POST | /admin/promotions/branches/{branch_id}/roulette/campaigns/{campaign_id}/deactivate | PROMOTION_MANAGE |
| POST | /admin/promotions/branches/{branch_id}/roulette/campaigns/{campaign_id}/prizes | PROMOTION_MANAGE |
| PATCH, DELETE | /admin/promotions/branches/{branch_id}/roulette/campaigns/{campaign_id}/prizes/{prize_id} | PROMOTION_MANAGE |
| POST | /admin/promotions/branches/{branch_id}/rewards/{reward_id}/redeem | PROMOTION_REDEEM |

Request/spin/create 201 (también retry), Favorite PUT 200, softDELETE 204, resto 200.
ErrorResponse 401/403/404/409/422/503; bodies/queries extra_forbid, limit 50 (1..100),
offset 0 (0..10000). Review/Receipt fechas locales inclusivas opcionales; bounds UTC
[start,end), sin timezone de frontend ni límite dashboard de 31 días aplicado artificialmente.
Spin body solo `{"branch_id":"UUID"}`; no outcome/prize/customer/draw/expiry.
Receipt body solo document_type y destinatario. Códigos y contratos detallados
en [informe F11](docs/phase11-report.md).

### Migración y validación

`0011_customer_extras` depende de `0010_admin`: nueve tablas nuevas,
59 aplicación/60 con Alembic, catorce índices, trece triggers, cinco funciones propias.
Seis permissions solo ADMIN BRANCH, sin grants a CUSTOMER/KITCHEN.
FK RESTRICT, historial inmutable, fiscal no-delete, sum prob y unique active campaign.
Downgrade rechaza cualquier dato F11 antes de DELETE/DDL; no modifica fases previas.

~~~bash
ruff check .
ruff format --check .
pytest -q
pytest tests/modules/favorites -q
pytest tests/modules/reviews -q
pytest tests/modules/receipts -q
pytest tests/modules/promotions -q
pytest tests/test_phase11_migration.py -q
alembic heads
alembic history
git diff --check
git status --short --branch
# Solo TEST_DATABASE_URL dedicada, VACÍA y distinta de la normal:
pytest -m integration tests/integration/test_phase11_postgresql.py -q
~~~

Head de definiciones 0011, NO migración aplicada a la base normal.
No existe TEST_DATABASE_URL: tests PostgreSQL: 6 SKIPPED; parser/locks/carreras reales
pendientes. La base normal observada en Fase 10 tenía 49 tablas sin Alembic.
No se modificó; el intento read-only desde WSL en F11 recibió connection refused.
no upgrade/stamp/reset allí sin plan explícito. Servidor [Swagger](http://localhost:8000/docs)
activo y 22 operaciones F11 registradas; no demuestra CRUD sobre esa base.

RF-08/56/57/58 y RN-23 implementados. RF-55 separado de emisión legal pendiente.
RF-46: el gap Promotions de F10 queda cubierto para esta ruleta/rewards; no se
declara motor general de marketing/descuentos. Informes previos son históricos.
[Informe completo F11](docs/phase11-report.md), 66 secciones, evidencia y pendientes.
Validación final: 2511 passed, 18 skipped (PostgreSQL opt-in), sin fallos;
343 pruebas nuevas F11 aprobadas, Ruff y formato aprobados.
Sin nueva dependencia, Docker, SSE/push, proveedor inventado, frontend ni Fase 12.

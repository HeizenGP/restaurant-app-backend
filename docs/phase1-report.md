# Informe técnico — Fase 1: usuarios, autenticación y sucursales

Fecha: 2026-10-06. Repositorio: `/home/heizen27/proyectos/restaurante-backend`.
Rama conservada: `chore/backend-foundation`. HEAD: `34b4638`.

El código de Fase 1 está implementado y disponible para revisión, con 141
pruebas aprobadas. No se afirma validación end-to-end contra PostgreSQL:
la conexión está rechazada y no existe TEST_DATABASE_URL. No se aplicaron
migraciones, stamp, commits ni push. El proveedor real de SMS queda deliberadamente
sin integrar, conforme al alcance solicitado.

## 1. Estado inicial encontrado

Fase 0 existente y funcional: factory FastAPI, lifespan, API v1, Settings,
engine/sesiones async, health/readiness, errores, logging, CORS, Alembic,
Pytest y Ruff. La revisión inicial fue sobre un árbol limpio; 29 pruebas
existentes aprobaban. Las dependencias necesarias ya estaban instaladas.

El adjunto mencionaba `feat/auth-and-users`, pero la instrucción humana posterior
pidió trabajar en la misma rama de la terminal. Por eso se conservó
`chore/backend-foundation`, sin crear rama ni worktree. El checkout Windows
inicial no se utilizó como repositorio del backend.

## 2. Arquitectura implementada

Se extiende Fase 0 mediante slices auth, customers y branches. Domain utiliza
Python puro; application declara casos de uso, DTOs y puertos concretos;
infrastructure implementa SQLAlchemy/SQLModel y seguridad; presentation valida
HTTP y mapea DTOs a schemas. Una prueba AST comprueba que domain/application
no importen FastAPI, ORM, PyJWT, pwdlib ni adapters externos.

Puertos: PasswordHasher, TokenService, OtpCodeService, OtpSender,
RefreshTokenHasher, AuthRepository, CustomerRepository/CustomerUnitOfWork y
BranchRepository. No se introdujeron repositorios, servicios ni controladores
genéricos. Los límites transaccionales pertenecen a los casos de uso/UoW.

## 3. Estructura final de carpetas

```text
app/
├── main.py                         # Factory de Fase 0 conservada
├── lifespan.py                     # Composition root ampliado
├── modules/
│   ├── health/                     # Slice de Fase 0 conservado
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
│   └── branches/
│       ├── application/
│       ├── infrastructure/persistence/
│       └── presentation/
├── presentation/api/v1/
└── shared/{domain,application,infrastructure}/
migrations/versions/
tests/
├── integration/
├── modules/{health,auth,customers,branches}/
└── test_phase1_{foundation,migration}.py
docs/phase1-report.md
```

Customers y branches no tienen carpetas domain vacías: sus necesidades actuales
se expresan mediante DTOs/puertos, y reutilizan Principal de auth.

## 4. Archivos creados

Inventario funcional; se incluyen además los `__init__.py` correspondientes:

- `app/modules/auth/domain/models.py`: enums y Principal.
- `app/modules/auth/application/{errors,exceptions,ports,repository,security,services,types}.py`.
- `app/modules/auth/infrastructure/persistence/{models,repositories}.py`.
- `app/modules/auth/infrastructure/security/{otp,otp_sender,passwords,refresh_tokens,tokens}.py`.
- `app/modules/auth/presentation/{dependencies,router,schemas}.py`.
- `app/modules/customers/application/{dtos,exceptions,ports,services}.py`.
- `app/modules/customers/infrastructure/persistence/{models,repositories}.py`.
- `app/modules/customers/presentation/{dependencies,router,schemas}.py`.
- `app/modules/branches/application/{errors,ports,services}.py`.
- `app/modules/branches/infrastructure/persistence/{models,repositories}.py`.
- `app/modules/branches/presentation/{dependencies,router,schemas}.py`.
- `app/shared/domain/time.py`.
- `migrations/versions/0001_create_phase1_identity_branches_customers.py`.
- `tests/modules/auth/{conftest,fakes,test_api,test_domain_models,test_otp,test_passwords,test_repositories,test_services,test_tokens}.py`.
- `tests/modules/customers/{test_api,test_repositories,test_services}.py`.
- `tests/modules/branches/test_branches.py`.
- `tests/test_phase1_foundation.py` y `tests/test_phase1_migration.py`.
- `tests/integration/test_phase1_postgresql.py`.
- `docs/phase1-report.md`, este informe.

Son 71 archivos nuevos incluyendo paquetes y este informe: auth 25,
customers 14, branches 11, pruebas 18, helper UTC 1, migración 1 e informe 1.

## 5. Archivos modificados

Once archivos previamente versionados:

- `.env.example`: configuración JWT/OTP, sin secretos reales.
- `README.md`: documentación, bootstrap, migraciones, pruebas y trazabilidad.
- `app/lifespan.py`: composición de adapters, manteniendo engine y health.
- `app/presentation/api/v1/router.py`: registro de los tres routers.
- `app/presentation/errors.py`: taxonomía HTTP y CORS seguro en errores 500.
- `app/shared/application/exceptions.py`: errores comunes específicos.
- `app/shared/infrastructure/config/settings.py`: configuración y guardas.
- `app/shared/infrastructure/database/dependencies.py`: errores DB seguros.
- `migrations/env.py`: imports de metadata y conexión externa para test aislado.
- `pyproject.toml`: marcador integration, sin deshabilitar reglas Ruff.
- `tests/test_cors.py`: regresión de CORS para errores internos.

No se modificaron main.py, requirements.txt, configuración Docker ni .env real.
Se eliminaron únicamente copias temporales propias y un backup de parche;
los archivos definitivos permanecen en el repositorio.

## 6. Tablas SQLModel implementadas

| Slice de persistencia | Tablas |
| --- | --- |
| auth | roles, permissions, role_permissions, users, user_roles, refresh_tokens |
| branches | branches, branch_hours, staff_assignments |
| customers | customers, otp_challenges, customer_addresses |

Son las doce tablas solicitadas, sin objetos de fases futuras. Se utilizan
UUID, TIMESTAMPTZ, CITEXT, SMALLINT IDENTITY, FKs, checks, índices y unicidad.
Customer.is_guest se genera desde user_id IS NULL. Horarios admiten cierre
nocturno; cuando is_closed=true ambas horas deben ser NULL. Direcciones tienen
índice único parcial para un único default por customer.

## 7. Migración Alembic creada

Archivo: `0001_create_phase1_identity_branches_customers.py`.
Revisión: `0001_phase1`. Padre: base, sin revisión de negocio previa en Fase 0.

Upgrade crea solo los objetos de Fase 1; no contiene DROP TABLE/COLUMN ni
elimina extensiones. Habilita citext/pgcrypto con IF NOT EXISTS y seeds
idempotentes. Incluye triggers GLOBAL/BRANCH, protección de cambios de scope y
updated_at con clock_timestamp(). El downgrade elimina solo esta fase en orden
inverso y conserva extensiones compartidas; únicamente se compiló offline.

La migración sirve para una BD nueva. No es un reconciliador automático de un
esquema preexistente. El README exige inspección y comparación; cualquier stamp
o reconciliación requiere decisión humana explícita.

## 8. Roles creados/configurados

CUSTOMER/GLOBAL, ADMIN/BRANCH y KITCHEN/BRANCH. Registro asigna CUSTOMER en
user_roles. Personal utiliza staff_assignments, nunca ADMIN en user_roles.
La migración no crea cuentas, administradores ni contraseñas.

## 9. Permisos creados/configurados

STAFF_MANAGE, asignado a ADMIN mediante role_permissions. KITCHEN no recibe
permiso administrativo. No se crean permisos de catálogo/pedidos sin uso.
El README documenta la asignación DBA auditada del primer ADMIN a un usuario
existente y a una sucursal activa, sin credenciales predeterminadas.

## 10. Endpoints implementados

Todas las rutas siguientes tienen prefijo `/api/v1`:

| Método | Ruta | Resultado exitoso |
| --- | --- | --- |
| POST | /auth/otp/request | 202, aceptación y debug OTP solo si habilitado dev/test |
| POST | /auth/otp/verify | 200, prueba phone_verification |
| POST | /auth/register | 201, access + refresh |
| POST | /auth/guest | 200, access limitado sin refresh |
| POST | /auth/login | 200, access + refresh |
| POST | /auth/refresh | 200, nuevo par rotado |
| POST | /auth/logout | 204 |
| POST | /auth/password/change | 204 |
| POST | /auth/phone/change | 204 |
| GET | /customers/me | 200, perfil propio |
| PATCH | /customers/me | 200, perfil seguro actualizado |
| GET | /customers/me/addresses | 200, direcciones propias |
| POST | /customers/me/addresses | 201 |
| PATCH | /customers/me/addresses/{address_id} | 200 |
| DELETE | /customers/me/addresses/{address_id} | 204 |
| GET | /branches | 200, sucursales activas |
| GET | /branches/{branch_id} | 200, sucursal activa y horarios |
| GET | /branches/{branch_id}/staff | 200, autorizado por sucursal |
| POST | /branches/{branch_id}/staff | 201 |
| PATCH | /branches/{branch_id}/staff/{assignment_id} | 200 |

Health y readiness de Fase 0 se conservan. OpenAPI publica response_model y
schemas de error; los routers nuevos no devuelven objetos SQLModel directamente.
La selección de sucursal es un branch_id elegido por el frontend, sin endpoint
artificial select-branch ni estado global del servidor.

## 11. Flujo de registro

OTP REGISTER → prueba válida con teléfono → validación de datos y duplicados →
Argon2 → User activo y teléfono verificado → CUSTOMER global → Customer nuevo
o invitado promovido conservando id → hash refresh → commit único → par JWT.
Unicidad DB resuelve carreras; IntegrityError se traduce sin exponer valores.

## 12. Flujo guest

OTP GUEST_ACCESS → prueba válida → nombre obligatorio → Customer sin User.
Si ya existe guest con ese teléfono se reutiliza. Si está ligado a registrado
se exige autenticación registrada. Solo se entrega access guest. La promoción
posterior conserva Customer y direcciones; el access guest previo deja de
aceptarse cuando Customer ya está asociado a User.

## 13. Flujo OTP

Seis dígitos con secrets, HMAC-SHA256 y pepper privado, comparación constante,
expiración, máximo de intentos, consumo único, invalidación y cooldown.
Los intentos rechazados se confirman para no reiniciar el contador con rollback.
Un advisory lock por teléfono/propósito serializa incluso el primer challenge.

OtpSender de memoria existe solo en development/test y no escribe códigos en
logs. Debug está deshabilitado por defecto y es inválido en staging/production.
Sin proveedor real, esos entornos fallan de forma segura con 503 y rollback.
LOGIN es un propósito compatible, no un login OTP implementado.

La prueba JWT emitida después del consumo conserva validez por teléfono y
propósito hasta expirar; no se persiste un jti de prueba de un solo uso.
Esto no permite reutilizar el challenge OTP ni usar esa prueba como access.

## 14. Flujo login

Email o teléfono + contraseña. Usuario inexistente y contraseña incorrecta
comparten INVALID_CREDENTIALS; un hash dummy evita omitir el trabajo Argon2 en
cuenta inexistente. Se verifica estado ACTIVE y ausencia de deleted_at, se
rehash si procede, actualiza last_login_at y emite tokens transaccionalmente.
Las cuentas de personal también pueden autenticarse sin Customer.

## 15. Flujo refresh

Verifica firma, expiración, emisor, audiencia y tipo refresh. Bloquea User antes
del token, verifica hash/propiedad/revocación/expiración, revoca el anterior y
almacena solo SHA-256 del nuevo. Un único commit confirma la rotación. El token
viejo no puede volver a rotar. Este orden evita inversión frente a cambio de
contraseña, que también bloquea User antes de revocar sus tokens.

## 16. Flujo logout

Valida refresh, busca hash y persiste revoked_at; la revocación repetida es
idempotente para un refresh todavía válido. No hay blacklist en memoria.
Un access emitido conserva su duración corta; bloqueo/desactivación/eliminación
de cuenta se verifica en cada petición, independientemente de expiración JWT.

## 17. Manejo de passwords

pwdlib/Argon2, rehash disponible; no hashes rápidos para contraseñas. Política
de 8–128 caracteres, no vacío ni compuesto únicamente por espacios, sin
exigencias de símbolos/mayúsculas. SecretStr en requests sensibles. El trabajo
Argon2 de los casos de uso se ejecuta fuera del event loop. Cambiar contraseña
requiere la actual y revoca todos los refresh activos.

## 18. Autorización por sucursal

Principal registrado + User activo/no eliminado + Branch activa/no eliminada +
asignación activa/no finalizada + rol BRANCH + permiso actual STAFF_MANAGE +
misma branch_id. Se consulta la DB; los JWT no transportan autoridad de roles.
ADMIN de A no administra B; guest y CUSTOMER sin asignación administrativa se
rechazan. La edición bloquea la asignación y la desactivación conserva ended_at.
Triggers DB impiden insertar roles de scope incorrecto aun fuera de la API.

## 19. Perfil y direcciones

GET/PATCH propio para guest o registrado. Guest modifica full_name; registrado
first_name/last_name/email, sincronizando User/Customer y anulando verificación
del email sustituido. Se prohíben phone, roles, estado e identidad en PATCH.
Cambio de teléfono exige prueba PHONE_VERIFY y actualiza ambas identidades en
una transacción; no fusiona ni desplaza otros Customer existentes.

Ownership se obtiene del principal, nunca de un customer_id del body. Direcciones
ajenas se responden como inexistentes. Cambio de default bloquea Customer y
desmarca el anterior dentro de la transacción; el índice único parcial es la
última barrera. Solo customer_addresses se elimina físicamente.

## 20. Variables nuevas de entorno

JWT_SECRET, JWT_ALGORITHM=HS256, JWT_ISSUER, JWT_AUDIENCE,
ACCESS_TOKEN_EXPIRE_MINUTES=15, REFRESH_TOKEN_EXPIRE_DAYS=30,
PHONE_VERIFICATION_TOKEN_EXPIRE_MINUTES=10, OTP_PEPPER,
OTP_EXPIRE_MINUTES=5, OTP_MAX_ATTEMPTS=5,
OTP_RESEND_COOLDOWN_SECONDS=60 y OTP_DEBUG_EXPOSE_CODE=false.

No son reglas de negocio inmutables. Staging/production rechaza valores
ausentes, débiles o placeholders, y debug OTP. Dev/test genera secretos aleatorios
efímeros si faltan; deben configurarse valores estables e independientes para
conservar sesiones/challenges entre reinicios. .env.example contiene placeholders,
no secretos reales. TEST_DATABASE_URL es exclusivo del test de integración.

## 21. Dependencias nuevas

Ninguna. requirements.txt permanece intacto. Se reutilizan las dependencias
instaladas; entorno comprobado con Python 3.14.4.

## 22. Resultado de ruff check .

Ejecutado dentro de .venv: `All checks passed!`, exit code 0.
No se deshabilitaron reglas. `git diff --check` también pasa.

## 23. Resultado de ruff format --check .

Ejecutado dentro de .venv: `114 files already formatted`, exit code 0.

## 24. Resultado de pytest

Ejecución final: `pytest` → **141 passed, 1 skipped in 7.32s**, exit code 0.
Incluye las pruebas de Fase 0 y nuevas pruebas unitarias, HTTP con overrides,
persistencia con mocks, límites transaccionales y migración offline.

Ejecución explícita `pytest -q -m integration` → **1 skipped, 141 deselected**:
TEST_DATABASE_URL no está configurado. Pytest normal omite siempre esa prueba.

## 25. Resultado de alembic current

Ejecutado contra la configuración existente; exit code 1, ConnectionRefusedError.
No se puede determinar la revisión aplicada mientras no haya conexión. El detalle
de excepción/DSN se capturó sin publicar trazas que pudieran incluir credenciales.

## 26. Resultado de alembic heads

Exit code 0: `0001_phase1 (head)`.

## 27. Resultado de alembic history

Exit code 0:

```text
<base> -> 0001_phase1 (head), Create Phase 1 identity, customer and branch persistence.
```

## 28. Estado de PostgreSQL/migraciones

La configuración existente apunta a localhost:5432. Una conexión de inspección
read-only falló con ConnectionRefusedError. No se pudo enumerar el esquema ni
comparar tablas preexistentes. No se ejecutó upgrade, downgrade online ni stamp.

La prueba opcional requiere TEST_DATABASE_URL, nombre dedicado con indicador
test, distinta de la base normal y sin objetos previos. Aplica upgrade y verifica
tablas/seeds/columna generada/índice default mediante una conexión inyectada en
Alembic; una transacción externa revierte todo el DDL al terminar. No crea ni
elimina bases. La compilación offline no sustituye esa verificación PostgreSQL.

## 29. Resultado de endpoints probados

Se levantó temporalmente Uvicorn con --reload en un puerto loopback libre,
sin modificar puertos de PostgreSQL/Docker. Se terminó el grupo de procesos
del servidor y del reloader al finalizar.

| Petición real al servidor temporal | Resultado |
| --- | --- |
| GET /api/v1/health | 200 |
| GET /api/v1/health/ready | 503 DEPENDENCY_UNAVAILABLE |
| GET /api/v1/branches | 503 DEPENDENCY_UNAVAILABLE |
| GET /api/v1/customers/me sin credencial | 401 AUTHENTICATION_REQUIRED |
| POST /api/v1/auth/login con datos sintéticos | 503 DEPENDENCY_UNAVAILABLE |
| POST /api/v1/auth/otp/request con datos sintéticos | 503 DEPENDENCY_UNAVAILABLE |
| POST /api/v1/auth/refresh con token inválido | 401 TOKEN_INVALID |
| POST /api/v1/auth/register con prueba inválida | 401 TOKEN_INVALID |
| GET /openapi.json | 200; 18 paths v1, con múltiples métodos |

Los 503 son esperados por ausencia de DB, no prueba de flujos persistidos.
Los flujos exitosos de OTP, registro, guest/promoción, login, refresh/logout,
password/phone, perfil/direcciones y staff se validaron por TestClient usando
adapters de seguridad reales y repositorios/UoW fake o dependencias sustituidas.
También se verificaron errores de permisos entre sucursales, ownership,
mass assignment, bloqueo actual y rechazo de tipos JWT incorrectos.

## 30. Git status final

Once archivos modificados y 71 archivos nuevos sin staging, agrupados por Git:

```text
## chore/backend-foundation...origin/chore/backend-foundation
 M .env.example
 M README.md
 M app/lifespan.py
 M app/presentation/api/v1/router.py
 M app/presentation/errors.py
 M app/shared/application/exceptions.py
 M app/shared/infrastructure/config/settings.py
 M app/shared/infrastructure/database/dependencies.py
 M migrations/env.py
 M pyproject.toml
 M tests/test_cors.py
?? app/modules/auth/
?? app/modules/branches/
?? app/modules/customers/
?? app/shared/domain/time.py
?? docs/
?? migrations/versions/0001_create_phase1_identity_branches_customers.py
?? tests/integration/
?? tests/modules/auth/
?? tests/modules/branches/
?? tests/modules/customers/
?? tests/test_phase1_foundation.py
?? tests/test_phase1_migration.py
```

HEAD sigue siendo 34b4638, igual al inicio. No commit, push, merge ni rebase.

## 31. Git diff --stat

```text
 .env.example                                       |  15 +
 README.md                                          | 707 ++++++++++++++++-----
 app/lifespan.py                                    |  57 +-
 app/presentation/api/v1/router.py                   |   6 +
 app/presentation/errors.py                         |  36 +-
 app/shared/application/exceptions.py               |  30 +
 app/shared/infrastructure/config/settings.py        |  55 +-
 app/shared/infrastructure/database/dependencies.py |  12 +-
 migrations/env.py                                  |  12 +-
 pyproject.toml                                     |   3 +
 tests/test_cors.py                                 |  21 +
 11 files changed, 782 insertions(+), 172 deletions(-)
```

Importante: git diff --stat no incluye archivos untracked. Los 70 archivos
nuevos de implementación/pruebas anteriores a este informe agregan 8.530 líneas;
este informe es el archivo nuevo 71. No se hizo git add para alterar ese estado.

## 32. Riesgos o pendientes encontrados

- Falta validar migración, constraints/triggers y flujos reales contra PostgreSQL
  seguro. Hace falta que el servicio vuelva a aceptar conexiones y una URL de test
  exclusiva; no se cambió Docker ni se reinició infraestructura externa.
- Si desarrollo ya tiene tablas, hay que compararlas y definir baseline o una
  reconciliación no destructiva; no ejecutar upgrade/stamp ciegamente.
- Proveedor SMS real no definido: conectar un OtpSender real antes de habilitar
  los flujos OTP en staging/production. El adapter incluido no finge entrega allí.
- Configurar secretos fuertes, estables e independientes; valores efímeros solo
  sirven para dev/test. Los placeholders no son credenciales utilizables reales.
- OTP tiene control por teléfono/propósito; limitación adicional por IP, cuotas
  SMS y observabilidad operativa deben evaluarse al desplegar el proveedor real.
- Logout no invalida de inmediato access ya emitido; es una decisión coherente
  con access stateless de vida corta, sin listas en memoria ni tablas adicionales.
- La prueba phone_verification es reutilizable durante su TTL para el mismo
  teléfono/propósito, a diferencia del challenge OTP consumido de un solo uso.
- Cambiar teléfono requiere una identidad Customer; las cuentas de personal sin
  Customer pueden login/refresh/password/staff, no usar ese flujo de cliente.
- Revisión de seguridad de diff y los 82 archivos modificados/nuevos: sin coincidencias de secretos
  configurados reales, claves privadas o JWT literales. .env está ignorado y no
  versionado. Las credenciales y teléfonos presentes en tests son sintéticos.

Se detiene aquí para revisión humana: no se inició Fase 2 ni se publicaron cambios.

## 33. RF-08 deliberadamente pendiente

Perfil, datos personales y direcciones implementados. Historial de pedidos
requiere Orders; favoritos requiere Catalog. No se crearon tablas, endpoints ni
implementaciones ficticias para esas funcionalidades. RF-02 solo prepara
multi-sucursal; catálogo común también queda para la fase posterior.

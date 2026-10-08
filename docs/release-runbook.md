# Runbook de release

Este documento describe pasos para un operador autorizado; no los ejecuta.
F12 no migra la base normal, no hace deploy, commit, push ni tag.

## 1. Preflight local y CI

Desde la raíz del checkout WSL y con el virtualenv activo:

```bash
python -m pip install -r requirements.txt
python -m pip check
ruff check .
ruff format --check .
python -m compileall -q app tests scripts
pytest -m "not integration"
pytest
python scripts/export_openapi.py --check
python scripts/release_check.py
alembic heads
alembic history
git diff --check
git status --short --branch
```

Un exit 0 de pytest con skips no aprueba PostgreSQL. No usar pytest-xdist
contra el mismo TEST DB; la verificación de vacío exige ejecución serial.

## 2. PostgreSQL TEST

Configurar TEST_DATABASE_URL mediante el entorno/secret store, nunca en chat,
argv, commits ni artefactos. Host PostgreSQL explícito; database con marcador
test, distinta de normal, vacía, sin relaciones de usuario en ningún schema.
El usuario TEST necesita crear schemas/extensiones y ejecutar migrations;
estos privilegios NO deben copiarse al rol runtime de producción.

```bash
pytest -m integration -rP
pytest tests/integration/test_phase12_release_postgresql.py -m integration -q
pytest tests/e2e -m "integration and e2e" -q
pytest -m performance -s
```

El harness aplica Alembic, no migrar antes con un segundo comando. Nunca
usar stamp, create_all, reset, drop de schema público ni una URL normal.
F12 crea y elimina únicamente su schema TEST UUID validado y de su propiedad.
Los tests históricos anteriores usan sus revisiones específicas; F12 hace
0001 → head de una sola vez y prueba persistencia desde otro pool.
CI provisiona PostgreSQL 17 aislado por job; REQUIRE_POSTGRES_INTEGRATION=1
convierte ausencia de URL en failure, no skip. No existe deploy job.

## 3. Configuración productiva

.env.production.example es deliberadamente inválido. Obtener secretos aleatorios
distintos JWT_SECRET/OTP_PEPPER del secret store, credenciales DB no-placeholder,
APP_ENV=production, APP_DEBUG=false, OTP_DEBUG_EXPOSE_CODE=false y CORS_ORIGINS
exactos. Si se usa DATABASE_URL, también debe contener credenciales no-placeholder;
autenticación IAM/sin contraseña no está implementada en este contrato.

```bash
python scripts/release_check.py --production
```

Este check no lee .env, no conecta a DB y no certifica proveedores.
Secretos nunca deben entrar en comandos, logs o capturas. Revocar y rotar si
se filtran; cambiar JWT_SECRET invalida tokens existentes, planificar sesiones.
JWT/refresh/OTP y roles/permisos se revalidan contra DB, no confiar en claims de rol.

## 4. Plan de migración normal — requiere aprobación aparte

Inventariar versión real, tablas y ownership sin modificar. Si existe legado
sin alembic_version, **STOP**: diseñar reconciliación validada en una copia
aislada; no hacer stamp head ni aplicar 0001 sobre tablas existentes.
Si ya está gestionada por Alembic: comprobar head esperado, permisos, ventana,
backup verificable y restore probado. Revisar DDL/locks/constraints de cada
revisión pendiente y ejecutar solo el plan autorizado.

F12 no necesita 0012 porque no cambia schema, permisos ni estados.
Head esperado: 0011_customer_extras. Nunca create_all durante startup.

## 5. Arranque y salud

El comando para un entorno configurado es:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Producción requiere proxy TLS, host/bind/procesos elegidos por infraestructura,
sin reload/debug, logs del proxy sin Authorization/cookies/query/body,
soporte CORS y SSE sin buffering. No habilitar acceso público directo a este bind.
Aplicar límites/rate limiting de login/OTP y webhook en el gateway de despliegue;
los límites por challenge no sustituyen protección de tráfico distribuido.

GET /api/v1/health: liveness sin DB. GET /api/v1/health/ready:
SELECT 1 con timeout, 503 seguro si DB no responde. **Readiness de conexión
no prueba head, integridad de schema ni disponibilidad de proveedores.**
Verificar por separado Alembic y cada proveedor. SIGTERM/SIGINT debe cerrar
streams y disponer el pool; los tests cubren dispose incluso ante startup error.

## 6. Smoke y operación

Usar cuentas/órdenes sintéticas autorizadas, nunca datos personales reales.
Verificar ownership, Admin A/B y Kitchen por sucursal, checkout/idempotencia,
LOCAL READY → SERVED, pickup, delivery, cancelación/refund, ledger/historia,
SSE con Last-Event-ID y revocación. No simular online en runtime.
Probar proveedor online/refund/fiscal/push elegido en su sandbox y después
con la validación productiva autorizada. Probar sender OTP real.
Desplegar workers/scheduler externos supervisados usando casos de uso existentes;
no inventar BackgroundTasks ni loops acoplados al servidor HTTP.

Alertar sobre readiness 503, errores 5xx, contención, webhooks rechazados,
refunds pendientes/unknown, fiscal PROCESSING y outbox/claims vencidos.
Definir SLO, retención y escala con mediciones, no asignar metas ficticias.

## 7. Rollback

Preferir volver al binario compatible con el schema vigente y detener nuevas
mutaciones antes de reconciliar. No bajar migraciones con históricos financieros
solo para recuperar la versión anterior; algunos downgrades rechazan datos.
Una restauración es una operación aparte con destino aislado y aprobación;
primero validar el [drill](backup-restore-runbook.md), reconciliar pagos externos
ocurridos después del backup y recién decidir cutover. No reset/drop automatizado.

## 8. Go / no-go

Go solo con CI real verde, PostgreSQL/E2E/carreras reales verdes, performance
revisada, restore probado, proveedores y procesos operativos aprobados.
Cualquier failure/skipped inesperado, schema legado sin plan, proveedor faltante
o pérdida de evidencia financiera implica no-go. Estado F12 actual: RELEASE BLOCKED.

# Fase 12 — hardening y aceptación de release

Fecha: 2026-10-07. **RELEASE BLOCKED**, no “PostgreSQL real validado”.
Rama chore/backend-foundation. HEAD inicial y conservado: 309ade6.
La instrucción directa de misma rama prevalece sobre chore/release-hardening del
documento. Sin branch/worktree nuevo, staging, commit, push, tag o deploy.

## 1. Resumen ejecutivo

Gates CI, contratos, revisión de seguridad, cabeceras ASGI, validación productiva,
pruebas transversales, harness PostgreSQL, metodología de performance y tooling
seguro de recuperación. Dos defectos de comportamiento corregidos con regresiones.
El objetivo crítico PG real permanece abierto por falta de TEST_DATABASE_URL.

## 2. Objetivo F12

Confiabilidad y evidencia de F0–11, no un nuevo módulo de negocio. Cerrar gaps de
aceptación sin ocultar proveedores/infraestructura faltantes.

## 3. Baseline F11

Checkout inicialmente limpio; HEAD 309ade6, feat: complete phase 11 customer extras
and promotions. Resultado histórico F11: 2511 passed, 18 skipped in 477.47s.
Los 18 eran integración PG omitida, no persistencia aprobada.
Python local 3.14.4; requirements directos fijados, sin dependencia nueva F12.

## 4. Alcance

Hardening puntual, matrices, boundaries AST, contract inventory/OpenAPI, CI y
Dependabot, E2E/carreras PG opt-in, performance TEST, scripts/runbooks/docs.
La ausencia de READY → SERVED se corrigió como gap probado del graph existente.

## 5. Fuera de alcance

Frontend/Flutter, nuevas reglas/estados, descuentos/cupones, proveedor ficticio,
pagos reales, deployment, Docker local, reset/stamp/migración normal, refactor masivo.

## 6. RNF evaluados

RNF-01..14. Tabla completa con evidencia y siguiente acción:
[release-readiness](release-readiness.md).

## 7. RNF-01 Usabilidad

PARTIAL / backend only. API guide/contratos; evaluación visual frontend pendiente.

## 8. RNF-02 Compatibilidad

PARTIAL / backend only. HTTP/CORS/SSE; clientes/dispositivos reales pendientes.

## 9. RNF-03 Rendimiento

PARTIAL. Batching/conteos unitarios; fixture PG/EXPLAIN preparado pero no ejecutado.
No cifras de latencia productiva ni SLA inventados.

## 10. RNF-04 Disponibilidad

PARTIAL. Código liveness/readiness/timeout/dispose probado; no hosting/failover/SLO.

## 11. RNF-05 Seguridad

PASS dentro del alcance de pruebas de código. No pentest ni certificación TLS/proxy.

## 12. RNF-06 Autorización

PARTIAL. Matrices HTTP y revocación TEST pasan; validación con filas PG pendiente.

## 13. RNF-07 Privacidad

PASS en contratos de respuesta/errores/log app probados. Retención/legal externos.

## 14. RNF-08 Trazabilidad

PARTIAL. Graph/historia/rollback probados; E2E durable real pendiente.

## 15. RNF-09 Auditoría

PARTIAL. Application append-only/atomicidad; permisos DB y protección operador pendientes.

## 16. RNF-10 Escalabilidad

PARTIAL. Scope multibranch/batches/paginación, no carga distribuida medida.

## 17. RNF-11 Persistencia

BLOCKED. Sin ejecución PostgreSQL TEST; offline/AsyncMock no prueban persistencia.

## 18. RNF-12 Respaldo

PARTIAL. Guards de scripts probados; dump/restore/drill real no ejecutado.

## 19. RNF-13 Notificaciones

PARTIAL. In-app/SSE/outbox probados; push real y worker operativo pendientes.

## 20. RNF-14 Mantenibilidad

PASS local. AST boundaries, Ruff, compileall, pip check y contratos reproducibles.

## 21. PostgreSQL real

No servidor/utilidades PG TEST disponibles en WSL ni TEST_DATABASE_URL.
No se habilitó Docker ni se creó/migró/resetearon bases normales.
La inspección histórica F10 vio legado sin Alembic; no se certifica su estado actual.

## 22. TEST_DATABASE_URL

Solo opt-in explícito. Nombre test, host PostgreSQL, distinto de normal/local
aliases, sin prod/production/staging. DB vacía globalmente antes de DDL.
Ausencia local: skip; con REQUIRE_POSTGRES_INTEGRATION=1: failure.
Nunca se imprime URL/contraseña. No fallback a DATABASE_URL normal.

## 23. Full migration upgrade

Nuevo harness crea schema phase12_test_UUID validado/propio, aplica una única
cadena 0001 → head, exige 60 tablas incluyendo alembic_version y users vacío.
Sin stamp/create_all ni extensiones preparadas por fuera de 0001.
Commit real y lectura tras disponer/recrear pool; limpia solo su schema TEST.
Preparado, **no ejecutado**. No migration 0012 ni cambios en 0001–0011.

## 24. Integration tests

44 casos PG recolectados: 18 previos + 8 transversales F12 + 11 carreras F12
+ 6 E2E + 1 performance. Ejecución explícita local final: **44 skipped,
2826 deselected in 1.30s**, falta TEST_DATABASE_URL. No se contó exit 0 con skips
como PG aprobado.

## 25. E2E flows

Seis casos contra servicios SQL reales: LOCAL/CASH/Kitchen/SERVED/review;
PICKUP/ONLINE/SCHEDULED/release/Kitchen/PICKED_UP; DELIVERY/ONLINE/Kitchen/
assignment/dispatch/DELIVERED; cancelación pagada/refund cash; cancelación previa
al pago online tardío; retraso/notificación/decisión humana sin compensación automática.
Nuevo session verifica histórico, ledger, audit y proyecciones.
Providers online son doubles TEST explícitos, no cobros reales.
Ejecutar tests/e2e sin opt-in produjo 6 skipped in 0.21s; con integración,
los 6 siguen omitidos por URL ausente.

## 26. Concurrency

11 carreras F12 con barrera y pg_backend_pid distintos: cart update, checkout
same/different key, Kitchen, cash, cash refund, pickup release, delivery assignment,
cancel vs Kitchen, cancel vs payment y serve-local. Dos conexiones simultáneas,
timeout/locks acotados, invariantes en tercera lectura. Solo ApplicationError
es resultado competitivo esperado; excepciones SQL/runtime no se silencian.
Carreras previas cubren online/refund, push claim/fencing y roulette/redemption.
Todo PG real **NOT EXECUTED**, sin afirmar que AsyncMock valida locks.

## 27. Financial invariants

Orders total histórico no se recalcula desde catálogo; PAID solo por ledger/resultado
verificado; CASH admin y ONLINE webhook separados. Refund íntegro/único después
de cancelación pagada, cancelación nunca se reactiva por capture tardío.
Dashboard suma pagos/refunds en DB; receipt no cambia dinero; ruleta gratuita.
Unit/API previos pasan; validación financiera real/provider pendiente.

## 28. Branch permission matrix

[Matriz completa](security-review.md): REGISTERED + User activo + ADMIN vigente
+ permiso DB + branch. Kitchen solo preparación/view; Guest/Customer no administra.
Asignación futura/expirada, revocación, branch inactiva y claim falso cubiertos.
Catalog global es deliberadamente global; overrides siguen branch-scoped.

## 29. IDOR

Ownership customer_id/user_id y predicados branch en almacenamiento.
Sin scope: 403; ID extranjero bajo scope propio: 404; ningún body decide owner.
F12 añade reviews/receipts/rewards/notifs/admin campaign/process extranjeros.
Casos PG reales preparados, no ejecutados.

## 30. Auth/JWT

Firma, algoritmo fijo, issuer/audience/exp/purpose; access/refresh/phone tokens no
intercambiables. Claims role/permissions falsos no dan permisos.
Refresh hashed/rotación/revocación/replay persistente probado en suites Auth TEST.

## 31. OTP

HMAC/pepper, expiry, cooldown, intentos y consumo único; debug solo dev/test.
Sender production/staging None: falta proveedor real, no simular éxito.

## 32. Password storage

Argon2id mediante pwdlib, dummy hash login, verify y no hash-as-password;
sin plaintext en DB/response. No inspección de passwords personales.

## 33. Secrets

Settings oculta inputs/repr y exige secretos no débiles/placeholder en staging/prod.
DB_PASSWORD o password DATABASE_URL configurada; debug prohibido.
Plantilla production deliberadamente inválida. No secrets reales en CI/tests/docs.

## 34. CORS

Origins exactos, sin wildcard/credenciales/path/query. Bearer y Last-Event-ID
permitidos, X-Request-ID expuesto. Tests CORS y SSE pasan.

## 35. Privacy

Response schemas recursivos sin hashes/pepper/push tokens/fingerprints/random draw.
Kitchen/SSE sin contacto/dirección/datos fiscales. Inputs sensibles no se reflejan
en 422/500. Auth devuelve token al dueño, no hashes de almacenamiento.

## 36. Logs

Middleware registra método/status/request ID validado, no ruta/query/body/headers.
Errores app registran clase/ubicación, no valores de excepción.
Filtro uvicorn.error sanea exc_info y tracebacks preformateados de lifespan;
regresión explícita no filtra el sentinel secreto y conserva diagnóstico.
HTTPX/Uvicorn/proxy externos pueden loguear URLs: runbook exige --no-access-log
y redacción en proxy. No se certifica configuración externa.

## 37. Audit

Auditoría actor/branch, cambios críticos en transacción; serve-local falla antes
de mutar si audit no disponible y rollback si falla. Retry no duplica.
Recorder runtime append-only comprobado AST; no trigger inmutable audit_logs
nuevo, no protección demostrada contra usuario DB privilegiado.

## 38. Traceability

[Matriz F0–12](release-traceability.md), fuentes de verdad y pendientes sin reescribir
reportes históricos. Pedidos conservan snapshots e historial ordenado.

## 39. Error safety

Envelope previo conservado. 401/403/404/409/422/503 coherentes; 500 seguro con
cabeceras aun cuando ServerErrorMiddleware maneja fuera del middleware de usuario.
Regresión detectó y corrigió una copia de MutableHeaders durante implementación.
Los scripts inicialmente importaban app.main (aplicación global), por lo que
el preflight negativo fallaba antes de su handler. Factory separada en app/factory.py;
main conserva create_app como alias y el entrypoint app. Contrato usa inputs
DEFAULT explícitos para todos los campos, sin depender de .env/deployment env.
Dos regresiones subprocess prueban export/preflight bajo producción inválida,
sin traceback ni sentinel privado.

## 40. OpenAPI

JSON determinista sort_keys/UTF-8; factory sin conexión/lifespan/DDL.
114 paths/155 operaciones; GET / y /health legacy adicional en inventario.
OpenAPI del servidor activo confirmó version0.1.0, 114 paths, 155 operaciones
y presencia de serve-local; no implica éxito contra DB.

## 41. Route inventory

157 operaciones inventariadas por método/path/tag/módulo/política.
140 protegidas Bearer, todas 401 sin credenciales en regresión HTTP.
FastAPI lazy includes aplanados; duplicados se comprueban antes de generar OpenAPI.

## 42. Security contract

Allowlist pública explícita + dos webhooks verified/fail-closed; sin debug/test/fake/
simulate/mark-paid backdoors. Operation IDs únicos, Bearer/SSE/idempotencia,
privacy de responses y roles actuales revisados.

## 43. Performance methodology

Dataset TEST reproducible + capture SQL + perf_counter + EXPLAIN de lecturas reales.
Ver [metodología y límites](performance-report.md). NOT EXECUTED.

## 44. Menu performance

Batches IN con hasta 5 queries repository, independiente del número de productos.
Unit 50 productos validado; PG 250 y planes pendientes.

## 45. Cart performance

GET un statement con snapshots y sin repricing/lock; PG12 líneas pendiente.
Checkout revalida batch; writes por línea no son un N+1 de lectura.

## 46. Order status performance

Lectura histórica scoped sin llamada externa; tests repositorio revisados.
Sin benchmark HTTP/status concurrente ni latencia afirmada.

## 47. Kitchen performance

Proyección JSON en un statement, permiso adicional, sin llamadas/card.
Presupuesto real preparado: <=2 SQL para páginas 10/50.

## 48. Dashboard performance

Agregados financieros SQL, top10, branches/periodos acotados; 1 statement repo.
Sin loading/sum de órdenes en Python; plan y tiempos reales pendientes.

## 49. Query count

Budgets PG preparados: menu<=5 repo; cart=1; kitchen<=2 service;
notifications=2 repo; favorites<=7 service; dashboard=1 repo.
Checkout captura conteo sin gate constante ficticio a inserts por línea.

## 50. EXPLAIN findings

NINGUNO real: PostgreSQL no ejecutado. SQL compilado no se presenta como plan.
No nuevo índice sin evidencia.

## 51. Availability

App activa local puerto8000; infraestructura productiva no desplegada.
Sin SLA/failover/rate limiting distribuido/monitoring real certificado.

## 52. Liveness

GET /health y /docs reales: 200, nosniff y X-Request-ID presentes.
No prueba migración/persistencia ni disponibilidad de dependencias.

## 53. Readiness

GET /api/v1/health/ready real: 503, DB no responde. GET rewards sin bearer: 401.
Probe SELECT 1 timeout y 503 seguro; no valida Alembic ni proveedores.
Startup/shutdown/dispose probados en suite Health, sin auto-DDL.
F12 añade prueba de failure parcial de startup y dispose del pool; shutdown
real observado: Backend stopped; database pool disposed.

## 54. Backup

Helper/wrappers seguros, env explícito, no credenciales argv, custom/0600/exclusive/
SHA/list, output fuera de repo. Tests con bytes sintéticos/subprocess dobles.
No pg_dump real ejecutado.

## 55. Restore drill

NOT EXECUTED. Flag/DB aislada vacía/checksum obligatorios, normal/prod rechazados,
transacción única, sin clean/drop/create/reset. RPO/RTO sin cifras inventadas.
Ver [runbook de recuperación](backup-restore-runbook.md).

## 56. CI

CONFIGURED, NOT YET EXECUTED, PENDING USER PUSH. Jobs quality + PostgreSQL17,
Python3.14, healthcheck, TEST secrets, permisos contents:read, concurrency y timeout.
Actions checkout/setup-python pin SHA estable; persist-credentials false.
No deploy/secret productivo/pytest-xdist; ausencia URL falla en job PG.

## 57. Dependabot

Configurado semanal para pip/GitHub Actions; no ejecutado aún.
Dependencias directas pinned conservadas; no vulnerability scan externo afirmado.

## 58. Production settings

Validación fail-closed y .env.production.example inválida; preflight --production
usa entorno explícito sin .env. Proveedores no se habilitan por una variable falsa.
No infraestructura/TLS/secret manager desplegados.

## 59. Migration runbook

Single head, backup/drill/ventana y revisar estado normal antes de upgrade.
STOP con legado sin Alembic; sin stamp automático. [Runbook](release-runbook.md).

## 60. Rollback strategy

Preferir binario compatible/schema vigente; proteger datos/históricos, no downgrade
financiero ciego. Restore aislado + reconciliación externa + aprobación humana.

## 61. External payment provider

UnconfiguredOnlinePaymentGateway; online503, adaptador/verificación real pendiente.

## 62. External refund provider

UnconfiguredOnlineRefundGateway; obligación sí, devolución online real pendiente.

## 63. Push provider

Registry productivo vacío; no push real ni device registration soportada sin provider.

## 64. Push worker

Dispatch/claim/fencing/recovery código probado; no servicio desplegado/supervisado.

## 65. Fiscal provider

UnconfiguredFiscalDocumentGateway; sin emisión legal/SUNAT/PDF/XML/CDR real.
No se cambia estado fiscal por petición cliente no verificada.

## 66. Pickup scheduler

release_due existente; sin scheduler real. No loop/BackgroundTasks nuevo en HTTP.

## 67. Production blockers

PostgreSQL/CI real, schema normal/plan, restore drill, payment/refund/push/fiscal/
OTP providers, worker/scheduler, TLS/DB privileges/monitoring y política de recuperación.

## 68. Release candidate decision

RELEASE BLOCKED. No v1/RC/tag ni “100% production ready”.

## 69. Ruff

ruff check . → All checks passed!
ruff format --check . → 561 files already formatted.
Sin warning filters laxos/xfail/noqa blanket; E402 solo bootstrap de scripts.

## 70. Pytest

Resultados finales del código entregado, sin failures:

| Comando | Resultado exacto |
| --- | --- |
| pytest -m "not integration" -q --tb=short | 2826 passed, 44 deselected in 679.81s (0:11:19) |
| pytest -q --tb=short | 2826 passed, 44 skipped in 672.77s (0:11:12) |
| pytest tests/quality -q | 266 passed in 27.46s |
| pytest tests/security -q | 37 passed in 52.32s |
| Quality/security/health/errors/CORS, bloque actualizado | 326 passed in 83.80s |
| Catalog repository | 19 passed in 0.16s |
| Cierre LOCAL, regresión individual | 11 passed in 3.36s |

Primera regresión non-integration: 2792 passed, 43 deselected in 771.53s,
antes de últimas regresiones. Bloque inicial quality/security/local:
310 passed in 73.11s. El bloque quality/security también pasó con TEST env de CI:
301 passed in65.54s, antes de las dos regresiones de scripts offline finales.
Primer full run: **2 failed, 2820 passed, 44 skipped in 992.62s**.
Ambos failures eran tests F12 de issuer/audience que reutilizaban NOW de import
del helper Auth; al durar >15min, expiraban antes de la comprobación específica.
Se genera el token en utc_now() al ejecutar cada test, sin cambiar TTL, bypass
de firma/expiry ni manejo de errores del backend. Regresión auth/log/startup:
9 passed in2.92s. Las corridas parciales previas se interrumpieron al ajustar
las pruebas; no se presentan como completas ni aprobadas.

## 71. Integration Pytest

pytest -m integration -q → 44 skipped, 2826 deselected in 1.30s, URL ausente.
E2E + release PG seleccionados → 14 skipped in0.22s.
Performance → 1 skipped,2869 deselected in1.28s.
Esto NO cumple el gate de PG real.

## 72. Alembic

heads: 0011_customer_extras único. history: once revisiones lineales 0001..0011.
No se aplicó upgrade a DB normal. Head offline no certifica parser/trigger real.

## 73. OpenAPI check

PASS OpenAPI + route inventory check. Artefactos incluidos y comparados byte a byte.
Offline release preflight → PASS; NOT provider/deployment approval.
YAML workflow/Dependabot parseado y gates/service assertions → PASS local.
Esto no sustituye ejecución de GitHub Actions.

## 74. pip check

No broken requirements found. Verifica consistencia, no ausencia de CVEs.

## 75. compileall

python -m compileall -q app tests scripts: exit0, sin salida/error.

## 76. Git status

Misma rama/HEAD, 18 tracked modificados y 48 archivos nuevos, índice sin staging.
Sin add/commit/push/tag. git diff --check pasa; --stat tracked no incluye nuevos.

## 77. Files created

.env.production.example; .github/{workflows/ci.yml,dependabot.yml};
app/factory.py, app/presentation/hardening.py; scripts/{contracts,export_openapi,release_check,
postgres_backup}.py y wrappers backup_postgres.sh/restore_postgres.sh.
Docs: phase12-report, release-readiness, release-runbook, security-review,
security-checklist, performance-report, backup-restore-runbook, api-guide,
release-traceability, api-inventory y openapi.json.
Tests: quality/security/e2e/performance paquetes; phase12_support;
integration/test_phase12_release_postgresql y concurrency_postgresql;
orders/test_phase12_local. Incluye __init__.py y conftest TEST necesarios.

## 78. Files modified

README, .gitignore, pyproject; app/main, presentation/errors, Settings/logging;
Catalog authorization; Orders ports/service/repository/dependencies/router;
tests Orders fakes/API, Catalog repository, Phase1 foundation y guard PG.
No requirements, versión ni migrations históricas modificados.

## 79. Bugs discovered

Gap LOCAL completion; catálogo global permitía asignación futura; configuración
productiva permitía secretos repetidos/variantes placeholder; hardening HTTP faltante.
Durante implementación: header500 se copiaba y SHA vacío no tenía guard seguro.
Uvicorn podía reimprimir valores; nuevo test JWT heredaba reloj import-time;
test de plantilla dependía de APP_ENV externo (ajustado para CI TEST env).
Preflight offline tenía un import-time side effect; factory separada y
regresión subprocess, sin modificar el contrato create_app ni las rutas existentes.

## 80. Bugs fixed

Regresión catálogo falló antes del fix assigned_at<=now(), después 19 repos pasan.
LOCAL11 regresiones (permisos/body/estado/branch/retry/audit rollback) pasan.
Configuration/backups/header/security regressions pasan. Hallazgos y severidad
incluyen redacción Uvicorn y pruebas de reloj/plantilla sin debilitar producción.
en security-review; PostgreSQL real sigue pendiente, no se “corrige” con mocks.

## 81. Known risks

Gate PG/CI abierto, legacy normal, operadores DB privilegiados, traffic abuse
distribuido, ausencia de proveedores/procesos/drill, performance sin planes reales.
El API readiness solo conecta; no declarar schema/producto completo por un 200.
Los reportes anteriores son históricos, no resultados de esta revisión.

## 82. Recommendations

Revisión del diff → TEST PG/CI real sin skips → resolver failures → performance/
drill con evidencia → seleccionar/integrar proveedores y operar workers/scheduler
→ preflight/plan normal aprobado → reevaluar release. No avanzar otra fase.

## Anexo — inventario exacto del diff

Rutas relativas al checkout WSL /home/heizen27/proyectos/restaurante-backend.

### Nuevos (48)

```text
.env.production.example
.github/dependabot.yml
.github/workflows/ci.yml
app/factory.py
app/presentation/hardening.py
docs/api-guide.md
docs/api-inventory.md
docs/backup-restore-runbook.md
docs/openapi.json
docs/performance-report.md
docs/phase12-report.md
docs/release-readiness.md
docs/release-runbook.md
docs/release-traceability.md
docs/security-checklist.md
docs/security-review.md
scripts/__init__.py
scripts/backup_postgres.sh
scripts/contracts.py
scripts/export_openapi.py
scripts/postgres_backup.py
scripts/release_check.py
scripts/restore_postgres.sh
tests/e2e/__init__.py
tests/e2e/test_order_flows.py
tests/integration/test_phase12_concurrency_postgresql.py
tests/integration/test_phase12_release_postgresql.py
tests/modules/orders/test_phase12_local.py
tests/performance/__init__.py
tests/performance/test_postgresql_read_models.py
tests/phase12_support.py
tests/quality/__init__.py
tests/quality/test_architecture_boundaries.py
tests/quality/test_audit_contract.py
tests/quality/test_backup_safety.py
tests/quality/test_offline_scripts.py
tests/quality/test_openapi_contract.py
tests/quality/test_release_configuration.py
tests/quality/test_route_inventory.py
tests/quality/test_startup_cleanup.py
tests/security/__init__.py
tests/security/conftest.py
tests/security/test_auth_hardening.py
tests/security/test_idor_matrix.py
tests/security/test_permission_matrix.py
tests/security/test_privacy_contracts.py
tests/security/test_sensitive_logging.py
tests/security/test_server_logging.py
```

### Modificados (18)

```text
.gitignore
README.md
app/main.py
app/modules/catalog/infrastructure/authorization.py
app/modules/orders/application/ports.py
app/modules/orders/application/services.py
app/modules/orders/infrastructure/persistence/repositories.py
app/modules/orders/presentation/dependencies.py
app/modules/orders/presentation/router.py
app/presentation/errors.py
app/shared/infrastructure/config/settings.py
app/shared/infrastructure/logging/config.py
pyproject.toml
tests/integration/test_phase1_postgresql.py
tests/modules/catalog/test_repositories.py
tests/modules/orders/fakes.py
tests/modules/orders/test_api.py
tests/test_phase1_foundation.py
```

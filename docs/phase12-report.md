# Fase 12 — hardening y aceptación de release

Fecha: 2026-10-07. **POSTGRESQL REAL: VALIDATED. RELEASE BLOCKED** por pendientes externos.
Rama chore/backend-foundation. Baseline de esta validación: b2ad4c5;
309ade6 fue el HEAD inicial de la implementación F12 anterior.
La instrucción directa de misma rama prevalece sobre chore/release-hardening del
documento. Sin branch/worktree nuevo, staging, commit, push, tag o deploy.

## 1. Resumen ejecutivo

Gates CI, contratos, revisión de seguridad, cabeceras ASGI, validación productiva,
pruebas transversales, harness PostgreSQL, metodología de performance y tooling
seguro de recuperación. Dos defectos de comportamiento corregidos con regresiones.
El objetivo crítico PG real está cerrado: 45 pruebas de integración aprobadas,
sin failures/skips, en una base TEST del contenedor Docker ya existente.
No certifica proveedores, despliegue ni la migración de la base normal.

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

PARTIAL. Budgets y EXPLAIN PG reales aprobados; falta carga productiva representativa.
No cifras de latencia productiva ni SLA inventados.

## 10. RNF-04 Disponibilidad

PARTIAL. Código liveness/readiness/timeout/dispose probado; no hosting/failover/SLO.

## 11. RNF-05 Seguridad

PASS dentro del alcance de pruebas de código. No pentest ni certificación TLS/proxy.

## 12. RNF-06 Autorización

PASS, alcance automatizado. Matrices HTTP, IDOR y revocación con filas PG reales pasan.

## 13. RNF-07 Privacidad

PASS en contratos de respuesta/errores/log app probados. Retención/legal externos.

## 14. RNF-08 Trazabilidad

PASS, alcance automatizado. Graph/historia/rollback y E2E durable real aprobados.

## 15. RNF-09 Auditoría

PARTIAL. Application append-only/atomicidad; permisos DB y protección operador pendientes.

## 16. RNF-10 Escalabilidad

PARTIAL. Scope multibranch/batches/paginación, no carga distribuida medida.

## 17. RNF-11 Persistencia

PASS, PostgreSQL TEST real. Migraciones, constraints, triggers, persistencia y locks
aprobados; no certifica el schema normal ni un despliegue productivo.

## 18. RNF-12 Respaldo

PARTIAL. Guards de scripts probados; dump/restore/drill real no ejecutado.

## 19. RNF-13 Notificaciones

PARTIAL. In-app/SSE/outbox probados; push real y worker operativo pendientes.

## 20. RNF-14 Mantenibilidad

PASS local. AST boundaries, Ruff, compileall, pip check y contratos reproducibles.

## 21. PostgreSQL real

Contenedor existente `postgres`, ID `9aa3c65192ce`, imagen `postgres`, puerto5432;
servidor PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2). No se instaló servidor ni
se cambió contenedor/imagen/volumen/puerto/compose/Dockerfile.
Settings identifica `localhost:5432`, usuario `postgres`, base normal
`restaurante_app`. Consulta de pg_database confirmó su existencia y ausencia de
`restaurant_test`; se creó solo `restaurant_test` con docker exec/psql.
Antes de los tests tenía 0 tablas y 0 relaciones de usuario. La conexión Python
leyó únicamente current_database()/version() y confirmó `restaurant_test`.
No se conectó a la base normal para DDL/cleanup ni se certifica su schema actual.
Verificación final: ambas bases siguen existiendo; restaurant_test conserva
0 tablas/0 relaciones de usuario y 0 schemas phase*_test_ tras el cleanup propio.
No se eliminó restaurant_test. .env conserva el SHA256 inicial (valor no publicado).
No DROP/ALTER/cleanup, upgrade/stamp ni restore contra restaurante_app.

## 22. TEST_DATABASE_URL

Solo opt-in explícito. Nombre test, host PostgreSQL, distinto de normal/local
aliases, sin prod/production/staging. DB vacía globalmente antes de DDL.
Ausencia local: skip; con REQUIRE_POSTGRES_INTEGRATION=1: failure, incluso sin -m.
Ese flag es opt-in explícito también para pytest completo; los guards de nombre,
host/base normal y emptiness siguen vigentes, con cinco regresiones adicionales.
Para esta validación se deriva en memoria desde database_connection_url,
conservando host/puerto/usuario/password y cambiando solo la base a restaurant_test.
URL y flag viven exclusivamente en los procesos de pruebas; .env no modificado.
Nunca se imprime URL/contraseña. No fallback a DATABASE_URL normal.

## 23. Full migration upgrade

Nuevo harness crea schema phase12_test_UUID validado/propio, aplica una única
cadena 0001 → head, exige 60 tablas incluyendo alembic_version y users vacío.
Sin stamp/create_all ni extensiones preparadas por fuera de 0001.
Commit real y lectura tras disponer/recrear pool; limpia solo su schema TEST.
**Ejecutado y aprobado**. No migration 0012 ni cambios en 0001–0011.

## 24. Integration tests

45 casos PG: 18 previos + 9 transversales F12 + 11 carreras F12 + 6 E2E + 1 performance.
Ejecución final explícita: **45 passed, 2831 deselected in 61.47s**, 0 failed/0 skipped.
Incluye FK/CHECK/UNIQUE/índices únicos parciales, JSONB/TIMESTAMPTZ, triggers
PL/pgSQL, FOR UPDATE/SKIP LOCKED, commit/rollback, idempotencia y conexiones
independientes. Se añadió prueba real del advisory lock OTP existente: espera
observada en pg_locks, distinto PID, otra identidad no bloqueada y liberación por rollback.

## 25. E2E flows

Seis casos contra servicios SQL reales: LOCAL/CASH/Kitchen/SERVED/review;
PICKUP/ONLINE/SCHEDULED/release/Kitchen/PICKED_UP; DELIVERY/ONLINE/Kitchen/
assignment/dispatch/DELIVERED; cancelación pagada/refund cash; cancelación previa
al pago online tardío; retraso/notificación/decisión humana sin compensación automática.
Nuevo session verifica histórico, ledger, audit y proyecciones.
Providers online son doubles TEST explícitos, no cobros reales.
Ejecución aislada con opt-in explícito: **6 passed in 7.70s**, 0 failed/0 skipped.

## 26. Concurrency

11 carreras F12 con barrera y pg_backend_pid distintos: cart update, checkout
same/different key, Kitchen, cash, cash refund, pickup release, delivery assignment,
cancel vs Kitchen, cancel vs payment y serve-local. Dos conexiones simultáneas,
timeout/locks acotados, invariantes en tercera lectura. Solo ApplicationError
es resultado competitivo esperado; excepciones SQL/runtime no se silencian.
Carreras previas cubren online/refund, push claim/fencing y roulette/redemption.
F12 concurrency: **11 passed in 13.05s**, 0 failed/0 skipped; las carreras
previas también pasan dentro de los 45 casos reales, no mediante AsyncMock.

## 27. Financial invariants

Orders total histórico no se recalcula desde catálogo; PAID solo por ledger/resultado
verificado; CASH admin y ONLINE webhook separados. Refund íntegro/único después
de cancelación pagada, cancelación nunca se reactiva por capture tardío.
Dashboard suma pagos/refunds en DB; receipt no cambia dinero; ruleta gratuita.
Invariantes financieras SQL reales aprobadas por integración/E2E; proveedores
externos reales siguen pendientes, sin cobros/reembolsos externos en esta validación.

## 28. Branch permission matrix

[Matriz completa](security-review.md): REGISTERED + User activo + ADMIN vigente
+ permiso DB + branch. Kitchen solo preparación/view; Guest/Customer no administra.
Asignación futura/expirada, revocación, branch inactiva y claim falso cubiertos.
Catalog global es deliberadamente global; overrides siguen branch-scoped.

## 29. IDOR

Ownership customer_id/user_id y predicados branch en almacenamiento.
Sin scope: 403; ID extranjero bajo scope propio: 404; ningún body decide owner.
F12 añade reviews/receipts/rewards/notifs/admin campaign/process extranjeros.
Casos PG reales ejecutados y aprobados; ID customer/branch ajeno no filtra filas.

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
Ver [mediciones y límites](performance-report.md). EXECUTED / PASS local, sin SLA.

## 44. Menu performance

Batches IN con hasta 5 queries repository, independiente del número de productos.
PG 250 productos: 4 SQL repo, 44.871ms en la ejecución registrada.
Sin adicionales en este dataset; no se extrapola a todos los menús productivos.

## 45. Cart performance

GET un statement con snapshots y sin repricing/lock; PG12 líneas: 1 SQL, 6.407ms.
Checkout revalida batch; writes por línea no son un N+1 de lectura.

## 46. Order status performance

Lectura histórica scoped sin llamada externa; tests repositorio revisados.
Sin benchmark HTTP/status concurrente ni latencia afirmada.

## 47. Kitchen performance

Proyección JSON en un statement, permiso adicional, sin llamadas/card.
Páginas 10/50 reales: 2 SQL cada una, 14.265/13.080ms en la ejecución registrada.

## 48. Dashboard performance

Agregados financieros SQL, top10, branches/periodos acotados; 1 statement repo.
Sin loading/sum de órdenes en Python; 1 SQL, 6.802ms; EXPLAIN ejecución0.734ms.
50 órdenes pagadas/PEN2000.00 verificados en el dataset sintético.

## 49. Query count

SQL reales: menu4 repo; cart1; kitchen2 service; notifications2 repo;
favorites6 service (páginas10/50); dashboard1 repo. Budgets aprobados.
Checkout12: 23 SQL/47.591ms, sin gate constante ficticio a inserts por línea.

## 50. EXPLAIN findings

EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) real sobre las lecturas TEST capturadas.
Planes con Index/Bitmap scans, joins, aggregates y sorts; 0 bloques leídos de
disco y 0 temporales en esos planes. Menú/favoritos planean su última lectura
de adicionales vacíos, no la totalidad del flujo. Límites y datos completos en
performance-report. No se añadió índice ni se inventó p95/SLA.

## 51. Availability

App activa local puerto8000; infraestructura productiva no desplegada.
Sin SLA/failover/rate limiting distribuido/monitoring real certificado.

## 52. Liveness

GET /health y /docs reales: 200, nosniff y X-Request-ID presentes.
No prueba migración/persistencia ni disponibilidad de dependencias.

## 53. Readiness

Observación histórica al implementar F12: /api/v1/health/ready503 sin DB y rewards401.
Esta revisión valida la conexión TEST, no usa readiness para certificar la DB normal.
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

CI real, schema normal/plan, restore drill, payment/refund/push/fiscal/
OTP providers, worker/scheduler, TLS/DB privileges/monitoring y política de recuperación.

## 68. Release candidate decision

RELEASE BLOCKED. No v1/RC/tag ni “100% production ready”.

## 69. Ruff

ruff check . → All checks passed!
ruff format --check . → 561 files already formatted.
Sin warning filters laxos/xfail/noqa blanket; E402 solo bootstrap de scripts.

## 70. Pytest

Resultados históricos de la implementación F12 en 309ade6 (sin PostgreSQL):

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

Validación actual sobre b2ad4c5 más el diff local, REQUIRE_POSTGRES_INTEGRATION=1:

| Suite | Resultado exacto |
| --- | --- |
| Phase12 release PostgreSQL | 9 passed in 9.70s |
| Phase12 concurrency PostgreSQL | 11 passed in 13.05s |
| pytest -m integration -q | 45 passed, 2831 deselected in 61.47s |
| E2E PostgreSQL explícito | 6 passed in 7.70s |
| pytest -m performance -s -q | 1 passed, 2874 deselected in 8.73s |
| Guards release/configuration | 46 passed in 0.14s |
| pytest -m "not integration" -q, repetición final | 2831 passed, 45 deselected in 593.78s |
| pytest -q, repetición final con PG obligatorio | 2876 passed in 658.45s |

Todas esas suites tienen 0 failed/0 skipped. Los deselected corresponden al
selector de la suite, no a pruebas PostgreSQL omitidas.
Primera corrida real: 8 failed por fixture price_delta ausente; tras corregir,
8 passed. Primera integración completa: 1 failed/38 passed (stop-first) por
fixture pickup fuera de CHECK temporal; regresión fases6–9: 5 passed in6.98s.
Después 44 passed in69.59s; se añadió la regresión advisory y pasó la corrida
final de45. Sin xfail, skip añadido, assertion eliminada ni cambio de migraciones.

Regresión general inicial: 3 failed, 2828 passed, 44 deselected in581.45s.
Dos fueron TOKEN_EXPIRED en JWT de fixtures y uno HTTP500 en catálogo;
los tres pasan aislados (3 passed in2.16s), y cancellation API:93 passed in69.00s.
Clasificación provisional F (incidencia de ejecución): expiración inesperada en
fixtures recién creados y HTTP500 durante una corrida a la que se envió SIGINT
diagnóstico. La causa raíz de esos eventos no quedó confirmada; no se declara
un bug de producción corregido por un retry ni se ocultaron los failures.
Sin modificar esos tests, TTL/validación JWT, reloj del sistema ni assertions,
la repetición non-integration y la completa pasaron, **0 failed/0 skipped/0 xfailed**.
Diagnóstico observacional: non-integration wall593.755s/monotonic593.781s;
completo wall658.420s/monotonic658.448s, sin discontinuidades >1s detectadas.
Los 45 casos PG se ejecutan también en pytest completo mediante el flag explícito.
Los skips antiguos por falta de URL son históricos; no hay skips en la validación final.

## 72. Alembic

heads: 0011_customer_extras único. history: once revisiones lineales 0001..0011.
No se aplicó upgrade a DB normal. La cadena se ejecutó realmente en TEST y los
tests verificaron parser, constraints y triggers además del head offline.

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

Baseline actual b2ad4c5, checkout limpio al comenzar, misma rama/HEAD.
Este cierre deja 10 archivos tracked modificados (6 tests/harness y 4 docs),
sin archivos nuevos ni staging; no app/runtime, migrations ni CI modificados.
Sin add/commit/push/tag. El inventario final inferior del diff 309ade6 es histórico.

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
en security-review. PostgreSQL real ahora aprobado; no se sustituyó por mocks.
En este cierre: fixture price_delta explícito0 (B, test), horario pickup consistente
(B, test), guard REQUIRE también para suite completa (E, configuración/harness),
y regresión advisory real. Sin bug de runtime/migración PostgreSQL identificado.

## 81. Known risks

Gate CI abierto, legacy normal, operadores DB privilegiados, traffic abuse
distribuido, ausencia de proveedores/procesos/drill, performance sin carga productiva.
El API readiness solo conecta; no declarar schema/producto completo por un 200.
Los reportes anteriores son históricos, no resultados de esta revisión.

## 82. Recommendations

Revisión del diff → CI real → drill autorizado con evidencia → seleccionar/
integrar proveedores y operar workers/scheduler
→ preflight/plan normal aprobado → reevaluar release. No avanzar otra fase.

## Anexo histórico — inventario del diff F12 inicial (309ade6)

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

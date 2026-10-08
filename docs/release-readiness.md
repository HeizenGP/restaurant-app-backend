# Fase 12 — decisión de release

Fecha de revisión: 2026-10-07. Rama real: chore/backend-foundation.
Baseline de esta validación: b2ad4c5. HEAD inicial F12: 309ade6.
Versión: 0.1.0, sin tag nuevo.

**RELEASE BLOCKED. POSTGRESQL REAL: VALIDATED.**
45 pruebas PG aprobadas, 0 failed/0 skipped, en `restaurant_test` del contenedor
existente `postgres`/puerto5432/PostgreSQL18.6. No equivale a aprobación productiva.
La base normal `restaurante_app` no fue objetivo de DDL, limpieza ni migraciones.
TEST_DATABASE_URL/REQUIRE_POSTGRES_INTEGRATION solo en procesos; .env intacto.
Regresión final: **2831 passed** sin integración y **2876 passed** en pytest
completo, 0 failed/0 skipped. restaurant_test queda retenida y vacía tras los tests.
CI: **CONFIGURED, NOT YET EXECUTED; EXECUTION PENDING USER PUSH**.

## Puertas de aceptación

| Gate | Estado | Evidencia / siguiente acción |
| --- | --- | --- |
| Calidad, límites arquitectónicos y contratos | PASS local | [Resultados](phase12-report.md), tests/quality |
| Autenticación, permisos, IDOR y privacidad | PASS local, alcance de tests | Matrices API más permisos/ownership/revocación de filas PG reales |
| PostgreSQL, cadena completa, E2E y carreras | PASS / VALIDATED local | 45 passed; 9 release, 11 carreras F12, 6 E2E; cadena0001–0011, advisory OTP y skip-locked reales |
| Rendimiento real / EXPLAIN | PASS local / PARTIAL productivo | 1 passed; SQL counts, tiempos y buffers reales en performance-report; sin SLA demostrado |
| Backup / restore | PARTIAL | Herramientas y guards preparados/probados; drill real no ejecutado |
| Operación productiva | BLOCKED | Proveedores, scheduler/worker, TLS, monitoreo y credenciales por configurar |

## RNF, sin confundir código con infraestructura

PASS significa evidencia automatizada dentro del alcance señalado; PARTIAL
indica evidencia incompleta; BLOCKED exige una condición externa.

| RNF | Estado | Evidencia, límite y acción pendiente |
| --- | --- | --- |
| RNF-01 Usabilidad | PARTIAL / backend only | API guide/OpenAPI; validación visual Flutter/frontend pendiente |
| RNF-02 Compatibilidad | PARTIAL / backend only | Contratos HTTP/SSE/CORS; clientes móviles/navegadores reales pendientes |
| RNF-03 Rendimiento | PARTIAL | Budgets PG/EXPLAIN reales aprobados; falta carga HTTP/distribuida representativa |
| RNF-04 Disponibilidad | PARTIAL | Liveness/readiness, timeout y dispose probados; hosting, alertas, failover y SLO pendientes |
| RNF-05 Seguridad | PASS, código probado | Argon2/JWT/refresh/OTP/configuración/cabeceras; no pentest ni certificación de despliegue |
| RNF-06 Autorización | PASS, tests automatizados | Matriz HTTP/permisos/IDOR y revocación real de staff/branch/user/asignación/permiso |
| RNF-07 Privacidad | PASS, contratos probados | Proyecciones y errores sin secretos; no certifica cumplimiento legal/retención |
| RNF-08 Trazabilidad | PASS, tests automatizados | Historia, snapshots y E2E persistente real; rollback de historia/audit/eventos probado |
| RNF-09 Auditoría | PARTIAL | Atomicidad/append-only de aplicación probados; privilegios DB e inmutabilidad ante operador pendientes |
| RNF-10 Escalabilidad | PARTIAL | Scope multibranch, páginas/batches acotados; no carga distribuida ni benchmark real |
| RNF-11 Persistencia | PASS, PostgreSQL TEST | 45 casos PG reales aprobados; no certifica migración normal ni operadores productivos |
| RNF-12 Respaldo | PARTIAL | Scripts/runbook/guards; falta backup-restauración real y acordar RPO/RTO |
| RNF-13 Notificaciones | PARTIAL | In-app/SSE, reconexión/revocación y outbox probados; push real/worker pendientes |
| RNF-14 Mantenibilidad | PASS, alcance local | AST Domain/Application/Presentation, Ruff, compileall, pip check y CI preparado |

## Bloqueadores externos

| Dependencia | Estado real | Efecto |
| --- | --- | --- |
| PaymentGateway | UnconfiguredOnlinePaymentGateway | Online devuelve 503; PICKUP/DELIVERY reales no son operables |
| RefundGateway | UnconfiguredOnlineRefundGateway | Obligación persistida, ejecución online real pendiente |
| PushGateway | Registro productivo vacío | No envío push real; in-app/SSE no dependen de él |
| FiscalDocumentGateway | UnconfiguredFiscalDocumentGateway | Sin emisión legal, SUNAT, CDR/XML/PDF ni validación fiscal real |
| OTP sender | None en staging/production | Debe integrarse un envío real; OTP TEST no habilita onboarding productivo |
| Push worker | Caso de uso de dispatch, sin servicio desplegado | Falta proceso, cadencia, supervisión y recuperación de claims |
| Pickup scheduler | release_due disponible, sin scheduler desplegado | Falta liberación automática supervisada |
| PostgreSQL normal | No migrado por F12 | Observación histórica F10: legado sin Alembic; estado actual no certificado |
| Restore drill | No ejecutado; no autorizado en esta validación | No se ha demostrado recuperación ni RPO/RTO |

No hay nuevo proveedor falso en runtime, ni ruta debug para cobrar/reembolsar.
Los doubles están exclusivamente en tests y no constituyen evidencia externa.

## Recomendación

Revisar los cambios y ejecutar CI tras el commit/push **del usuario**; mantiene
su servicio PostgreSQL17 aislado, sin cambios innecesarios. La evidencia local
corresponde a PostgreSQL18.6 y no sustituye una corrida de GitHub Actions.
Después ejecutar el [runbook](release-runbook.md), obtener evidencia de los
proveedores y del restore drill. Solo entonces reevaluar un release candidate.
No afirmar “100% production ready”.

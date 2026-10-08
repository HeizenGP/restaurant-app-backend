# Fase 12 — decisión de release

Fecha de revisión: 2026-10-07. Rama real: chore/backend-foundation.
HEAD inicial: 309ade6. Versión: 0.1.0, sin tag nuevo.

**RELEASE BLOCKED.** El hardening y los gates están implementados, pero no se
ha ejecutado el suite contra PostgreSQL real. No equivale a aprobación productiva.
CI: **CONFIGURED, NOT YET EXECUTED; EXECUTION PENDING USER PUSH**.

## Puertas de aceptación

| Gate | Estado | Evidencia / siguiente acción |
| --- | --- | --- |
| Calidad, límites arquitectónicos y contratos | PASS local | [Resultados](phase12-report.md), tests/quality |
| Autenticación, permisos, IDOR y privacidad | PASS local, alcance de tests | tests/security y suites de cada slice; persistencia real pendiente |
| PostgreSQL, cadena completa, E2E y carreras | BLOCKED | TEST_DATABASE_URL no configurada; CI tiene PostgreSQL 17 aislado |
| Rendimiento real / EXPLAIN | NOT EXECUTED | Fixture y presupuestos preparados; no SLA demostrado |
| Backup / restore | PARTIAL | Herramientas y guards preparados/probados; drill real no ejecutado |
| Operación productiva | BLOCKED | Proveedores, scheduler/worker, TLS, monitoreo y credenciales por configurar |

## RNF, sin confundir código con infraestructura

PASS significa evidencia automatizada dentro del alcance señalado; PARTIAL
indica evidencia incompleta; BLOCKED exige una condición externa.

| RNF | Estado | Evidencia, límite y acción pendiente |
| --- | --- | --- |
| RNF-01 Usabilidad | PARTIAL / backend only | API guide/OpenAPI; validación visual Flutter/frontend pendiente |
| RNF-02 Compatibilidad | PARTIAL / backend only | Contratos HTTP/SSE/CORS; clientes móviles/navegadores reales pendientes |
| RNF-03 Rendimiento | PARTIAL | Batching y conteos unitarios; mediciones PostgreSQL preparadas, no ejecutadas |
| RNF-04 Disponibilidad | PARTIAL | Liveness/readiness, timeout y dispose probados; hosting, alertas, failover y SLO pendientes |
| RNF-05 Seguridad | PASS, código probado | Argon2/JWT/refresh/OTP/configuración/cabeceras; no pentest ni certificación de despliegue |
| RNF-06 Autorización | PARTIAL | Matriz HTTP/permisos/IDOR pasa; revalidación con filas reales pendiente |
| RNF-07 Privacidad | PASS, contratos probados | Proyecciones y errores sin secretos; no certifica cumplimiento legal/retención |
| RNF-08 Trazabilidad | PARTIAL | Graph/historia y rollback unitarios; E2E histórico real pendiente |
| RNF-09 Auditoría | PARTIAL | Atomicidad/append-only de aplicación probados; privilegios DB e inmutabilidad ante operador pendientes |
| RNF-10 Escalabilidad | PARTIAL | Scope multibranch, páginas/batches acotados; no carga distribuida ni benchmark real |
| RNF-11 Persistencia | BLOCKED | Sin PostgreSQL TEST; metadata/DDL offline no equivalen a persistencia validada |
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
| Restore drill | No ejecutado; sin utilidades PostgreSQL locales | No se ha demostrado recuperación ni RPO/RTO |

No hay nuevo proveedor falso en runtime, ni ruta debug para cobrar/reembolsar.
Los doubles están exclusivamente en tests y no constituyen evidencia externa.

## Recomendación

Revisar los cambios, configurar TEST_DATABASE_URL dedicada/vacía o ejecutar CI
tras el commit/push **del usuario**, corregir cualquier failure y conservar sus logs.
Después ejecutar el [runbook](release-runbook.md), obtener evidencia de los
proveedores y del restore drill. Solo entonces reevaluar un release candidate.
No afirmar “100% production ready”.

# Trazabilidad Fases 0–12

Estado del código al revisar HEAD 309ade6 más cambios locales F12. “Implementado”
no significa proveedor productivo, PostgreSQL ejecutado ni aceptación frontend.
Los reportes previos conservan sus resultados históricos; no se reescriben como
si hubieran ejecutado pruebas que estaban omitidas.

| Fase | Responsabilidad / fuente de verdad | Evidencia | Estado / pendiente |
| --- | --- | --- | --- |
| 0 | App factory, lifespan, config, health, arquitectura | README; tests/modules/health/test_health.py; tests/test_settings.py, test_cors.py, test_errors.py | Código base probado; infraestructura pendiente |
| 1 | Auth, User/Customer, OTP/JWT/refresh, branches/addresses/staff | phase1-report; tests/modules/auth, customers, branches; test_phase1_postgresql | Código probado; sender OTP real y PG pendientes |
| 2 | Catalog global y overrides branch; precios/disponibilidad | phase2-report; tests/modules/catalog; test_phase2_postgresql | Batching/scope probado; PG pendiente |
| 3 | Cart activo y snapshots servidor | phase3-report; tests/modules/cart; test_phase3_postgresql | Atomicidad unit/API; PG pendiente |
| 4 | Checkout/idempotencia/históricos LOCAL/PICKUP/DELIVERY | phase4-report; tests/modules/orders; test_phase4_postgresql | Código probado; F12 corrige cierre LOCAL faltante |
| 5 | Kitchen WAITING → PREPARING → READY/READY_FOR_PICKUP | phase5-report; tests/modules/kitchen; test_phase5_postgresql | Solo preparación, no pagos/cancelaciones/completions |
| 6 | Payments ledger, CASH y port online verificado | phase6-report; tests/modules/payments; test_phase6_postgresql | CASH código; provider online real pendiente |
| 7 | Pickup release/completion, delivery assignment/completion/delay | phase7-report; tests/modules/fulfillment; test_phase7_postgresql | Código probado; scheduler real pendiente |
| 8 | Cancel requests/decision, full-refund obligation, late-payment | phase8-report; tests/modules/cancellations/payments; test_phase8_postgresql | Invariantes probados; refund online provider pendiente |
| 9 | In-app/outbox/devices/SSE y scopes | phase9-report; tests/modules/notifications; test_phase9_postgresql | In-app/SSE código; push real/worker pendiente |
| 10 | Customers/staff/branches/config admin y dashboard read-only | phase10-report; tests/modules/admin; test_phase10_postgresql | DB-derived permissions; no SUPERADMIN ni writes al ledger |
| 11 | Favorites/reviews/fiscal requests/roulette gratuita/rewards | phase11-report; tests/modules/favorites/reviews/receipts/promotions; test_phase11_postgresql | Proveedores fiscales reales pendientes; NO cupones/pago por giro |
| 12 | Gates, security, E2E/PG/carreras/perf, backup/docs/CI | phase12-report; tests/quality/security/e2e/performance; test_phase12_* | Implementación local; RELEASE BLOCKED, PG/CI/drill sin ejecutar |

Los nombres de reportes en la tabla corresponden a docs/phaseN-report.md.
Rama histórica consolidada: chore/backend-foundation, no se inventan feature
branches. El documento F12 propone chore/release-hardening; prevalece la
instrucción directa de mantener la rama actual.

## Fuentes de verdad transversales

Catalog valida IDs/precios/disponibilidad; Cart snapshots temporales;
Orders snapshots históricos y order_status_history; Payments dinero capturado;
Cancellations decisión; Refunds obligación/resultado; Fulfillment transporte;
Notifications/outbox son proyecciones, no autoridad financiera;
Receipts referencia fiscal verificada, no sustituto del ledger;
Promotions premios gratuitos, no descuento automático de Order.

Cobertura RNF-01..14 y blockers: [release-readiness](release-readiness.md).
Permisos/IDOR/privacidad: [security-review](security-review.md).
Contrato por cada operación/módulo: [api-inventory](api-inventory.md).
Despliegue/migración/rollback: [release-runbook](release-runbook.md).
No quedan afirmaciones de que Favorites/Reviews/Receipts/Promotions no existen.

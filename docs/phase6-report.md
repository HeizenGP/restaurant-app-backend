# Fase 6 — Payments

Informe de implementación y verificación. 7 de octubre de 2026.

## 1. Resumen ejecutivo

ONLINE PAYMENT ORCHESTRATION: IMPLEMENTADA.

REAL EXTERNAL PAYMENT PROVIDER: NO IMPLEMENTADO / PENDIENTE DE SELECCIÓN.

Ledger, caja autorizada, intentos idempotentes, auditoría y frontera webhook
implementados en chore/backend-foundation, desde 43af19e. Ningún cobro real online
se declara realizado o validado.

## 2. Alcance

Cuatro endpoints, confirmación financiera única por Order, correlación verificada,
reintentos, eventos duplicados/fallos/capturas tardías y proyección atómica a Orders.
Moneda de negocio fija PEN; importe tomado del total histórico.

## 3. RF/RN cubiertos

RF-21/RN-07: LOCAL admite CASH/ONLINE. RF-28, RF-36 y RN-06: PICKUP/DELIVERY
solo se confirman con pago online completo. RN-01 e identidad/ownership de guest
se preservan. No saldos, parcial ni contraentrega.

## 4. ONLINE pendiente de proveedor

Faltan selección/contrato del proveedor, adapter real, SDK si procede, secretos,
sandbox, firma/replay/retry/idempotencia según su protocolo y validación de cobro.
No se inventan credenciales, firmas ni una pasarela. Adapter por defecto falla
cerrado con 503 antes de crear nuevos registros.

## 5. Arquitectura

Slice app/modules/payments con domain/application/infrastructure/presentation.
Puertos específicos PaymentRepository, PaymentOrderLifecycle,
OnlinePaymentGateway y PaymentAuthorization, sin bases genéricas.
Domain/Application no dependen de ORM, HTTP, Pydantic ni adapters.

## 6. Límites Payments/Orders

Payments confirma dinero; Orders decide el lifecycle y Kitchen observa Orders.
OrderPaymentContext es un contrato mínimo sin PII/ítems.
Adapter Payments usa el repositorio público SQLAlchemyOrderPaymentRepository,
no privados del repositorio agregado. No importa Cart/Catalog/Kitchen.
Deuda histórica Orders.Domain → Cart.Domain permanece sin refactor masivo.

## 7. Archivos creados

Payments: domain/models.py y transitions.py; application/dtos.py, errors.py,
ports.py y services.py; infrastructure/authorization.py, gateway.py, orders.py,
persistence/models.py y repositories.py; presentation/dependencies.py, router.py,
schemas.py y paquetes __init__. Orders: domain/payments.py e
infrastructure/payments.py. Migración 0006_create_payments.py; tests Payments,
test_phase6_migration.py, integración PostgreSQL opt-in y este informe.

## 8. Archivos modificados

Orders transitions acepta contexto mínimo reutilizando su política existente.
Router v1 y migrations/env registran Payments. main.py permite Idempotency-Key en
CORS. README actualizado. Tests históricos 1/4/5 verifican su revisión/alcance
fijados, no un head/contador global obsoleto; Fase 6 verifica metadata exacta y
head único. Migraciones 0001–0005 intactas.

## 9. Modelo Payment

payments: UUID, UNIQUE order_id/FK RESTRICT, method_type, NUMERIC(18,2), PEN,
estado, paid_at, reconciliation_required interno, tiempos con zona.
Repositorio no modifica monto/método/currency históricos. GET no crea ledger;
Order legacy PAID sin ledger no se backfillea con procedencia ficticia.

## 10. Attempts

payment_attempts: key cliente por Payment, key proveedor payment-attempt:<UUID>,
proveedor/referencia, monto, estado, código de fallo seguro, acción pública,
created/updated/completed. Máximo uno CREATED/PROCESSING; fallos antiguos
conservados al crear otro intento. Sin datos de tarjeta ni secretos.

## 11. Payment history

payment_status_history: origen/destino, fuente CUSTOMER/STAFF/PROVIDER/SYSTEM,
actor nullable, intento/evento opcionales y hora backend. STAFF exige usuario;
PROVIDER/SYSTEM no lo inventan. Creación inicia PENDING; ningún CRUD público
permite editar o borrar auditoría.

## 12. Provider events

payment_provider_events: UNIQUE proveedor+evento, hash SHA-256, referencia,
resultado verificado, importe/moneda reportados, hora proveedor, recibido/procesado,
intento, estado y reason_code. Sin raw body, headers o firmas. Hash solo trazabilidad;
adapter autentica antes de consultar o escribir.

## 13. Estado de pago

ONLINE: PENDING → PROCESSING → PAID/FAILED; FAILED → PROCESSING para retry.
CASH: PENDING → PAID. PAID terminal. Orders.payment_status conserva PENDING/PAID,
sin PROCESSING/FAILED. Captura tardía desde FAILED usa recuperación auditada
FAILED → PROCESSING → PAID, no transición ilegal.

## 14. Idempotencia

Key initiation independiente de checkout. Misma key repite resultado; nueva key
con intento activo da 409 PAYMENT_IDEMPOTENCY_CONFLICT. Order se bloquea antes de
crear Payment. UNIQUEs cubren Order, Payment+key, proveedor+referencia y evento.
Llamadas concurrentes usan misma key propia en proveedor: requiere su garantía
real, no se afirma exactly-once externo sin integración.

## 15. Cash

LOCAL+CASH no cancelado; actor activo autorizado en sucursal. Reintento PAID
retorna el mismo registro sin nueva historia. Solo actualiza resumen financiero
de Orders, no status/confirmed_at/historia operacional. La liberación
confirm-cash-release sigue siendo una operación independiente.

## 16. Online

Reserva Payment+Attempt+historia y commit antes de red; luego bloquea/revalida
para guardar respuesta del proveedor. Initiation DTO no permite SUCCEEDED.
Timeout ambiguo mantiene CREATED recuperable con misma key. Rechazo confirmado
conserva FAILED, devuelve 200 con ese estado y permite nueva key. No activa Order.

## 17. Webhook

Sin JWT, adapter autentica raw bytes antes de construir VerifiedPaymentEvent.
Body máximo 64 KiB; dedupe antes de locks Order → Payment → Attempt.
Comprueba relaciones/importe/moneda. Procesado duplicado ACK 200 sin efectos;
mismo ID con otro body 409. Mismatch autenticado: REJECTED+ACK 200 sin pagar.
Unknown ref conserva evidencia, commit y 503 PAYMENT_PROVIDER_EVENT_PENDING
para pedir reintento; mismo evento puede procesarse al persistirse referencia.

## 18. Seguridad

AuthService resuelve JWT real y usuario/Customer actuales, incluidos bloqueados.
CurrentCustomer para online/GET; registrado+permiso DB para caja, no claims roles.
Body/query extras 422. No mark-paid público/PATCH arbitrario/test-success.
Errores seguros sin SQL, inputs, raw proveedor o secretos.

## 19. PCI/data minimization

No PAN/CVV/expiración ni secretos de proveedor. Acción cliente solo REDIRECT HTTPS
sin credenciales o SDK_TOKEN PÚBLICO; contrato no admite tokens privados.
repr oculta acciones. GET oculta keys/referencias/acciones/auditoría interna.
Estas medidas no son certificación PCI ni validación de un proveedor real.

## 20. Guest

Puede iniciar/consultar Order online propio existente con Customer válido sin
User; historia CUSTOMER puede tener actor null. No caja ni pedidos ajenos.
No cambia elegibilidad del checkout ni exige crear User para pagar.

## 21. Registered

Customer comercial existente y User activo resuelto por Auth. Un User sin
Customer no habilita API cliente. Ser registrado no otorga permiso de caja.
Historia CUSTOMER conserva user_id cuando existe.

## 22. Ownership

Iniciar: SELECT/FOR UPDATE con Order.id+customer_id. GET: JOIN Orders filtrado
customer_id+Order.id antes de cargar intentos. Inexistente/ajeno 404 sin revelar
importe/sucursal/identidad ni llamar al proveedor.

## 23. Branch authorization

SQLAlchemyBranchRepository.has_permission reutilizado: User activo/no borrado,
Branch activa, asignación activa/no finalizada, Role BRANCH y permiso vigente.
PAYMENT_CASH_MANAGE solo ADMIN BRANCH en seed, no KITCHEN/CUSTOMER. Scope
Order.id+branch_id en SQL; sin permiso global inventado.

## 24. Order activation

Reutiliza status_after_payment y validate_transition de Orders. Update condicional
payment_status/status/confirmed_at e historia en misma sesión/transacción que
pago/evento. Timestamps backend. Ninguna llamada a KitchenService.

## 25. LOCAL

ONLINE PENDING_PAYMENT → WAITING con confirmed_at backend.
CASH conserva estado operacional, incluso PENDING_CASH_CONFIRMATION.
Cobrar no libera automáticamente a cocina.

## 26. PICKUP

Pago completo verificado: SCHEDULED antes de calculated_kitchen_release_at,
WAITING desde ese instante. Reloj backend, no occurred_at arbitrario del proveedor.
SCHEDULED excluido de Kitchen; scheduler posterior fuera de alcance.

## 27. DELIVERY

Pago completo verificado: PENDING_PAYMENT → WAITING y confirmed_at.
No contraentrega ni nuevas acciones OUT_FOR_DELIVERY/DELIVERED.

## 28. Late payment

CANCELLED sigue CANCELLED sin confirmed_at/historia operacional nuevos; verdad
financiera PAID y reconciliation_required. Fallo después de PAID se ignora.
Segundo intento capturado conserva SUCCEEDED/evidencia y conciliación, no segunda
historia PAID/activación. Captura antigua con otro intento activo también señala
conciliación. No refunds automáticos.

## 29. Transacciones

Una unidad para CASH; reserva/finalización separadas para initiation, red sin
transacción/locks; una unidad webhook para intento/pago/evento/Orders/ambas
historias. Fallo/commit fallido revierte todo. Unknown ref se conserva antes del
503 explícito, no confirma parcialmente dinero.

## 30. Concurrencia

FOR UPDATE y orden global Order → Payment → Attempt; locator no bloquea intento
primero. Dedupe con INSERT ON CONFLICT y lock por evento. Updates comparan estado
original/scope. Tests memoria y SQL barreras; concurrencia PostgreSQL real NO
probada al no existir TEST_DATABASE_URL. Garantía externa depende del proveedor.

## 31. Migration 0006

0006_payments → down_revision 0005_kitchen. Cuatro tablas, checks/FKs RESTRICT,
índices, dos triggers reutilizando restaurant_phase1_set_updated_at y seed caja.
Sin nuevas extensiones/funciones/SDK/backfill Orders/startup DDL.
Downgrade aborta con ledger/eventos no vacíos ANTES de DDL, preserva auditoría.
Vacío retira solo tablas/permisos/triggers propios.

## 32. Constraints

Payment: UNIQUE Order, monto finito no negativo, PEN, estados/métodos válidos,
paid_at iff PAID y estados CASH. Attempt: key/proveedor, completed iff terminal,
referencia para PROCESSING/SUCCEEDED, failure solo FAILED, acción emparejada
solo PROCESSING. Historia: source/actor/inicio/estados. Eventos: key/hash/result,
money/currency, procesamiento/tiempo y códigos. Dinero NUMERIC(18,2), nunca float.

## 33. Indexes

Partial UNIQUE Payment con intento CREATED/PROCESSING y proveedor+ref no nula.
UNIQUE Order, Payment+key y proveedor+evento. Intentos/historia por Payment,
created_at,id; eventos processing_status,received_at,id para atención operativa.
Sin tablas Kitchen ni índices redundantes sobre columnas ya únicas.

## 34. Tests Domain

105 tests: Decimal/precisión, invariantes, keys, grafos, actores, acciones,
evidencia verificada y política Orders por modalidad. Initiation no puede
construir SUCCEEDED.

## 35. Tests Services

64 tests (services+additional): ownership/guest, caja/online, keys/timeouts/declines,
config faltante, duplicados/collision, mismatches, unknown/early callbacks,
rollback, capturas tardías/múltiples, replay tras PAID y concurrencia en memoria.
Proveedor simulado solo tests; no se presenta como integración real.

## 36. Tests API

63 tests con JWT real AuthService y memoria: errores 401/403/404/409/422/503,
bloqueados, guests, ownership, permiso caja, mass assignment body/query,
headers/privacidad, webhook firmado test sin JWT, 64 KiB y OpenAPI.
Sin bypass de get_current_principal para fingir permiso.

## 37. Tests Repository

24 tests: scopes SQL, locks, contexto mínimo, updates condicionales sin cambiar
montos, lectura bounded/orden estable, locator sin lock, ON CONFLICT,
mappers y errores integridad seguros.

## 38. Tests Migration

7 tests: head/cadena, metadata exacta, montos/tiempos, checks/índices equivalentes
a revisión fijada, barreras, grants y downgrade protegido.
Verificación histórica 0001–0005 se conserva.

## 39. PostgreSQL integration

Test opt-in nuevo prepara 0001→0006 en TEST vacía, comprueba permisos/constraints,
CASH/online, idempotencia webhook, FK real fallida para rollback, Kitchen sin
SCHEDULED ni CASH no liberado, downgrade rechazado con datos y downgrade/upgrade
vacío, rollback externo completo. Ejecutado: 1 skipped porque TEST_DATABASE_URL
no está configurada. No ejecutó DDL real.
Suite opt-in completa pytest -m integration -q: 6 skipped, 1069 deselected,
por TEST_DATABASE_URL ausente.

## 40. Ruff

ruff check .: All checks passed.
ruff format --check .: 267 files already formatted.
git diff --check: sin errores.

## 41. Pytest

Baseline 806 passed/5 skipped. Suite final pytest -q: 1069 passed, 6 skipped,
244.54 s. Payments separado: 256 passed, 56.68 s. Migración: 7 passed.
Los seis skips son integración opt-in; no equivalen a PostgreSQL validado.

## 42. Alembic heads/history

Único head 0006_payments. Cadena 0001_phase1 → 0002_catalog → 0003_cart →
0004_orders → 0005_kitchen → 0006_payments. Offline 0006 validado.
No upgrade/current/stamp ejecutado contra la base manual incompatible.

## 43. PostgreSQL real validado o no

NO VALIDADO en Fase 6: falta TEST_DATABASE_URL. SQL offline/metadata y mocks no
sustituyen ejecución real de constraints/locks/triggers/tx. Base normal intacta.
La API/Swagger existente responde HTTP 200 y expone los cuatro endpoints.
Smoke test del webhook sin proveedor: HTTP 503, falla cerrado sin pago ficticio.

## 44. Provider real integrado o no

NO IMPLEMENTADO / PENDIENTE DE SELECCIÓN. Orquestación/puertos implementados.
Unconfigured devuelve 503. Simulado/HMAC de tests NO es una pasarela productiva
ni firma universal. Ningún cobro real realizado.

## 45. Git status

chore/backend-foundation, HEAD 43af19e. Instrucción directa misma rama prevalece
sobre feat/payments del adjunto. Cambios sin staging/commit/push; sin rama nueva,
merge/rebase/reset. El árbol estaba limpio al empezar; cambios previos preservados.

## 46. Riesgos

Sin proveedor no se valida su firma/replay/idempotencia/acciones. CREATED puede
necesitar mismo key para recuperarse tras crash. Unknown ref necesita retry y
atención si no se correlaciona. Capturas tardías/múltiples se señalan sin refund.
Legacy PAID sin ledger necesita conciliación explícita, no datos fabricados.
Integración PG pendiente; esquema manual incompatible no debe migrarse a ciegas.

## 47. Pendientes

Configurar TEST_DATABASE_URL vacía/distinta y ejecutar pytest -m integration.
Seleccionar/integrar proveedor y contrato de firma/replay/retry/idempotencia,
secretos y pruebas sandbox. Atender reconciliation_required/eventos pendientes
si hay operación real futura. Usuario revisa antes de staging/commit/push.

## 48. Fuera de alcance

Fase 7, scheduler PICKUP, cancelaciones/refunds, caja contable, impuestos/promos,
pago parcial, conciliación automática, notificaciones, SDK móvil/frontend,
entrega/atención y APIs mark-paid/test productivas. Sin refactor masivo.

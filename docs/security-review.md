# Revisión de seguridad — Fase 12

Revisión de código y pruebas automatizadas, no pentest externo ni certificación.
Los tests HTTP usan AuthService/PyJWT reales y almacenamiento TEST en memoria;
la matriz de filas/revocaciones PostgreSQL está preparada, no ejecutada.

## Hallazgos

| Finding | Severidad | Módulo / evidencia | Fix / estado |
| --- | --- | --- | --- |
| Asignación futura autorizaba catálogo global | Media | can_manage global omitía assigned_at; nueva regresión falló antes del fix | Añadir assigned_at <= now(); 19 tests repositorio pasan; PG pendiente |
| LOCAL no tenía operación READY → SERVED | Alta funcional | Estado/graph existían, pero no caso de uso/ruta; impedía cierre/review | Operación específica ORDER_MANAGE branch-scoped, lock, historia y auditoría atómicos; 11 regresiones pasan |
| Secretos largos repetitivos/placeholder aceptables | Alta en despliegue | Settings anterior aceptaba cadenas repetidas y variantes placeholder | Validación staging/production reforzada, debug prohibido, credenciales DB/URL obligatorias; tests pasan |
| Faltaban cabeceras seguras/correlación | Baja | Respuestas HTTP/SSE y 500 sin control común | Middleware ASGI sin buffering + handler 500; cabeceras/correlación probadas |
| Uvicorn podía imprimir valores de excepción manejada | Media | ServerErrorMiddleware vuelve a lanzar el error; logger con exc_info/lifespan traceback | Filtro idempotente uvicorn.error conserva clase/ubicación sin valores; regresión pasa |
| Restauración con SHA vacío fallaba fuera del error seguro | Baja | Lectura split()[0] | Guard explícito; checksum corrupto/vacío impide acceso a DB |
| Preflight negativo importaba configuración global antes del guard | Baja | Import de app.main arrancaba Settings antes del try | Factory sin side effect + inputs default explícitos para artefactos; subprocess bajo prod inválida probado |
| Access logs ajenos pueden registrar query/PII | Media operativa | HTTPX/servidor/proxy pueden registrar URL aunque app no lo haga | App logs solo método/status/request ID; --no-access-log y redacción proxy en runbook; configuración externa pendiente |
| Audit no es inmutable ante rol DB privilegiado | Media operativa | API recorder append-only, pero audit_logs no tiene trigger anti-UPDATE/DELETE | No se añadió trigger sin evidencia; aplicar least privilege, retención y control operador; PARTIAL |
| PostgreSQL real no disponible | Alta para release | Sin TEST_DATABASE_URL ni herramientas PG locales | CI dedicado y harness preparados; BLOCKED hasta ejecución real |

READY → SERVED reutiliza el graph existente, no habilita cambios genéricos de
estado. Mantiene la política CASH LOCAL existente, que puede servir antes del pago
si está confirmada; no altera ledger ni afirma pago por servir. ONLINE exige PAID.

## Matriz de permisos

“Admin A” significa REGISTERED activo, asignación ADMIN vigente en A y permiso
leído de DB. El rol textual de JWT o un user_roles global no da scope de sucursal.
Kitchen solo KITCHEN_VIEW/KITCHEN_MANAGE, nunca gestión financiera ni cierre LOCAL.

| Familia | Sin bearer | Guest/Customer | Kitchen A | Admin A | Admin B en A |
| --- | --- | --- | --- | --- | --- |
| Customers / staff / branches / dashboard admin | 401 | 403 | 403 | Permiso específico | 403 |
| Catalog admin global | 401 | 403 | 403 | CATALOG_MANAGE, cualquier asignación ADMIN vigente | Puede gestionar global con su permiso; no overrides A |
| Catalog override / order config A | 401 | 403 | 403 | CATALOG_MANAGE / ORDER_SETTINGS_MANAGE | 403 |
| Orders release / serve-local A | 401 | 403 | 403 | ORDER_MANAGE, graph específico | 403 |
| Kitchen queue / prepare A | 401 | 403 | VIEW / MANAGE | Si tiene permiso explícito | 403 |
| Cash payment A / refunds A | 401 | 403 | 403 | PAYMENT_CASH_MANAGE / REFUND_MANAGE | 403 |
| Fulfillment A | 401 | 403 | 403 | FULFILLMENT_VIEW / FULFILLMENT_MANAGE | 403 |
| Cancellation admin A | 401 | 403 | 403 | CANCELLATION_VIEW / CANCELLATION_MANAGE | 403 |
| Reviews A | 401 | 403 | 403 | REVIEW_VIEW | 403 |
| Receipts A | 401 | 403 | 403 | RECEIPT_VIEW / RECEIPT_MANAGE | 403 |
| Promotions A | 401 | 403 | 403 | PROMOTION_VIEW / MANAGE / REDEEM según operación | 403 |
| Admin realtime A | 401 | 403 | 403 | ORDER_REALTIME_VIEW | 403 |

Otros permisos F10: CUSTOMER_VIEW/MANAGE, STAFF_MANAGE,
BRANCH_VIEW/MANAGE, ORDER_VIEW, DASHBOARD_VIEW. No SUPERADMIN nuevo.
La suite F12 recorre las **140 operaciones Bearer** sin credenciales: todas 401.
Las matrices completas con actores y recursos están en tests/modules de cada
slice; F12 añade cruces reviews/receipts/promotions/realtime y serve-local.
Un usuario BLOCKED produce 403 ACCOUNT_BLOCKED por contrato existente.

## IDOR / ownership

| Recurso | Predicado / resultado |
| --- | --- |
| Profile/address/cart/order/payment/cancellation/refund | customer_id actual, no identidad del body; recurso ajeno 404 o denial previsto |
| Favorites | user_id actual; Guest 403; no parámetro de propietario |
| Reviews / receipt request | order.customer_id; pedido ajeno 404 |
| Notifications / devices / customer SSE | customer_id actual, push token privado; lectura/stream ajenos no visibles |
| Rewards / roulette | customer actual + branch/campaign; premios ajenos no canjeables |
| Admin recurso de otra sucursal | Sin permiso en branch → 403; permiso en su propia branch pero ID extranjero → 404 |
| Kitchen / SSE kitchen | Predicado branch, proyección operativa sin teléfono/dirección |

F12 añade regresiones de receipt/review ajenos, patch de campaign y proceso
fiscal de branch extranjera, permisos revocados con mismo token y claims falsos.
PG añade A/B, staff futuro/expirado, usuario deshabilitado y branch inactiva.
No registrar el valor del identificador privado en logs.

## Auth, OTP, errores y privacidad

Argon2id (pwdlib), comparación de contraseña y dummy hash en login; sin passwords
en respuesta. JWT verifica firma HS256 fija, issuer, audience, exp y purpose;
access/refresh/phone verification no intercambiables. Refresh se hashea,
rota/revoca persistentemente y detecta replay; JWT nunca decide permisos.
OTP usa HMAC + pepper, expiry, cooldown, máximo de intentos y consumo único;
debug solo development/test; sin sender real en staging/production devuelve fallo.

Tokens necesariamente están en respuestas de autenticación a su propietario:
esto no es fuga de hash/secreto de almacenamiento. DeviceRequest acepta push_token,
DeviceResponse no lo devuelve. Datos fiscales/entrega se exponen solo a casos
autorizados que los requieren; Kitchen/SSE no heredan esas proyecciones.
OpenAPI response schemas se recorren recursivamente para detectar hashes,
push_token, pepper, fingerprints privados y random_draw.

Errores 422 omiten input; 500 genérico no devuelve excepción, SQL, DSN o traceback.
El log app guarda clase/ubicación de error sin valores, y método/status/request ID.
El filtro de uvicorn.error también elimina exc_info y tracebacks preformateados
de lifespan; conserva diagnóstico sin el valor de excepción. No configura
access logs ni logger de un proxy externo: esa puerta sigue siendo operativa.
X-Request-ID tiene longitud/charset limitado; inválido se reemplaza. No es
identidad autenticada ni clave de auditoría confiable suministrada por el cliente.
CORS rechaza wildcard y origins con credenciales/path/query; Last-Event-ID
permitido, X-Request-ID expuesto. No agregar headers HSTS sin TLS operativo.

## SQL y límites de arquitectura

SQL usa parámetros bound. La interpolación de admin_repository F10 es una
excepción revisada de **fragmentos SQL constantes/allowlisted**: FIELDS,
CUSTOMERS_FROM, VISIBLE, search_clause, key, table, condition. Los valores de
búsqueda/IDs permanecen bound. El test AST falla con nuevos nombres/expresiones;
no es un scanner taint completo ni permite interpolar datos request.
Domain no depende de frameworks; Application usa ports; Presentation no ejecuta
SQL/commit/rollback; DI compone adaptadores. No create_all/drop_all en runtime.

No pip-audit/Bandit ni escaneo externo de secretos ejecutado; pip check solo
verifica consistencia de dependencias. Dependabot configurado, no ejecutado.
TLS, least-privilege DB, rate limiting distribuido, cifrado/retención y monitoreo
siguen siendo gates del despliegue y no se declaran resueltos por estas pruebas.

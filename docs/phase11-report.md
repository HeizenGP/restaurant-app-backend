# Informe de Fase 11 — Favorites, Reviews, Receipts y Promotions

Fecha: 2026-10-07. Repositorio: `/home/heizen27/proyectos/restaurante-backend`.
La petición directa conserva `chore/backend-foundation`; prevalece sobre la rama propuesta en el adjunto.

## 1. Resumen ejecutivo

Implementados cuatro slices independientes: Favorites, Reviews, Receipts y Promotions.
Se conservó `chore/backend-foundation`, desde `87202f0` (Fase 10).
22 operaciones HTTP nuevas, nueve tablas, seis permisos y revisión incremental 0011.
RF-55 tiene dominio y gestión implementados; emisión fiscal real PENDIENTE DE PROVEEDOR.
La base normal no se migró ni se estampó. Resultados de validación en secciones 49–60.

## 2. Alcance y contratos HTTP

Prefijo `/api/v1`. JWT real obligatorio; las identidades proceden de Auth,
nunca del body. Request bodies y queries de filtros usan extra_forbid.

| Métodos | Ruta sin prefijo | Autoridad |
| --- | --- | --- |
| GET | /favorites?branch_id=UUID | Cuenta registrada |
| PUT, DELETE | /favorites/{product_id} | Cuenta registrada propietaria |
| POST, GET | /orders/{order_id}/review | Customer propietario, registrado o Guest |
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

POST de creación/solicitud/giro: 201, incluso retry idempotente.
PUT favorito: siempre 200, DELETE: 204, resto 200. Errores con envelope seguro
401/403/404/409/422/503. Sin endpoints de edición/borrado de reviews ni auto-redención.

## 3. CU cubiertos

El adjunto identifica CU-09, CU-10, CU-11 y CU-25–CU-30.
No se encontró un catálogo oficial que defina sus nombres/correspondencia individual.
Se documentan los IDs y la cobertura funcional de las APIs; no se inventan nombres ni
se declara una equivalencia formal uno-a-uno sin esa fuente.

## 4. RF-08 — Favorites

IMPLEMENTADO: favoritos por User registrado, alta y baja idempotentes, catálogo
público por sucursal en un único lote. Guest recibe 403 REGISTERED_ACCOUNT_REQUIRED.

## 5. RF-55 — Comprobantes

DOMINIO Y GESTIÓN IMPLEMENTADOS: solicitud del propietario sobre pedido realmente
pagado, BOLETA/FACTURA, snapshots, consulta y procesamiento administrativo.
EMISIÓN FISCAL REAL PENDIENTE DE PROVEEDOR. No se declara integración SUNAT.

## 6. RF-56 — Reviews

IMPLEMENTADO: una calificación entera 1..5 por pedido completado y propietario.
Comentario opcional plano, máximo 1000 caracteres; histórico inmutable.

## 7. RF-57 — Roulette

IMPLEMENTADO: ruleta promocional gratuita por sucursal, campaña configurable,
términos visibles, RNG criptográfico servidor, probabilidades en basis points y NO_PRIZE.

## 8. RF-58 — Rewards

IMPLEMENTADO: WIN otorga recompensa histórica de producto; Customer lista solo
sus premios; ADMIN autorizado redime en la sucursal, con expiración e idempotencia.

## 9. RN-23 — Gratuita

IMPLEMENTADO: no cobro, tokens comprados, compra previa, apuesta ni consumo de saldo.
El giro no escribe Payments, Orders o Cart y no altera subtotales/descuentos.

## 10. Arquitectura

Cada slice contiene domain, application (puertos/casos de uso), infrastructure y
presentation. Dominios con dataclasses/reglas puras, sin ORM/Pydantic/FastAPI.
Orders expone CustomerOrderReader; Branches expone CustomerBranchReader; Catalog
expone product_batch. No acceso a servicios privados de otro slice ni God Service.

## 11. Slices y archivos principales

Nuevos directorios `app/modules/{favorites,reviews,receipts,promotions}`.
Puertos públicos en Orders/Branches, identidad y calendario compartidos,
routers en `app/presentation/api/v1/router.py`, metadata en `migrations/env.py`.
Tests de cada slice, helpers SOLO tests, test de migración y PostgreSQL opt-in.
No nuevas dependencias ni cambios de infraestructura/startup.

## 12. Favorites — almacenamiento

customer_favorites: UUID, user_id, product_id, created_at; unicidad (user,product).
PUT usa ON CONFLICT DO NOTHING y lectura posterior; UUID/created_at no cambian
en retry. DELETE filtra por User y Product; no borra la selección de otra cuenta.

## 13. Favorites — registrados

UserID es la clave de Favorites, CustomerID no lo sustituye. Regla aplicada antes
de tocar repositorio/catálogo, con principal validado por Auth.
Una cuenta bloqueada deja de usar su mismo JWT firmado.

## 14. Favorites — catálogo batch

CatalogService.product_batch reutiliza la proyección pública/pricing de Catalog,
overrides por Branch y reglas de publicación. Una consulta batch, sin consulta
por favorito; repositorio Catalog carga agregados con número constante de consultas.
Temporalmente no disponible puede mostrarse is_available=false; archivado/no publicable
se omite sin destruir el favorito. Validación de Branch incluso en lista vacía.
limit=50 (1..100), offset=0 (0..10000); se pagina almacenamiento antes de filtrar visibilidad,
por lo que un lote puede devolver menos de limit.

## 15. Reviews — entidad

order_reviews conserva Order/Customer/Branch, rating/comment/created_at/updated_at.
order_id único, FK históricas RESTRICT. Sin PATCH/DELETE público o administrativo.
La sucursal y propietario se obtienen de Orders, no del cliente.

## 16. Reviews — pedido completado

Solo LOCAL/SERVED, PICKUP/PICKED_UP y DELIVERY/DELIVERED. Todos los estados
pendientes, preparación, readiness, reparto y CANCELLED son rechazados 409.
Se bloquea Order antes de validar e insertar; trigger DB protege la misma asociación.

## 17. Reviews — Guest

CurrentCustomer incluye Guest con identidad existente verificada por Auth.
Mismos ownership, límites y estado completado que Registered.
Order/review ajeno o inexistente: 404; no se revela su existencia.

## 18. Reviews — administración

REVIEW_VIEW actual por Branch. SQL filtra Branch/rating/fechas antes de paginar,
orden estable created_at,id DESC. Proyección sin CustomerPII.
Fechas opcionales inclusivas del calendario local convertidas a UTC [start,end);
sin límite artificial de 31 días. Query rating válida numérica; body estricto entero.
Resumen/average opcional no implementado.

## 19. FiscalDocument — entidad

fiscal_documents guarda solicitud única por Order, Customer/Branch, tipo, estado,
amount NUMERIC(12,2) histórico, PEN servidor, destinatario y resultado externo
opcional. request_key_hash y fingerprint privados; ambos SHA256.
PENDING -> PROCESSING -> ISSUED/FAILED; FAILED permite nuevo intento explícito.

## 20. BOLETA

Documento de solicitud, destinatario opcional. No genera serie/número, archivo
o validación tributaria inventada. Campos de destinatario normalizados y acotados.
La conformidad tributaria real corresponde al futuro proveedor seleccionado.

## 21. FACTURA

Exige estructura mínima: tipo RUC, 11 dígitos ASCII, nombre y dirección no vacíos.
Aplicación y CHECK PostgreSQL rechazan ausencia/NULL en campos requeridos.
Esto no valida inscripción RUC ni sustituye reglas fiscales del proveedor.
Body no admite amount, currency, status, serie, número, emisión o identificador ajeno.

## 22. FiscalDocumentGateway

Puerto issue/lookup con IDs estables de documento e intento. Resultado debe ser
verificado, corresponder a ambos IDs y proveedor, y para ISSUED coincidir en
Decimal amount/PEN, timestamp aware y referencias válidas.
Se reserva/commit antes de llamar externamente; finalización en transacción nueva.

## 23. Proveedor sin configurar

UnconfiguredFiscalDocumentGateway es el único adaptador productivo actual.
Procesar devuelve 503 FISCAL_PROVIDER_UNAVAILABLE sin crear intento ni cambiar
PENDING. No SDK, credenciales, HTTP simulado ni proveedor arbitrario seleccionado.

## 24. No fake SUNAT

No SUNAT fake, series/números fiscales de producción, PDF/XML/CDR ficticios o
enlaces inventados. Adapters deterministas con referencias TEST existen exclusivamente
en tests; un resultado ISSUED de test no es evidencia de emisión legal.

## 25. Receipt idempotency

Idempotency-Key obligatorio, ASCII acotado 1..128; se persiste solo hash.
Misma clave + payload normalizado = mismo documento; payload distinto con esa clave:
409 RECEIPT_IDEMPOTENCY_CONFLICT. Otra clave para mismo Order:
409 FISCAL_DOCUMENT_ALREADY_EXISTS. Ownership se verifica antes de resolver retry.

## 26. Fiscal attempts

fiscal_document_attempts: documento/clave únicos, un intento activo parcial,
provider/reference/status/failure/completed timestamps. UUID sirve de clave externa.
Un timeout/respuesta no verificada deja PROCESSING durable; otra clave no reemite.
Retry con la misma clave llama lookup, no issue. Terminal antiguo está fenced y no
sobrescribe resultado posterior; fallo de finalización revierte intento+documento
y permite conciliación posterior. No reemisión automática por timeout.

## 27. Cancelación/refund e historia fiscal

Solicitud/importe/destinatario inmutables, ISSUED inmutable; no se borran al cancelar
o devolver. GET y retry de solicitud recuperan historia aunque Order ya se haya
cancelado. Relaciones RESTRICT y trigger fiscal de no-delete.
Notas de crédito y política tributaria de devolución quedan fuera de esta fase.

## 28. Promotions — alcance

Solo ruleta gratuita y recompensas de producto. Sin motor general de cupones,
descuentos, campaigns pagadas, puntos, compras obligatorias o marketing automation.
CustomerID mantiene namespace de Guest y Registered sin clonar identidad.

## 29. Roulette campaigns

roulette_campaigns: Branch, name/terms, ventana UTC, cooldown, máximo diario opcional,
vigencia premio opcional, version, autor y timestamps. Creación siempre draft;
premios antes de activar. Una campaña activa por Branch mediante índice parcial.
Toda mutación de configuración incrementa versión en el mismo commit.

## 30. Términos visibles

GET roulette devuelve terms_text y configuración efectiva de campaña.
Texto plano, no vacío y <=10000; name <=150. Configuración no se acepta desde giro.
Fechas de creación/edición aware, ends_at>starts_at si existe.

## 31. Frecuencia

spin_cooldown_seconds>=0 obligatorio; máximo diario NULL o entero >=1;
reward_validity_days NULL o entero >=1. Sin defaults comerciales arbitrarios.
Participación por campaign/customer: último giro y contador de día local de Branch.

## 32. Probabilidades

Premios activos tienen probabilidad 0..10000; suma activa <=10000.
Exhausted/unavailable convierte su intervalo en NO_PRIZE, no redistribuye el peso
a otros premios. Inactivo tiene ancho cero. Política pública y selección coinciden.

## 33. Basis points

Enteros exactos: 100 bps = 1%. No float para dinero/probabilidad configurada.
Rango RNG 0..9999, intervalos semiabiertos ordenados por sort_order,UUID.
Porcentajes de salida Decimal; campos configured/effective diferenciados.

## 34. NO_PRIZE

Resto =10000-suma de probabilidades efectivas. Resultado NO_PRIZE persiste el
spin y consume la frecuencia, sin crear Reward. No se rerollean pérdidas.
Ejemplo validado: 1000+500 bps produce exactamente 8500 resultados sin premio
sobre los 10000 puntos del espacio determinista de pruebas.

## 35. RNG seguro

SecretsRandomSource usa secrets.randbelow(10000) por giro nuevo.
Cliente no envía draw, outcome, prize, reward, probabilidad ni expiry.
Draw inválido aborta la transacción. Fuentes fijas son exclusivamente doubles de tests.

## 36. Spin idempotency

Idempotency-Key obligatorio con hash privado. Unicidad campaign/customer/hash y,
adicionalmente, Branch/customer/hash para recuperar retry tras cambiar campaña activa.
Retry devuelve spin histórico, incluso tras desactivar campaña/Branch o producto.
No nueva participación/award/RNG. Estado de Reward se proyecta actualizado
(REDEEMED/EXPIRED), sin alterar el resultado o snapshot del giro.

## 37. Participation, cooldown y día

Upsert participation antes de FOR UPDATE, dentro del lock de Campaign.
Cooldown bloquea incluso primer acceso concurrente; día definido por ZoneInfo de
Branch, con reset al siguiente midnight local, incluido DST.
next_spin_at=max(cooldown,reset diario) si ambos aplican; frontera exacta permite girar.
No claim frontend ni condición de compra para habilitar.

## 38. Rewards históricos

customer_rewards único por Spin, guarda Campaign/Customer/Branch/Prize/Product,
product_name_snapshot, AVAILABLE, awarded_at y expiry servidor.
WIN incrementa awarded_count condicional y crea Reward atómicamente con Spin y
Participation. NO_PRIZE no inserta Reward. Producto renombrado no cambia snapshot.

## 39. Expiry

NULL validity -> NULL expiry. Configurado -> awarded_at+days.
GET calcula EXPIRED al alcanzar expires_at<=now sin escribir ni scheduler.
Redemption vuelve a evaluar la frontera; un premio redimido sigue REDEEMED.
Overflow de vigencia representable aborta giro con 422 y rollback.

## 40. Redemption

PROMOTION_REDEEM actual, Branch activa, lock Reward filtrado por Branch.
AVAILABLE/no expirado -> REDEEMED con timestamp/actor de servidor, audit y commit.
Retry de REDEEMED no cambia timestamp/actor ni duplica audit, incluso luego de expiry.
Ajeno:404, scope:403, expirado:409 ROULETTE_REWARD_EXPIRED. Sin auto-redención Customer.

## 41. Aislamiento y privacidad

No writes nuevos a Orders, Payments, Cart, Notifications/SSE. Owner siempre UserID
o CustomerID de Auth, never supplied IDs. RUC/DNI/dirección no se incluyen en errores,
audit genérico ni realtime. Schemas de salida explícitos ocultan hashes/CustomerID,
actor de redención y snapshot/draw internos; detalle fiscal solo owner/admin autorizado.

## 42. Permisos

REVIEW_VIEW, RECEIPT_VIEW, RECEIPT_MANAGE, PROMOTION_VIEW, PROMOTION_MANAGE,
PROMOTION_REDEEM. Seed idempotente solo ADMIN de scope BRANCH. CUSTOMER/KITCHEN
sin grants nuevos; no superadmin. SQLAlchemyBranchRepository reutiliza comprobación
actual de User/Branch/assignment/Role. Claims roles/permisos del JWT no son autoridad.
Escrituras revalidan permiso tras barrera de fila relevante.

## 43. Audit

FISCAL_DOCUMENT_PROCESS_REQUESTED; ROULETTE_CAMPAIGN_CREATED/UPDATED/ACTIVATED/
DEACTIVATED; ROULETTE_PRIZE_CREATED/UPDATED/DEACTIVATED; ROULETTE_REWARD_REDEEMED.
Audit en mismo commit, estados mínimos sin destinatario, clave o secretos.
No audit global de cada spin: roulette_spins es su historia operacional inmutable.
Fallo de Audit revierte escritura y evita llamada externa prematura.

## 44. Transacciones

Favorites/Reviews: commit y rollback explícitos. Order lock para Reviews/Receipts.
Fiscal reservation/commit, gateway SIN transacción, finalize/commit; fencing de intento.
Promotions Branch SHARE -> Campaign UPDATE -> Participation/prize/reward,
todo spin atómico. Award usa incremento condicional para no sobrepasar max_awards.
Configuración+version+audit y redención+audit son unidades transaccionales.

## 45. Concurrencia

Campaña serializa configuración, spins y agotamiento; Branch SHARE coordina con
desactivación/Staff UPDATE sin serializar otros Customers entre sucursales.
Índices únicos protegen favorito, review, documento, attempt activo, active campaign,
participación, spin y reward. Tests memoria y SQL comprueban contrato; NO son prueba
de PostgreSQL. Se prepararon carreras reales con sesiones/backend_pids distintos
y rendezvous antes de tomar el lock, pero no se ejecutaron por falta de TEST URL.

## 46. Migración 0011

0011_customer_extras depende de 0010_admin. Nueve tablas:
customer_favorites, order_reviews, fiscal_documents, fiscal_document_attempts,
roulette_campaigns, roulette_prizes, roulette_participations, roulette_spins,
customer_rewards. 59 tablas aplicación / 60 con Alembic tras upgrade limpio.
Trece triggers, cinco funciones propias y reutilización de updated_at Fase1 en siete tablas.
0001–0010 sin cambios. No create_all/startup migration/autogenerate.
Downgrade examina las nueve tablas antes de cualquier DELETE/DDL y rechaza dato nuevo;
solo un esquema sin datos F11 permite retirar sus objetos/permisos.

## 47. Constraints

FK históricas RESTRICT; rating, money/PEN, FACTURA mínimos noNULL, hashes SHA256,
probability/awards, campaign window/frecuencia, draw/outcome, JSONB objeto y redención.
Review y Spin UPDATE/DELETE rechazados; fiscal requests no-delete y snapshots congelados.
Trigger de suma de premios bloquea campaña antes de comprobar y aplica <=10000;
activation exige premio activo positivo. Validación product availability sigue en Catalog.

## 48. Índices

Catorce índices explícitos, además de PK/UNIQUE: favorito por propietario/fecha,
reviews Branch/fecha y Branch/rating, fiscal Branch/status, números/referencias únicos,
attempt activo/reference/recent, campaign activa por Branch y fecha, prizes ordenados,
spins Customer/time, rewards Customer/status/time.
Índices comparados con metadata/DDL compilado; sin inventar EXPLAIN ni benchmarks.

## 49. Pruebas Favorites

Dominio/servicio, HTTP con JWT y repositorio: registrados, Guest403, propiedad,
idempotencia PUT/DELETE, batch único, hidden vs unavailable sin borrar registro,
paginación, usuario bloqueado y SQL bound.
24 passed in 9.60s (ejecución individual).

## 50. Pruebas Reviews

Matriz completa tres modalidades/12 estados, rating estricto, comentario seguro,
registered/Guest, duplicate/IDOR, filtros/fecha/scope, endpoints inmutables y SQL.
100 passed in 22.26s (ejecución individual).

## 51. Pruebas Receipts

Pago real coherente, ownership, Decimal histórico, BOLETA/FACTURA, fingerprint,
request/process retries, 503 sin proveedor, verified-only, unknown->lookup, fencing,
rollback de ambas filas, scope/revocación, privacidad, schema servidor y mock SQL.
86 passed in 22.15s (ejecución individual).

## 52. Pruebas Roulette y Rewards

Histograma exacto de los 10000 draws, intervalos, unavailable/deadspace, RNG secrets,
free spins, Guest, clave estable, campaña/branch desactivada, cooldown/localday/DST,
participación inicial simulada concurrente, last-award/double-redeem simulados,
configuración/audit/rollback, expiry boundary y permisos.
115 passed in 44.82s (ejecución individual).

## 53. Pruebas API y JWT

AuthService y PyJWT reales con claves SOLO tests; sustitución de almacenamiento
de negocio, no bypass de CurrentPrincipal. 98 casos HTTP nuevos: Favorites9,
Reviews21, Receipts21, Promotions47. Las APIs ejercitan 22 operaciones.
Tokens válidos con role claims falsos no adquieren autoridad; blocked DB User falla.
Bodies/queries sensibles rechazan extra-fields sin devolver input.

## 54. Pruebas repositorios

18 casos nuevos de SQL scoped/bound, proyección pública, batch, upsert/locks,
attempt fencing, failcode allowlist, commit del caller, counter condicional y redemption.
No se confunde AsyncMock/compilación con ejecución PostgreSQL.

## 55. Pruebas de migración

18 casos F11: head/chain, nueve tablas exactas y 59 metadata, DDL/check/index
matching, FK/timestamps, seeds, triggers/historia y downgrade previo a DDL, arquitectura.
Tests F9/F10 siguen fijados a sus revisiones históricas; se valida su conjunto exacto
offline y preservación de metadata, mientras F11 valida exactamente el head actual.
18 passed in 0.88s (ejecución individual).

## 56. Integración preparada

Seis tests opt-in: schema/seeds/downgrade vacío; reviews/receipts/rollback/historia;
tres carreras de dos conexiones (same-key, cooldown inicial, último premio);
favorite upsert, probability/active-campaign y doble redemption/audit/revocation.
El harness verifica TEST DB dedicada, vacía, distinta de normal, crea un schema UUID
propio y solo limpia ese schema validado. No fallback, creación de base o reset.

## 57. Ruff

ruff check .: PASÓ. ruff format --check .: PASÓ, 519 archivos ya formateados.
Sin dependencias nuevas ni reglas de lint suprimidas para resolver defectos.

## 58. Pytest — regresión

Baseline inicial F0–10: 1 failed,2167 passed,12 skipped (360.78s).
Falló una aserción frágil preexistente: buscar "888" en repr incluyendo UUID aleatorio.
Se cambió para verificar la razón persistida exacta, sin tocar lógica Fulfillment.
Sus 84 casos pasaron. Primer full run F11: 1 failed, 2510 passed, 18 skipped
en 501.03s; único fallo por un conteo histórico de Swagger Orders que no excluía
las extensiones /review y /receipt. Se conservaron sus ocho rutas/14 operaciones
originales y se añadieron aserciones explícitas GET/POST de ambas extensiones.
La prueba corregida pasó (1 passed in 1.35s). F11 completo aislado:
343 passed in 78.61s. La regresión final completa incluye las fases anteriores y F11:
2511 passed, 18 skipped in 477.47s (0:07:57), sin fallos.
Los 18 omitidos son PostgreSQL opt-in (12 previos + 6 F11); no representan
integración real aprobada. Ruff/formato y diff check volvieron a pasar.

## 59. Alembic

alembic heads: 0011_customer_extras (único head).
alembic history: once revisiones lineales, 0010_admin -> 0011_customer_extras.
Esto valida DEFINICIONES, no significa upgrade aplicado a la base normal.
DDL upgrade/downgrade offline validado en tests; parser PL/pgSQL real pendiente.

## 60. PostgreSQL real — omitido

TEST_DATABASE_URL configured: False. Comando explícito:
pytest -q -m integration tests/integration/test_phase11_postgresql.py
Resultado: 6 skipped in 0.13s, motivo TEST_DATABASE_URL is not configured.
No se ejecutaron parser, locks, constraints, queryplans o carreras reales contra PG.
La base normal se observó en Fase 10 con 49 tablas sin alembic_version.
En F11 se intentó solo una inspección read-only desde WSL: ConnectionRefusedError,
sin DDL ni escrituras. Por tanto no se afirma un nuevo recuento exitoso.
No upgrade/stamp/reset allí sin plan explícito y nuevo consentimiento.

## 61. Proveedor fiscal real — pendiente

Seleccionar proveedor, credenciales y contrato de verificación, deduplicación por
attempt UUID y lookup/reconciliation, normativa tributaria y aceptación real.
Sin callback fiscal opcional ni fiscal_provider_events. No certificado de emisión
SUNAT, sandbox de proveedor, PDF/XML/CDR o pruebas fiscales reales en esta entrega.

## 62. RF-46 — Promotions gap

Customers/Staff/Branches de F10 se conservan; Orders previo se reutiliza.
Promotions se implementa en F11 para ruleta gratuita, campaign/prize configuration
y redemption Branch-scoped. El gap Promotions definido para esta fase queda CUBIERTO.
No se declara cobertura de descuentos/cupones/marketing fuera de alcance.
El informe F10 mantiene su estado histórico; esta sección actualiza la trazabilidad.

## 63. Riesgos y límites

Serialización por Campaign limita throughput por sucursal (MVP intencional).
Guest limita frecuencia por CustomerID, no elimina abuso mediante identidades nuevas;
mitigación futura no puede convertirse en cobro/compra obligatoria por RN23.
Disponibilidad Catalog se revalida al girar, no hay inventario/stock warehouse transaccional.
Outcome externo desconocido permanece PROCESSING hasta lookup confiable;
sin proveedor no existe reconciliación productiva. Branch inactiva bloquea administración,
por lo que recovery fiscal bajo ese estado exige política futura explícita.
Vigencias enormes configurables pueden desbordar datetime: 422/rollback documentado.

## 64. Pendientes

PostgreSQL TEST real y validación de contención/queryplans; integración fiscal real
y compliance; notas de crédito; callbacks o summary reviews opcionales si se requieren.
No quedan APIs requeridas de F11 deliberadamente sin implementar.
Las omisiones reales de infraestructura/proveedor se señalan, no se simulan como éxito.

## 65. Git y ejecución

Rama chore/backend-foundation; HEAD inicial/final 87202f0 mientras los cambios F11
permanecen locales. Sin staging, commit, push, branch nueva o worktree.
git diff --check pasó; 0001–0010 intactas; se incorporó solo migración 0011.
Servidor localhost:8000 ya activo: /health 200, OpenAPI con 22 operaciones F11.
Arranque/OpenAPI no validan operaciones contra la base normal incompatible.
git status confirma la misma rama y cambios locales; índice vacío, sin commits nuevos.
El diff tracked no incluye los archivos nuevos aún untracked: 89 nuevos y
10 archivos tracked modificados al verificar; pertenecen a esta implementación.
Swagger /docs 200 y GET rewards sin bearer 401, sin intento de CRUD sobre base normal.

## 66. Fuera de alcance

Sin Fase12, frontend/Flutter, inventory, cupones genéricos, apuesta/pago para girar,
discount mutations, accounting, payroll, nuevo realtime/push, Docker/Redis/Kafka,
proveedor fiscal inventado, secret dumps ni reconstrucción de la base normal.
Siguiente validación segura: aportar TEST_DATABASE_URL dedicada/vacía/distinta
y ejecutar el suite opt-in; emisión legal requiere selección y credenciales reales.

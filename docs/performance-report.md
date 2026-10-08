# Rendimiento — metodología y estado real

**EXECUTED / PASS contra PostgreSQL real**, 2026-10-07 (America/Lima).
Contenedor existente `postgres` (`9aa3c65192ce`), PostgreSQL 18.6, puerto 5432,
base aislada `restaurant_test`; nunca `restaurante_app`.
No p50/p95/p99 ni SLA productivo se deducen de esta ejecución local.
No se agregó índice/migración por intuición ni SLA wall-clock en CI.

## Evidencia actual

Además de los tests unitarios, se ejecutó el dataset y el planner PostgreSQL real.
Entorno Docker/WSL2: AMD Ryzen 7 7435HS, 16 CPU lógicas visibles, MemTotal
8 036 432 kB; sin límite explícito de CPU/memoria del contenedor. Compartido
con la regresión no-integration, sin control de carga ni cache fría. Los planes
observados usaron buffers compartidos en cache: 0 bloques leídos de disco y
0 temporales leídos/escritos en las lecturas capturadas.

### Mediciones observadas

`pytest -m performance -s -q --tb=short --show-capture=no`:
**1 passed, 2874 deselected in 8.73s**, 0 failed, 0 skipped.
Esta medición precede al caso advisory adicional; la suite completa final
contiene 2876 casos aprobados, incluido este mismo test de performance.
TEST_DATABASE_URL derivada en memoria de Settings, cambiando solo la base;
REQUIRE_POSTGRES_INTEGRATION=1 exclusivamente en el proceso de pruebas.

| Operación | SQL reales | Tiempo operación ms | EXPLAIN ejecución ms | Shared hit blocks |
| --- | ---: | ---: | ---: | ---: |
| menu_250 | 4 | 44.871 | 0.064 | 2 |
| cart_12 | 1 | 6.407 | 0.100 | 29 |
| kitchen_10 | 2 | 14.265 | 0.644 | 473 |
| kitchen_50 | 2 | 13.080 | 1.186 | 709 |
| notifications_page_50 | 2 | 8.773 | 0.035 | 3 |
| favorites_10 | 6 | 12.899 | 0.020 | 2 |
| favorites_50 | 6 | 17.818 | 0.030 | 2 |
| dashboard | 1 | 6.802 | 0.734 | 321 |
| checkout_12 | 23 | 47.591 | 0.038 | 2 |

EXPLAIN describe **la última lectura capturada**, no toda la operación ni sus
escrituras. Menú/favoritos: esa lectura es de adicionales vacíos (Sort/Index Scan,
0 filas); las aserciones separadas verifican los 250 productos y 10/50 favoritos.
Cart: Sort/Nested Loop/Bitmap e Index Scan, 12 filas. Kitchen: Limit, aggregates,
Memoize e Index Scan, 11/50 filas (limit+1 para detectar página siguiente).
Notifications: Limit/Index Scan, 51 filas para página50. Dashboard: Sort con CTE,
Append, Hash/Merge/Nested Loop y aggregates, 4 filas de proyección, 50 pagos y
PEN 2000.00 verificados; también se ejecutó su plan bound explícito.
Checkout: último SELECT owner-scoped por índice, 1 fila; se verifican 12 líneas
y PEN 240.00, sin presentar ese SELECT como plan de todos los INSERT.
No spills observados en estos planes; no se agregó ningún índice por intuición.

| Camino | Diseño revisado | Evidencia / presupuesto verificado |
| --- | --- | --- |
| Menú | Root + imágenes/presentaciones/addons/options por IN, sin query/producto | test catalog con 50 productos: 5 llamadas; PG repo 250 <=5, servicio añade 1 branch check |
| Cart GET | JOIN cart/items/options en un snapshot MVCC; sin repricing/locks | PG repo 12 líneas: 1 SQL |
| Checkout | Revalidación Catalog en batch; locks padre/idempotencia; writes por línea esperados | PG checkout 12 líneas captura SQL/tiempo, sin imponer conteo ficticio constante a writes |
| Order status | Lectura owner-scoped; snapshots e historia ordenada, sin llamadas a proveedor | Suites Orders/Notifications; carga/status HTTP real pendiente |
| Kitchen | JSON aggregates y scope en un statement; páginas 1..200 | PG service páginas 10/50: <=2 SQL, incluye permiso DB |
| Dashboard | Agregados pagos/refunds en DB, top10, periodos 1..31 días y <=100 branches | PG repo: 1 SQL; 50 órdenes CASH suman PEN 2000.00 |
| Notifications | High watermark + página limit+1, cursor estable por sequence | PG repo página50: 2 SQL |
| Favorites | Página limitada + Catalog batch, sin query/favorito | PG service 10/50 <=7 SQL, incluye branch check |
| SSE | Batch100, poll1s, heartbeat15s, revalidación15s, vida300s; sesión liberada antes de esperar | tests/modules/notifications/test_sse.py; proxies/clientes y carga real pendientes |

## Fixture reproducible y salida

tests/performance/test_postgresql_read_models.py comparte el guard/harness F12.
Dataset sintético: 2 branches, 250 productos con presentación, 50 órdenes con
checkout/pago cash/preparación reales, >=100 notificaciones, 50 favoritos y
12 líneas de cart distintas por notas. Se elimina solo su schema TEST propio.
No carga clientes reales ni usa la base normal.

```bash
pytest -m performance -s
```

Se captura before_cursor_execute solo durante cada operación, mide perf_counter
y emite JSON de nombre/conteo/elapsed_ms y EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
de la última lectura realmente ejecutada. Dashboard añade plan de su statement
bound exacto. No se imprimen parámetros, URL o credenciales. Son datos TEST.
CI -m integration -rP incluye esta prueba y conserva stdout en logs del job.

Este dataset es una regresión de N+1/proyección, **no** benchmark representativo
de tráfico distribuido o volumen productivo. No incluye coste TLS/HTTP/proxy/red.
Versión/CPU/RAM/cache/dataset/SQL counts/planes y tiempos observados arriba.
Falta repetir con tamaños/cargas acordados, adicionales no vacíos y cache fría,
y contrastar planes bajo carga representativa.
Revisar spills, seq scans selectivos, buffers y bloqueos; no exigir Index Scan
por defecto en tablas pequeñas. Solo proponer índices con evidencia y migration
justificada. Acordar SLO/RPO/RTO con el responsable, sin inferir cifras.

El resultado previo (1 skipped por URL ausente) es histórico y queda superado
por la ejecución real. RNF-03 permanece **PARTIAL**: este test aprueba los budgets
locales y no certifica rendimiento de HTTP, tráfico distribuido ni producción.

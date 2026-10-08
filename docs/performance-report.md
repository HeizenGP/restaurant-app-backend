# Rendimiento — metodología y estado real

**NOT EXECUTED contra PostgreSQL.** No TEST_DATABASE_URL disponible.
No p50/p95/p99, tiempos SQL, BUFFERS o EXPLAIN reales se inventan en este reporte.
No se agregó índice/migración por intuición ni SLA wall-clock en CI.

## Evidencia actual

Las pruebas unitarias/compiladas comprueban shape, batching y número de llamadas
al repositorio; no miden latencia, selectividad ni query planner real.

| Camino | Diseño revisado | Evidencia / presupuesto preparado |
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
Cuando exista PG: guardar versión/CPU/RAM/cache/dataset/SQL counts/planes y
tiempos observados, repetir con tamaños/cargas acordados y contrastar planes.
Revisar spills, seq scans selectivos, buffers y bloqueos; no exigir Index Scan
por defecto en tablas pequeñas. Solo proponer índices con evidencia y migration
justificada. Acordar SLO/RPO/RTO con el responsable, sin inferir cifras.

Resultado local final: pytest -m performance → 1 skipped, 2869 deselected in 1.28s.
Motivo: TEST_DATABASE_URL is not configured. RNF-03: PARTIAL.

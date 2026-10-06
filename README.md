# Restaurant App Backend

Base backend para una aplicación de gestión de pedidos de restaurante. La Fase 0
incluye configuración, API versionada, health/readiness, persistencia asíncrona,
Alembic, errores, logging y pruebas. Los módulos de negocio y autenticación se
implementarán en fases posteriores.

## Stack y requisitos

- Python 3.11 o superior; verificado localmente con Python 3.14.
- FastAPI y Uvicorn.
- PostgreSQL administrado externamente, accesible desde el backend.
- SQLAlchemy 2.0, AsyncEngine/AsyncSession y asyncpg.
- SQLModel para los futuros modelos de persistencia; complementa SQLAlchemy.
- Alembic, Pydantic y pydantic-settings.
- Pytest, HTTPX/HTTPX2 y Ruff.

`requirements.txt` declara dependencias directas con versiones verificadas. Los
extras `fastapi[standard]`, `uvicorn[standard]`, `SQLAlchemy[asyncio]` y
`pwdlib[argon2]` mantienen las dependencias transitivas necesarias. SQLModel
requiere SQLAlchemy <2.1. Las librerías de autenticación existentes se conservan,
pero esta fase no incorpora autenticación. HTTPX2 permite usar el TestClient de
la versión instalada de Starlette sin recurrir a su compatibilidad obsoleta con
HTTPX.

## Arquitectura

Vertical Slicing organiza las funcionalidades en `app/modules/<funcionalidad>`.
Cada slice aplica arquitectura hexagonal: presentación invoca aplicación;
aplicación depende de dominio y de puertos; infraestructura implementa esos
puertos. Dominio usa Python puro, sin dependencias HTTP ni ORM.

`health` es el primer slice: `HealthService` depende del puerto `DatabaseProbe`;
`SQLAlchemyDatabaseProbe` lo implementa ejecutando `SELECT 1`. La composición en
`app/lifespan.py` inyecta el adaptador. Presentación recibe el servicio mediante
una dependencia reemplazable en tests y no importa el adaptador SQLAlchemy.
Health no requiere entidades ni reglas de negocio, por lo que no se crea una
carpeta de dominio vacía. Los futuros slices añadirán su propio `domain/` cuando
lo necesiten.

```text
app/
├── main.py                         # create_app y registro de HTTP
├── lifespan.py                     # composición y ciclo de vida
├── shared/
│   ├── domain/exceptions.py         # errores de dominio, Python puro
│   ├── application/exceptions.py    # errores de casos de uso
│   └── infrastructure/
│       ├── config/settings.py
│       ├── database/               # engine, sesiones y dependencia
│       └── logging/config.py
├── modules/health/
│   ├── application/                # servicios, resultados y puerto
│   ├── infrastructure/             # adaptador PostgreSQL
│   └── presentation/               # schemas, dependencia y router
└── presentation/
    ├── errors.py                   # handlers y contrato común
    └── api/                        # composición y router v1
migrations/
├── env.py
├── script.py.mako
└── versions/                       # sin revisiones de negocio
tests/                              # tests sin PostgreSQL real
```

No hay repositorios, servicios o controladores genéricos. Los modelos futuros
pertenecerán a la infraestructura de su slice. `main.py` mantiene la factory y
el registro de routers, middlewares y handlers.

## Instalación y configuración

Desde la raíz del repositorio:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Si ya existe `.venv` o `.env`, reutilízalo. Edita `.env` con los datos del
PostgreSQL existente. `.env` está ignorado por Git; `.env.example` contiene solo
valores de ejemplo. No copies credenciales reales a archivos versionados.

| Variable | Uso |
| --- | --- |
| `APP_NAME`, `APP_VERSION` | Identidad del servicio y documentación OpenAPI |
| `APP_ENV` | `development`, `test`, `staging` o `production` |
| `APP_DEBUG` | Habilita logging DEBUG de la aplicación |
| `API_V1_PREFIX` | Prefijo de la API; por defecto `/api/v1` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Conexión PostgreSQL |
| `DATABASE_URL` | Alternativa a `DB_*`; tiene prioridad si se define |
| `DATABASE_TIMEOUT_SECONDS` | Límite de conexión, consulta y readiness; por defecto 5 s |
| `CORS_ORIGINS` | Orígenes HTTP(S) separados por comas |

Settings carga `.env` desde la raíz del proyecto; las variables del entorno
tienen prioridad. `DATABASE_URL` admite PostgreSQL y se normaliza al driver
`postgresql+asyncpg`. Al usar `DB_*`, SQLAlchemy construye la URL y maneja los
caracteres especiales de la contraseña. Si escribes una URL directamente,
codifica sus caracteres especiales conforme al formato URL.

CORS permite credenciales únicamente para orígenes explícitos; `*` se rechaza.
Incluso con `APP_DEBUG=true`, los errores HTTP internos nunca muestran trazas.

## Ejecución y endpoints

```bash
uvicorn app.main:app --reload
```

Documentación: `http://127.0.0.1:8000/docs`.

| Endpoint | Resultado |
| --- | --- |
| `GET /api/v1/health` | 200; liveness independiente de PostgreSQL |
| `GET /api/v1/health/ready` | 200 si `SELECT 1` funciona; 503 si PostgreSQL no está disponible |
| `GET /` | Respuesta original: `message=Restaurante API`, `status=running` |
| `GET /health` | Compatibilidad con el endpoint original: `status=ok` |

```bash
curl -i http://127.0.0.1:8000/api/v1/health
curl -i http://127.0.0.1:8000/api/v1/health/ready
```

Liveness devuelve:

```json
{"status": "ok", "service": "Restaurant App Backend", "version": "0.1.0"}
```

Readiness devuelve `{"status": "ready", "database": "connected"}` con HTTP 200.
Si falla la conexión o vence el timeout, devuelve HTTP 503:

```json
{"error": {"code": "DEPENDENCY_UNAVAILABLE", "message": "Database is unavailable"}}
```

Los errores de dominio devuelven 409; los de aplicación, 400; una dependencia
no disponible, 503; validación, 422; y los inesperados, 500. Los errores HTTP
esperados conservan su estado y headers. Todos usan el sobre `error`.
Validación informa ubicaciones y tipos sin repetir la entrada rechazada.
Logging registra inicio, cierre, fallos de DB y errores inesperados. Los logs
de fallo conservan tipos y ubicaciones de código sin imprimir valores de
excepciones, contraseñas, URLs de conexión ni cuerpos de solicitudes.

## PostgreSQL y sesiones

Este repositorio se conecta al PostgreSQL existente y no administra Docker.
Configura el host y el puerto ya publicados; no hace falta recrear contenedores.
La verificación local utilizó la base existente `restaurante_app`; el ejemplo
genérico usa `restaurant_db`, que debes reemplazar si corresponde.

Lifespan crea un único engine por aplicación y una fábrica central de sesiones.
Crear el engine no abre una conexión: el backend puede iniciar con PostgreSQL
apagado. Al cerrar, se ejecuta `await engine.dispose()`. `get_session` usa un
context manager y cierra cada sesión; los futuros casos de uso controlarán
`commit` y `rollback`. Readiness abre y cierra su propia sesión sin modificar
tablas. Ningún startup ejecuta `create_all` o migraciones automáticamente.

## Alembic

`migrations/env.py` obtiene la URL desde Settings y configura
`target_metadata = SQLModel.metadata`. Online usa asyncpg y `run_sync` para
Alembic; offline también está preparado. Cada ejecución CLI crea y cierra su
engine mediante la misma fábrica central.

```bash
alembic current
alembic heads
```

En Fase 0 no hay revisiones; es normal que ambos comandos no muestren una
revisión. Cuando se incorporen modelos en fases posteriores, importa sus
clases en `migrations/env.py` antes de obtener los metadatos y revisa el SQL:

```bash
alembic revision --autogenerate -m "create ..."
alembic upgrade head
alembic downgrade -1
```

Autogenerate filtra tablas existentes que aún no pertenecen a SQLModel para
evitar proponer su eliminación durante la adopción del esquema por slices.
La eliminación deliberada de una tabla requiere una migración explícita.
Esta fase no crea revisiones ni modifica el esquema de negocio existente.

## Tests y calidad

```bash
pytest
ruff check .
ruff format --check .
```

Los tests usan Settings aislado, dependency overrides y sesiones simuladas.
Cubren health, readiness en ambos estados, `SELECT 1`, timeout, cierre de
sesiones/engine, configuración, errores seguros y CORS. No requieren PostgreSQL
ni acceden a la base de desarrollo.

Para aplicar formato durante desarrollo: `ruff format .`.

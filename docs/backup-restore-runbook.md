# Backup y restauración segura

Estado: scripts y tests de seguridad preparados/probados; **RESTORE DRILL NOT
EXECUTED**. No pg_dump/pg_restore/psql disponibles localmente. RNF-12: PARTIAL.
RPO/RTO, frecuencia, retención, cifrado y ubicación remota deben acordarse;
no hay respaldo automático ni evidencia de recuperación productiva.

## Backup

Operador autorizado configura BACKUP_DATABASE_URL explícita (no fallback normal)
y un directorio fuera del repositorio. Usar secret store o entorno seguro, no
contraseña en comando/chat/log. Para servidor remoto configurar PGSSLMODE=verify-full
y PGSSLROOTCERT; el helper no acepta parámetros query en URL para evitar routing
oculto. Verificar cliente pg_dump compatible con versión del servidor.

```bash
bash scripts/backup_postgres.sh --output-dir /ruta/externa/aprobada
```

Wrapper con set -euo pipefail y argumentos quoted. Archivo custom de nombre UTC
único, creación exclusiva (no overwrite), permisos 0600; directorio nuevo 0700.
pg_dump --no-owner --no-acl --no-password, pg_restore --list y SHA-256 adjunto.
No guarda DSN/contraseña en argv; env libpq limpia service/hostaddr/options heredados.
Ante failure no imprime stderr/secretos. Un .dump parcial sin checksum no es
backup aprobado: poner en cuarentena/revisar con autorización; no se elimina
automáticamente. Cifrar/copiar a almacenamiento protegido y verificar acceso.

## Restore drill aislado

Crear por proceso externo autorizado una DB VACÍA marcada test/restore/staging,
distinta de la normal y nunca production/prod. No usar datos reales en tests CI.
Configurar RESTORE_DATABASE_URL explícita. El helper compara destino con normal,
incluyendo localhost/127.0.0.1/::1, y exige confirmación adicional.

```bash
bash scripts/restore_postgres.sh /ruta/externa/aprobada/archivo.dump --confirm-isolated-empty
```

Antes de escribir: SHA obligatorio/coherente, pg_restore --list y conteo de
relaciones de usuario en TODOS los schemas igual a cero. Si no está vacía:
STOP, sin drop/clean/create/reset. Restore --single-transaction --exit-on-error
--no-owner --no-acl; credenciales solo en env. No migrar/stamp automáticamente.
El dump debe ser de confianza: restaurar SQL ajeno puede ejecutar código;
validar procedencia y aislar privilegios/red.

## Evidencia posterior obligatoria

Verificar Alembic head, tablas/constraints/extensiones, recuentos críticos,
ledger/totales/reembolsos/historias/audit, idempotencia y lectura con otro proceso.
Arrancar una instancia aislada con providers deshabilitados para no enviar SMS,
push ni cobros reales. Readiness SELECT 1 no certifica integridad del backup.
Medir duración/pérdida respecto al último backup, comparar RPO/RTO acordados,
guardar evidencia sin PII y emitir aprobación humana.

No hay restore real ejecutado durante F12, no se afirma checksum/dump real.
Tests usan bytes sintéticos y subprocess dobles para validar controles:
flag obligatorio, URL normal/prod rechazada, destino no vacío rechazado,
checksum vacío/corrupto rechazado antes de DB, transacción única, errores
redactados, ruta fuera de repo y permisos de archivos.
Un cutover de recuperación productiva necesita aprobación y reconciliación
financiera externa; este helper deliberadamente no automatiza restores productivos.

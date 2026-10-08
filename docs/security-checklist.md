# Checklist de seguridad

La marca [x] identifica evidencia de código/tests; no certifica infraestructura.
Véanse [hallazgos y matrices](security-review.md).

- [x] Passwords Argon2id; hashes nunca como contraseña ni en respuestas.
- [x] JWT firma/algoritmo/issuer/audience/expiry/purpose; claims de rol sin autoridad.
- [x] Refresh hashed, rotación/revocación/replay y OTP HMAC/expiry/attempts/cooldown.
- [x] Staging/production rechaza debug, OTP debug, secretos débiles y DB placeholders.
- [x] CORS origins explícitos, sin wildcard; SSE/correlación compatibles.
- [x] 140 operaciones protegidas responden 401 sin bearer.
- [x] Roles/permisos/scope/ownership y branch extranjero probados en APIs TEST.
- [x] Asignación futura excluida también del catálogo global.
- [x] Schemas de respuesta/errores/logs app sin secretos de almacenamiento.
- [x] Uvicorn exception/lifespan logs redactados sin valores; instalación idempotente.
- [x] Headers HTTP/SSE/500; no buffering ni backdoors de pago/reembolso.
- [x] Audit append-only por contrato de aplicación, actor/scope/atomicidad probados.
- [x] Scripts sin contraseña en argv, restore solo aislado vacío, checksum obligatorio.
- [x] .env, backups y resultados locales ignorados; plantilla productiva inválida.
- [ ] Matrices/persistencia/locks/carreras ejecutadas en PostgreSQL TEST.
- [ ] CI real ejecutado y evidencias archivadas por el usuario.
- [ ] TLS/proxy sin query/body/credentials logs y permisos DB least-privilege.
- [ ] Proveedor OTP/payment/refund/push/fiscal real validado.
- [ ] Worker/scheduler supervisados y monitoreo/alertas operativos.
- [ ] Restore drill, RPO/RTO, retención y política de acceso a backups aprobados.
- [ ] Escaneo externo de vulnerabilidades/secretos y evaluación de privacidad/legal.

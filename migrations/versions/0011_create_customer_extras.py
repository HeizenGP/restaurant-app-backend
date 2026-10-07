"""Customer favorites, order reviews, fiscal requests and free promotional roulette.
Revision ID: 0011_customer_extras
Revises: 0010_admin
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_customer_extras"
down_revision = "0010_admin"
branch_labels = None
depends_on = None

TABLES = [
    "customer_favorites",
    "order_reviews",
    "fiscal_documents",
    "fiscal_document_attempts",
    "roulette_campaigns",
    "roulette_prizes",
    "roulette_participations",
    "roulette_spins",
    "customer_rewards",
]
PERMISSIONS = [
    "REVIEW_VIEW",
    "RECEIPT_VIEW",
    "RECEIPT_MANAGE",
    "PROMOTION_VIEW",
    "PROMOTION_MANAGE",
    "PROMOTION_REDEEM",
]


def upgrade():
    op.create_table(
        "customer_favorites",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "product_id", name="uq_customer_favorites_user_product"
        ),
    )
    op.create_index(
        "ix_customer_favorites_user_created",
        "customer_favorites",
        ["user_id", "created_at", "id"],
    )
    op.create_table(
        "order_reviews",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("order_id", name="uq_order_reviews_order"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_order_reviews_rating"),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment)<=1000", name="ck_order_reviews_comment"
        ),
    )
    op.create_index(
        "ix_order_reviews_branch_created",
        "order_reviews",
        ["branch_id", "created_at", "id"],
    )
    op.create_index(
        "ix_order_reviews_branch_rating",
        "order_reviews",
        ["branch_id", "rating", "created_at", "id"],
    )
    op.execute(
        "CREATE TRIGGER trg_phase11_order_reviews_updated BEFORE UPDATE ON "
        "order_reviews FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.create_table(
        "fiscal_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(8), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency_code",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'PEN'"),
        ),
        sa.Column("recipient_document_type", sa.String(16), nullable=True),
        sa.Column("recipient_document_number", sa.String(32), nullable=True),
        sa.Column("recipient_name", sa.String(180), nullable=True),
        sa.Column("recipient_address", sa.Text(), nullable=True),
        sa.Column("series", sa.String(32), nullable=True),
        sa.Column("number", sa.String(64), nullable=True),
        sa.Column("provider_code", sa.String(32), nullable=True),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("request_key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("order_id", name="uq_fiscal_documents_order"),
        sa.CheckConstraint(
            "document_type IN ('BOLETA','FACTURA')", name="ck_fiscal_documents_type"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','ISSUED','FAILED')",
            name="ck_fiscal_documents_status",
        ),
        sa.CheckConstraint(
            "amount>=0 AND amount<>'NaN'::numeric", name="ck_fiscal_documents_amount"
        ),
        sa.CheckConstraint("currency_code='PEN'", name="ck_fiscal_documents_currency"),
        sa.CheckConstraint(
            "(status='ISSUED')=(issued_at IS NOT NULL) AND (status<>'ISSUED' OR "
            "(series IS NOT NULL AND number IS NOT NULL AND provider_code IS "
            "NOT NULL AND provider_reference IS NOT NULL))",
            name="ck_fiscal_documents_issue",
        ),
        sa.CheckConstraint(
            "document_type<>'FACTURA' OR (recipient_document_type IS NOT NULL AND "
            "recipient_document_number IS NOT NULL AND recipient_document_type='RUC' "
            "AND "
            "recipient_document_number ~ '^[0-9]{11}$' AND recipient_name IS "
            "NOT NULL AND length(btrim(recipient_name))>0 AND recipient_address "
            "IS NOT NULL AND length(btrim(recipient_address))>0)",
            name="ck_fiscal_documents_factura",
        ),
        sa.CheckConstraint(
            "request_key_hash ~ '^[a-f0-9]{64}$' AND request_fingerprint ~ "
            "'^[a-f0-9]{64}$'",
            name="ck_fiscal_documents_hashes",
        ),
    )
    op.create_index(
        "ix_fiscal_documents_branch_status",
        "fiscal_documents",
        ["branch_id", "status", "requested_at", "id"],
    )
    op.create_index(
        "uq_fiscal_documents_number",
        "fiscal_documents",
        ["document_type", "series", "number"],
        unique=True,
        postgresql_where=sa.text("series IS NOT NULL AND number IS NOT NULL"),
    )
    op.create_index(
        "uq_fiscal_documents_reference",
        "fiscal_documents",
        ["provider_code", "provider_reference"],
        unique=True,
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_phase11_fiscal_documents_updated BEFORE UPDATE ON "
        "fiscal_documents FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.create_table(
        "fiscal_document_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "fiscal_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fiscal_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'CREATED'")
        ),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "fiscal_document_id",
            "idempotency_key",
            name="uq_fiscal_document_attempts_key",
        ),
        sa.CheckConstraint(
            "status IN ('CREATED','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_fiscal_document_attempts_status",
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED'))=(completed_at IS NOT NULL)",
            name="ck_fiscal_document_attempts_complete",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[a-f0-9]{64}$'", name="ck_fiscal_document_attempts_key"
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR (status='FAILED' AND failure_code ~ "
            "'^[A-Z][A-Z0-9_]{0,63}$')",
            name="ck_fiscal_document_attempts_failure",
        ),
    )
    op.create_index(
        "uq_fiscal_document_attempts_active",
        "fiscal_document_attempts",
        ["fiscal_document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('CREATED','PROCESSING')"),
    )
    op.create_index(
        "uq_fiscal_document_attempts_reference",
        "fiscal_document_attempts",
        ["provider_code", "provider_reference"],
        unique=True,
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )
    op.create_index(
        "ix_fiscal_document_attempts_recent",
        "fiscal_document_attempts",
        ["fiscal_document_id", "created_at", "id"],
    )
    op.execute(
        "CREATE TRIGGER trg_phase11_fiscal_document_attempts_updated BEFORE "
        "UPDATE ON fiscal_document_attempts FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.create_table(
        "roulette_campaigns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("terms_text", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "spin_cooldown_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("max_spins_per_customer_per_day", sa.Integer(), nullable=True),
        sa.Column("reward_validity_days", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "spin_cooldown_seconds>=0 AND (max_spins_per_customer_per_day IS "
            "NULL OR max_spins_per_customer_per_day>=1) AND "
            "(reward_validity_days IS NULL OR reward_validity_days>=1) AND "
            "version>=1",
            name="ck_roulette_campaigns_rules",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at>starts_at", name="ck_roulette_campaigns_window"
        ),
        sa.CheckConstraint(
            "length(btrim(terms_text)) BETWEEN 1 AND 10000 AND length(btrim(name))>0",
            name="ck_roulette_campaigns_terms",
        ),
    )
    op.create_index(
        "uq_roulette_campaigns_active_branch",
        "roulette_campaigns",
        ["branch_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_roulette_campaigns_branch_created",
        "roulette_campaigns",
        ["branch_id", "created_at", "id"],
    )
    op.execute(
        "CREATE TRIGGER trg_phase11_roulette_campaigns_updated BEFORE UPDATE ON "
        "roulette_campaigns FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.create_table(
        "roulette_prizes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(150), nullable=False),
        sa.Column("probability_bps", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("max_awards", sa.Integer(), nullable=True),
        sa.Column(
            "awarded_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "probability_bps BETWEEN 0 AND 10000", name="ck_roulette_prizes_probability"
        ),
        sa.CheckConstraint(
            "awarded_count>=0 AND (max_awards IS NULL OR (max_awards>=0 AND "
            "awarded_count<=max_awards))",
            name="ck_roulette_prizes_awards",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name))>0", name="ck_roulette_prizes_name"
        ),
    )
    op.create_index(
        "ix_roulette_prizes_campaign_sort",
        "roulette_prizes",
        ["campaign_id", "sort_order", "id"],
    )
    op.execute(
        "CREATE TRIGGER trg_phase11_roulette_prizes_updated BEFORE UPDATE ON "
        "roulette_prizes FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.create_table(
        "roulette_participations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("last_spin_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("day_key", sa.Date(), nullable=True),
        sa.Column(
            "spins_today", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "campaign_id", "customer_id", name="uq_roulette_participations_customer"
        ),
        sa.CheckConstraint("spins_today>=0", name="ck_roulette_participations_count"),
    )
    op.execute(
        "CREATE TRIGGER trg_phase11_roulette_participations_updated BEFORE "
        "UPDATE ON roulette_participations FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.create_table(
        "roulette_spins",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("random_draw", sa.SmallInteger(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column(
            "prize_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roulette_prizes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("campaign_version", sa.Integer(), nullable=False),
        sa.Column("configuration_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "spun_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "customer_id",
            "idempotency_key",
            name="uq_roulette_spins_campaign_key",
        ),
        sa.UniqueConstraint(
            "branch_id",
            "customer_id",
            "idempotency_key",
            name="uq_roulette_spins_branch_key",
        ),
        sa.CheckConstraint(
            "random_draw BETWEEN 0 AND 9999", name="ck_roulette_spins_draw"
        ),
        sa.CheckConstraint(
            "(outcome='WIN' AND prize_id IS NOT NULL) OR (outcome='NO_PRIZE' "
            "AND prize_id IS NULL)",
            name="ck_roulette_spins_outcome",
        ),
        sa.CheckConstraint("campaign_version>=1", name="ck_roulette_spins_version"),
        sa.CheckConstraint(
            "jsonb_typeof(configuration_snapshot)='object'",
            name="ck_roulette_spins_snapshot",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[a-f0-9]{64}$'", name="ck_roulette_spins_key"
        ),
    )
    op.create_index(
        "ix_roulette_spins_customer_time",
        "roulette_spins",
        ["customer_id", "spun_at", "id"],
    )
    op.create_table(
        "customer_rewards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "spin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roulette_spins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "prize_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roulette_prizes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_name_snapshot", sa.String(150), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'AVAILABLE'"),
        ),
        sa.Column(
            "awarded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "redeemed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("spin_id", name="uq_customer_rewards_spin"),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','REDEEMED','EXPIRED')",
            name="ck_customer_rewards_status",
        ),
        sa.CheckConstraint(
            "(status='REDEEMED' AND redeemed_at IS NOT NULL AND "
            "redeemed_by_user_id IS NOT NULL) OR (status IN "
            "('AVAILABLE','EXPIRED') AND redeemed_at IS NULL AND "
            "redeemed_by_user_id IS NULL)",
            name="ck_customer_rewards_redemption",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at>awarded_at",
            name="ck_customer_rewards_expiry",
        ),
    )
    op.create_index(
        "ix_customer_rewards_customer_status",
        "customer_rewards",
        ["customer_id", "status", "awarded_at", "id"],
    )
    op.execute(
        "CREATE TRIGGER trg_phase11_customer_rewards_updated BEFORE UPDATE ON "
        "customer_rewards FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )

    for code in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO permissions(code,name,description) VALUES "
                "(:code,:code,'Branch-scoped complementary functions') ON "
                "CONFLICT(code) DO NOTHING"
            ).bindparams(code=code)
        )
    codes = ",".join("'" + code + "'" for code in PERMISSIONS)
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id "
        "FROM roles r CROSS JOIN permissions p WHERE r.code='ADMIN' AND "
        "r.scope='BRANCH' "
        "AND p.code IN (" + codes + ") ON CONFLICT(role_id,permission_id) DO NOTHING"
    )
    op.execute("""
        CREATE FUNCTION restaurant_phase11_immutable_history() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Phase 11 history is immutable' USING ERRCODE='23514';
        END $$
    """)
    for table in ("order_reviews", "roulette_spins"):
        op.execute(
            f"CREATE TRIGGER trg_phase11_{table}_immutable BEFORE UPDATE OR "
            f"DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION "
            f"restaurant_phase11_immutable_history()"
        )
    op.execute("""
        CREATE FUNCTION restaurant_phase11_validate_review() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE valid boolean;
        BEGIN
            SELECT o.customer_id=NEW.customer_id AND o.branch_id=NEW.branch_id AND
                ((o.mode='LOCAL' AND o.status='SERVED') OR
                 (o.mode='PICKUP' AND o.status='PICKED_UP') OR
                 (o.mode='DELIVERY' AND o.status='DELIVERED'))
            INTO valid FROM orders o WHERE o.id=NEW.order_id FOR SHARE;
            IF valid IS DISTINCT FROM true THEN
                RAISE EXCEPTION 'Order is not reviewable by this owner' USING
                ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_phase11_review_order BEFORE INSERT ON order_reviews "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase11_validate_review()"
    )
    op.execute("""
        CREATE FUNCTION restaurant_phase11_fiscal_document_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE valid boolean;
        BEGIN
            IF TG_OP='INSERT' THEN
                SELECT o.customer_id=NEW.customer_id AND o.branch_id=NEW.branch_id AND
                    o.status<>'CANCELLED' AND o.payment_status='PAID' AND
                    p.status='PAID' AND p.amount=NEW.amount AND o.total=NEW.amount
                INTO valid FROM orders o JOIN payments p ON p.order_id=o.id
                WHERE o.id=NEW.order_id FOR SHARE OF o;
                IF valid IS DISTINCT FROM true OR NEW.status<>'PENDING' THEN
                    RAISE EXCEPTION 'Fiscal request requires a paid owned order' USING
                    ERRCODE='23514';
                END IF;
            ELSIF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Fiscal request history cannot be deleted' USING
                ERRCODE='23514';
            ELSE
                IF OLD.status='ISSUED' THEN
                    RAISE EXCEPTION 'Issued fiscal document is immutable' USING
                    ERRCODE='23514';
                END IF;
                IF (NEW.order_id,NEW.branch_id,NEW.customer_id,NEW.document_type,
                    NEW.amount,NEW.currency_code,NEW.recipient_document_type,
                    NEW.recipient_document_number,NEW.recipient_name,NEW.recipient_address,
                    NEW.request_key_hash,NEW.request_fingerprint,NEW.requested_at,NEW.created_at)
                    IS DISTINCT FROM
                    (OLD.order_id,OLD.branch_id,OLD.customer_id,OLD.document_type,
                    OLD.amount,OLD.currency_code,OLD.recipient_document_type,
                    OLD.recipient_document_number,OLD.recipient_name,OLD.recipient_address,
                    OLD.request_key_hash,OLD.request_fingerprint,OLD.requested_at,OLD.created_at)
                THEN
                    RAISE EXCEPTION 'Fiscal request snapshot is immutable' USING
                    ERRCODE='23514';
                END IF;
                IF NOT ((OLD.status IN ('PENDING','FAILED') AND
                NEW.status='PROCESSING') OR
                    (OLD.status='PROCESSING' AND NEW.status IN
                    ('PROCESSING','ISSUED','FAILED'))) THEN
                    RAISE EXCEPTION 'Invalid fiscal state transition' USING
                    ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_phase11_fiscal_guard BEFORE INSERT OR UPDATE OR DELETE ON "
        "fiscal_documents FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase11_fiscal_document_guard()"
    )
    op.execute("""
        CREATE FUNCTION restaurant_phase11_prize_total_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE total integer;
        BEGIN
            PERFORM id FROM roulette_campaigns WHERE id=NEW.campaign_id FOR UPDATE;
            SELECT coalesce(sum(probability_bps),0) INTO total FROM roulette_prizes
                WHERE campaign_id=NEW.campaign_id AND is_active AND id<>NEW.id;
            IF NEW.is_active THEN total:=total+NEW.probability_bps; END IF;
            IF total>10000 THEN
                RAISE EXCEPTION 'Roulette probability total exceeds 10000' USING
                ERRCODE='23514';
            END IF;
            IF TG_OP='UPDATE' THEN
                IF NEW.campaign_id<>OLD.campaign_id OR
                NEW.awarded_count<OLD.awarded_count THEN
                    RAISE EXCEPTION 'Prize history cannot be moved or erased' USING
                    ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_phase11_prize_total BEFORE INSERT OR UPDATE ON "
        "roulette_prizes FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase11_prize_total_guard()"
    )
    op.execute("""
        CREATE FUNCTION restaurant_phase11_campaign_activation_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE activating boolean;
        BEGIN
            activating:=NEW.is_active;
            IF TG_OP='UPDATE' THEN activating:=NEW.is_active AND NOT OLD.is_active;
            END IF;
            IF activating AND NOT EXISTS(SELECT 1 FROM roulette_prizes
                WHERE campaign_id=NEW.id AND is_active AND probability_bps>0) THEN
                RAISE EXCEPTION 'Activate only a configured roulette' USING
                ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_phase11_campaign_activation BEFORE INSERT OR UPDATE "
        "ON roulette_campaigns FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase11_campaign_activation_guard()"
    )


def downgrade():
    for table in TABLES:
        op.execute(f"""DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM {table}) THEN
                RAISE EXCEPTION 'Phase 11 data exists; downgrade requires an explicit
                preservation decision';
            END IF;
        END $$""")
    codes = ",".join("'" + code + "'" for code in PERMISSIONS)
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM "
        "permissions WHERE code IN (" + codes + "))"
    )
    op.execute("DELETE FROM permissions WHERE code IN (" + codes + ")")
    for table in reversed(TABLES):
        op.drop_table(table)
    for function in (
        "campaign_activation_guard",
        "prize_total_guard",
        "fiscal_document_guard",
        "validate_review",
        "immutable_history",
    ):
        op.execute(f"DROP FUNCTION restaurant_phase11_{function}()")

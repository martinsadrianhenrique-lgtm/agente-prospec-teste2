from sqlalchemy import MetaData, Table, Column, String, Text, Integer, Boolean, ForeignKey, UniqueConstraint, Index

metadata = MetaData()

users = Table("ef_users", metadata,
    Column("id", String(36), primary_key=True), Column("username", String(64), nullable=False, unique=True),
    Column("name", String(120), nullable=False), Column("role", String(20), nullable=False),
    Column("password_hash", Text, nullable=False), Column("active", Boolean, nullable=False, default=True),
    Column("must_change_password", Boolean, nullable=False, default=True), Column("created_at", String(32), nullable=False))
sessions = Table("ef_sessions", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", ForeignKey("ef_users.id"), nullable=False),
    Column("expires_at", String(32), nullable=False))
login_limits = Table("ef_login_limits", metadata,
    Column("username", String(64), primary_key=True), Column("failures", Integer, nullable=False), Column("locked_until", String(32)), Column("last_attempt", String(32), nullable=False))
leads = Table("ef_leads", metadata,
    Column("id", String(36), primary_key=True), Column("identity_key", String(64), nullable=False, unique=True),
    Column("company", String(250), nullable=False), Column("niche", String(120), nullable=False), Column("city", String(100), nullable=False),
    Column("address", Text, nullable=False, default=""), Column("website", Text, nullable=False, default=""), Column("instagram", Text, nullable=False, default=""),
    Column("maps_url", Text, nullable=False, default=""), Column("identity_verified", Boolean, nullable=False, default=False), Column("identity_source", Text, nullable=False, default=""),
    Column("identity_verified_at", String(32)), Column("identity_verified_by", ForeignKey("ef_users.id")),
    Column("owner_id", ForeignKey("ef_users.id")), Column("stage", String(40), nullable=False, default="Novo"),
    Column("campaign", String(160), nullable=False, default="Prospecção GMB"), Column("value_cents", Integer, nullable=False, default=50000), Column("blocked", Boolean, nullable=False, default=False),
    Column("block_reason", Text, nullable=False, default=""), Column("legacy_json", Text, nullable=False, default="{}"),
    Column("created_by", ForeignKey("ef_users.id"), nullable=False), Column("created_at", String(32), nullable=False), Column("updated_at", String(32), nullable=False),
    Column("version", Integer, nullable=False, default=1))
contacts = Table("ef_contacts", metadata,
    Column("id", String(36), primary_key=True), Column("lead_id", ForeignKey("ef_leads.id"), nullable=False),
    Column("raw", Text, nullable=False), Column("e164", String(20), nullable=False), Column("kind", String(20), nullable=False),
    Column("source_url", Text, nullable=False, default=""), Column("business_verified", Boolean, nullable=False, default=False),
    Column("whatsapp_verified", Boolean, nullable=False, default=False), Column("whatsapp_source", Text, nullable=False, default=""),
    Column("permission", Boolean, nullable=False, default=False), Column("permission_note", Text, nullable=False, default=""),
    Column("verified_at", String(32)), Column("verified_by", ForeignKey("ef_users.id")), Column("permission_at", String(32)),
    UniqueConstraint("lead_id", "e164", name="uq_ef_contact"))
observations = Table("ef_observations", metadata,
    Column("id", String(36), primary_key=True), Column("lead_id", ForeignKey("ef_leads.id"), nullable=False),
    Column("criterion", String(40), nullable=False), Column("points", Integer), Column("state", String(40), nullable=False),
    Column("fact", Text, nullable=False), Column("source_url", Text, nullable=False), Column("source_type", String(40), nullable=False),
    Column("observed_at", String(32), nullable=False), Column("author_id", ForeignKey("ef_users.id"), nullable=False), Column("created_at", String(32), nullable=False))
messages = Table("ef_messages", metadata,
    Column("id", String(36), primary_key=True), Column("lead_id", ForeignKey("ef_leads.id"), nullable=False), Column("contact_id", ForeignKey("ef_contacts.id"), nullable=False),
    Column("observation_id", ForeignKey("ef_observations.id")), Column("kind", String(30), nullable=False), Column("body", Text, nullable=False),
    Column("created_by", ForeignKey("ef_users.id"), nullable=False), Column("created_at", String(32), nullable=False),
    Column("sent_at", String(32)), Column("sent_by", ForeignKey("ef_users.id")), Column("task_id", String(36)))
interactions = Table("ef_interactions", metadata,
    Column("id", String(36), primary_key=True), Column("lead_id", ForeignKey("ef_leads.id"), nullable=False),
    Column("actor_id", ForeignKey("ef_users.id"), nullable=False), Column("actor_name", String(120), nullable=False),
    Column("kind", String(40), nullable=False), Column("channel", String(30), nullable=False), Column("direction", String(20), nullable=False),
    Column("body", Text, nullable=False), Column("previous_stage", String(40), nullable=False), Column("new_stage", String(40), nullable=False),
    Column("performed_at", String(32), nullable=False), Column("recorded_at", String(32), nullable=False),
    Column("message_id", ForeignKey("ef_messages.id")), Column("idempotency_key", String(100), nullable=False, unique=True))
tasks = Table("ef_tasks", metadata,
    Column("id", String(36), primary_key=True), Column("lead_id", ForeignKey("ef_leads.id"), nullable=False), Column("assigned_to", ForeignKey("ef_users.id"), nullable=False),
    Column("created_by", ForeignKey("ef_users.id"), nullable=False), Column("kind", String(30), nullable=False), Column("title", Text, nullable=False),
    Column("due_at", String(32), nullable=False), Column("state", String(20), nullable=False, default="Pendente"),
    Column("created_at", String(32), nullable=False), Column("completed_at", String(32)), Column("completed_by", ForeignKey("ef_users.id")),
    Column("origin_interaction", ForeignKey("ef_interactions.id")), Column("cancel_reason", Text, nullable=False, default=""))
suppressions = Table("ef_suppressions", metadata,
    Column("e164", String(20), primary_key=True), Column("reason", Text, nullable=False), Column("actor_id", ForeignKey("ef_users.id"), nullable=False), Column("created_at", String(32), nullable=False))
imports = Table("ef_imports", metadata,
    Column("id", String(36), primary_key=True), Column("file_hash", String(64), nullable=False, unique=True), Column("filename", Text, nullable=False),
    Column("actor_id", ForeignKey("ef_users.id"), nullable=False), Column("created_at", String(32), nullable=False), Column("summary_json", Text, nullable=False))
import_rows = Table("ef_import_rows", metadata,
    Column("id", String(36), primary_key=True), Column("import_id", ForeignKey("ef_imports.id"), nullable=False), Column("lead_id", ForeignKey("ef_leads.id")),
    Column("line_number", Integer, nullable=False), Column("raw_json", Text, nullable=False), Column("result", String(40), nullable=False), Column("notes", Text, nullable=False))
research = Table("ef_research", metadata,
    Column("id", String(36), primary_key=True), Column("actor_id", ForeignKey("ef_users.id"), nullable=False), Column("city", String(100), nullable=False),
    Column("niche", String(120), nullable=False), Column("source_url", Text, nullable=False), Column("notes", Text, nullable=False), Column("created_at", String(32), nullable=False))
settings = Table("ef_settings", metadata, Column("key", String(60), primary_key=True), Column("value", Text, nullable=False))
Index("ix_ef_contacts_phone", contacts.c.e164)
Index("ix_ef_tasks_due", tasks.c.state, tasks.c.due_at)
Index("ix_ef_interactions_lead", interactions.c.lead_id, interactions.c.performed_at)

contact_lists = Table("ef_contact_lists", metadata,
    Column("id", String(36), primary_key=True), Column("name", String(160), nullable=False),
    Column("description", Text, nullable=False, default=""), Column("city", String(100), nullable=False, default=""),
    Column("niche", String(120), nullable=False, default=""), Column("color", String(20), nullable=False, default="#7050C4"),
    Column("created_by", ForeignKey("ef_users.id"), nullable=False), Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False), Column("archived", Boolean, nullable=False, default=False),
    Column("version", Integer, nullable=False, default=1))
list_members = Table("ef_list_members", metadata,
    Column("list_id", ForeignKey("ef_contact_lists.id"), primary_key=True), Column("lead_id", ForeignKey("ef_leads.id"), primary_key=True),
    Column("added_by", ForeignKey("ef_users.id"), nullable=False), Column("added_at", String(32), nullable=False))
lead_details = Table("ef_lead_details", metadata,
    Column("lead_id", ForeignKey("ef_leads.id"), primary_key=True), Column("contact_person", String(160), nullable=False, default=""),
    Column("email", String(254), nullable=False, default=""), Column("tags", String(500), nullable=False, default=""),
    Column("updated_by", ForeignKey("ef_users.id"), nullable=False), Column("updated_at", String(32), nullable=False))
app_events = Table("ef_app_events", metadata,
    Column("id", String(36), primary_key=True), Column("actor_id", ForeignKey("ef_users.id"), nullable=False),
    Column("kind", String(50), nullable=False), Column("body", Text, nullable=False), Column("created_at", String(32), nullable=False))
Index("ix_ef_list_members_lead", list_members.c.lead_id)
BACKUP_TABLES = [users, leads, contacts, observations, messages, interactions, tasks, suppressions, imports, import_rows, research,
    contact_lists, list_members, lead_details, app_events, settings]

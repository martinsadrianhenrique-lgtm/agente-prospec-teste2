from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import timedelta
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import create_engine, select, insert, update, delete, and_, or_, func, event, case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

from . import schema as S
from .domain import (DomainError, ConflictError, STAGES, STOP_STAGES, CRITERIA, SOURCE_TYPES,
    OBS_STATES, stamp, now_utc, parse_time, clean_text, safe_url, normalized, current_evidence,
    score_evidence, next_business_day, whatsapp_url, is_optout)
from .security import hash_password, verify_password, token_hash, password_problem
from .importer import identity_key, phone_numbers


def uid():
    return str(uuid4())


def rows(conn, statement):
    return [dict(r) for r in conn.execute(statement).mappings()]


def one(conn, statement):
    result = conn.execute(statement).mappings().first()
    return dict(result) if result else None


class Store:
    def __init__(self, url: str, mode: str = "cloud"):
        if mode not in {"cloud", "local"}:
            raise DomainError("Modo deve ser cloud ou local.")
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        if not url.startswith(("postgresql+psycopg://", "sqlite:///")):
            raise DomainError("Configure a URL de um banco PostgreSQL ou use SQLite no modo local.")
        if mode == "cloud" and url.startswith("sqlite:"):
            raise DomainError("No modo online, configure PostgreSQL compartilhado em Secrets. SQLite fica reservado ao uso local.")
        opts = {"pool_pre_ping": True, "hide_parameters": True}
        if url.startswith("sqlite:"):
            opts["connect_args"] = {"check_same_thread": False, "timeout": 20}
            if url.endswith(":memory:"):
                opts["poolclass"] = StaticPool
            else:
                Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
        else:
            opts["connect_args"] = {"connect_timeout": 10}
            opts["pool_size"] = 3
            opts["max_overflow"] = 2
        self.engine = create_engine(url, **opts)
        self.mode = mode
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def sqlite_setup(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
        S.metadata.create_all(self.engine)
        self._dummy_hash = hash_password(secrets.token_urlsafe(32))
        with self.engine.begin() as conn:
            self._ignore(conn, S.settings, {"key": "schema_version", "value": "2.1.0"}, ["key"])
            current_version = conn.execute(select(S.settings.c.value).where(S.settings.c.key == "schema_version")).scalar_one()
            if current_version not in {"2.0.0", "2.1.0"}:
                raise DomainError("A versão do banco exige migração antes de abrir este aplicativo.")
            if current_version == "2.0.0":
                self._migrate_lists(conn)
                conn.execute(update(S.settings).where(S.settings.c.key == "schema_version").values(value="2.1.0"))

    def _migrate_lists(self, conn):
        for lead in rows(conn, select(S.leads)):
            name = lead["campaign"] or "Base anterior"
            list_id = str(uuid5(NAMESPACE_URL, "engage-flow:legacy-list:"+name))
            self._ignore(conn, S.contact_lists, {"id": list_id, "name": name, "description": "Lista recuperada da campanha da V2", "created_by": lead["created_by"],
                "created_at": stamp(), "updated_at": stamp()}, ["id"])
            self._ignore(conn, S.list_members, {"list_id": list_id, "lead_id": lead["id"], "added_by": lead["created_by"], "added_at": stamp()}, ["list_id", "lead_id"])

    def _ignore(self, conn, table, values, conflict_columns):
        builder = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        return conn.execute(builder(table).values(**values).on_conflict_do_nothing(index_elements=conflict_columns))

    def bootstrap(self, definitions: dict):
        with self.engine.begin() as conn:
            for username, data in definitions.items():
                username = username.lower().strip()
                if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,31}", username):
                    raise DomainError("Nome de usuário inválido na configuração inicial.")
                encoded = str(data.get("password_hash", ""))
                role = data.get("role", "operator")
                if role not in {"admin", "operator"} or not encoded.startswith("pbkdf2_sha256$"):
                    raise DomainError("Configure papéis e hashes de senha válidos em bootstrap_users.")
                self._ignore(conn, S.users, {"id": uid(), "username": username, "name": clean_text(data.get("name", username), 120),
                    "role": role, "password_hash": encoded, "active": True, "must_change_password": bool(data.get("must_change_password", True)), "created_at": stamp()}, ["username"])
            if not conn.execute(select(func.count()).select_from(S.users).where(S.users.c.role == "admin", S.users.c.active.is_(True))).scalar_one():
                raise DomainError("Configure o usuário administrador em bootstrap_users.adrian.")

    def login(self, username: str, password: str) -> str:
        username = clean_text(username, 64).lower()
        if not username or len(password) > 1024:
            raise DomainError("Usuário ou senha inválidos.")
        token = None
        with self.engine.begin() as conn:
            self._ignore(conn, S.login_limits, {"username": username, "failures": 0, "last_attempt": stamp()}, ["username"])
            limit = one(conn, select(S.login_limits).where(S.login_limits.c.username == username).with_for_update())
            if limit["locked_until"] and parse_time(limit["locked_until"]) > now_utc():
                raise DomainError("Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.")
            if limit["locked_until"] or parse_time(limit["last_attempt"]) < now_utc() - timedelta(minutes=15):
                conn.execute(update(S.login_limits).where(S.login_limits.c.username == username).values(failures=0, locked_until=None))
            user = one(conn, select(S.users).where(S.users.c.username == username))
            valid = verify_password(password, user["password_hash"] if user else self._dummy_hash)
            if valid and user and user["active"]:
                conn.execute(update(S.login_limits).where(S.login_limits.c.username == username).values(failures=0, locked_until=None, last_attempt=stamp()))
                token = self._session(conn, user["id"])
            else:
                conn.execute(update(S.login_limits).where(S.login_limits.c.username == username).values(
                    failures=S.login_limits.c.failures + 1, last_attempt=stamp(),
                    locked_until=case((S.login_limits.c.failures + 1 >= 8, stamp(now_utc()+timedelta(minutes=15))), else_=None)))
        if not token:
            raise DomainError("Usuário ou senha inválidos.")
        return token

    def _session(self, conn, user_id):
        conn.execute(delete(S.sessions).where(S.sessions.c.expires_at <= stamp()))
        token = secrets.token_urlsafe(40)
        conn.execute(insert(S.sessions).values(id=token_hash(token), user_id=user_id, expires_at=stamp(now_utc()+timedelta(hours=8))))
        return token

    def _actor(self, conn, token, admin=False, allow_change=False):
        user = one(conn, select(S.users).join(S.sessions, S.sessions.c.user_id == S.users.c.id).where(
            S.sessions.c.id == token_hash(token or ""), S.sessions.c.expires_at > stamp(), S.users.c.active.is_(True)))
        if not user:
            raise DomainError("Sessão expirada. Entre novamente.")
        if user["must_change_password"] and not allow_change:
            raise DomainError("Defina sua nova senha para continuar.")
        if admin and user["role"] != "admin":
            raise DomainError("Esta ação é exclusiva do administrador.")
        return user

    def whoami(self, token):
        with self.engine.connect() as conn:
            user = self._actor(conn, token, allow_change=True)
            return {k: v for k, v in user.items() if k != "password_hash"}

    def logout(self, token):
        with self.engine.begin() as conn:
            conn.execute(delete(S.sessions).where(S.sessions.c.id == token_hash(token or "")))

    def change_password(self, token, new_password, old_password=""):
        if problem := password_problem(new_password):
            raise DomainError(problem)
        with self.engine.begin() as conn:
            actor = self._actor(conn, token, allow_change=True)
            if not actor["must_change_password"] and not verify_password(old_password, actor["password_hash"]):
                raise DomainError("A senha atual está incorreta.")
            if verify_password(new_password, actor["password_hash"]):
                raise DomainError("Escolha uma senha diferente da senha inicial/atual.")
            conn.execute(update(S.users).where(S.users.c.id == actor["id"]).values(password_hash=hash_password(new_password), must_change_password=False))
            conn.execute(delete(S.sessions).where(S.sessions.c.user_id == actor["id"]))
            return self._session(conn, actor["id"])

    def set_user(self, token, user_id, active, new_password=""):
        with self.engine.begin() as conn:
            actor = self._actor(conn, token, admin=True)
            user = one(conn, select(S.users).where(S.users.c.id == user_id))
            if not user:
                raise DomainError("Usuário não encontrado.")
            if actor["id"] == user_id:
                raise DomainError("Use Minha conta para alterar sua própria senha.")
            values = {"active": bool(active)}
            if new_password:
                if problem := password_problem(new_password):
                    raise DomainError(problem)
                values.update(password_hash=hash_password(new_password), must_change_password=True)
            conn.execute(update(S.users).where(S.users.c.id == user_id).values(**values))
            conn.execute(delete(S.sessions).where(S.sessions.c.user_id == user_id))

    def _lead(self, conn, lead_id):
        lead = one(conn, select(S.leads).where(S.leads.c.id == lead_id))
        if not lead:
            raise DomainError("Lead não encontrado.")
        return lead

    def _write_lead(self, conn, lead_id, actor, expected_version=None, allow_unassigned=False):
        lead = self._lead(conn, lead_id)
        if actor["role"] != "admin" and lead["owner_id"] != actor["id"] and not (allow_unassigned and lead["owner_id"] is None):
            raise DomainError("Assuma este lead ou peça ao administrador para transferi-lo antes de editar.")
        version = expected_version if expected_version is not None else lead["version"]
        changed = conn.execute(update(S.leads).where(S.leads.c.id == lead_id, S.leads.c.version == version).values(version=S.leads.c.version+1, updated_at=stamp()))
        if changed.rowcount != 1:
            raise ConflictError("Este lead foi atualizado por outra pessoa. Atualize a página e confira o histórico antes de salvar.")
        return lead

    def _event(self, conn, actor, lead, kind, body, channel="Sistema", direction="internal", stage=None, performed_at=None, message_id=None, key=None):
        value = performed_at or stamp()
        if parse_time(value) > now_utc() + timedelta(minutes=5):
            raise DomainError("A data do contato não pode estar no futuro.")
        event_id = uid()
        conn.execute(insert(S.interactions).values(id=event_id, lead_id=lead["id"], actor_id=actor["id"], actor_name=actor["name"],
            kind=kind, body=clean_text(body, 20000), channel=channel, direction=direction, previous_stage=lead["stage"], new_stage=stage or lead["stage"],
            performed_at=value, recorded_at=stamp(), message_id=message_id, idempotency_key=key or uid()))
        return event_id

    def assign(self, token, lead_id, owner_id, expected_version):
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version, allow_unassigned=True)
            if actor["role"] != "admin" and owner_id != actor["id"]:
                raise DomainError("Somente o administrador pode transferir para outra pessoa.")
            owner = one(conn, select(S.users).where(S.users.c.id == owner_id, S.users.c.active.is_(True)))
            if not owner:
                raise DomainError("Escolha um usuário ativo.")
            conn.execute(update(S.leads).where(S.leads.c.id == lead_id).values(owner_id=owner_id))
            conn.execute(update(S.tasks).where(S.tasks.c.lead_id == lead_id, S.tasks.c.state == "Pendente").values(assigned_to=owner_id))
            self._event(conn, actor, lead, "Responsável alterado", f"Responsável definido: {owner['name']}. O histórico anterior foi preservado.")

    def _add_candidate(self, conn, actor, row, campaign):
        existing = one(conn, select(S.leads).where(S.leads.c.identity_key == row["key"]))
        if existing:
            return existing["id"], False
        lead_id = uid()
        conn.execute(insert(S.leads).values(id=lead_id, identity_key=row["key"], company=row["company"][:250], niche=row["niche"][:120], city=row["city"][:100],
            address=row["address"], website=row["website"], instagram=row["instagram"], maps_url=row["maps_url"], legacy_json=row["raw_json"],
            campaign=clean_text(campaign or "Prospecção GMB",160), created_by=actor["id"], created_at=stamp(), updated_at=stamp()))
        for p in row["phones"]:
            conn.execute(insert(S.contacts).values(id=uid(), lead_id=lead_id, **p, source_url=row["source_url"]))
        return lead_id, True

    def import_records(self, token, prepared, filename, file_bytes, campaign="Prospecção GMB", list_id=None):
        digest = hashlib.sha256(file_bytes + b"\0" + json.dumps(prepared, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with self.engine.begin() as conn:
            actor = self._actor(conn, token, admin=not bool(list_id))
            if list_id:
                self._list(conn, list_id, actor, write=True)
            previous = one(conn, select(S.imports).where(S.imports.c.file_hash == digest))
            if previous:
                if list_id:
                    for lead_id in conn.execute(select(S.import_rows.c.lead_id).where(S.import_rows.c.import_id == previous["id"], S.import_rows.c.lead_id.is_not(None))).scalars():
                        self._join_list(conn, list_id, lead_id, actor)
                return {**json.loads(previous["summary_json"]), "already_imported": True}
            import_id = uid()
            summary = {"new": 0, "existing": 0, "rejected": 0, "without_phone": 0, "phone_errors": 0}
            conn.execute(insert(S.imports).values(id=import_id, file_hash=digest, filename=clean_text(filename), actor_id=actor["id"], created_at=stamp(), summary_json="{}"))
            for row in prepared:
                notes = []
                lead_id = None
                if not row["valid"]:
                    result = "Rejeitado"
                    summary["rejected"] += 1
                    notes.append("Empresa, cidade ou nicho ausente.")
                else:
                    lead_id, created = self._add_candidate(conn, actor, row, campaign)
                    if created and actor["role"] != "admin":
                        conn.execute(update(S.leads).where(S.leads.c.id == lead_id).values(owner_id=actor["id"]))
                    if list_id:
                        self._join_list(conn, list_id, lead_id, actor)
                    result = "Novo" if created else "Já existente"
                    summary["new" if created else "existing"] += 1
                    if not row["phones"]:
                        summary["without_phone"] += 1
                        notes.append("Sem telefone válido; permanece na pesquisa.")
                    if row["phone_errors"]:
                        summary["phone_errors"] += 1
                        notes.append("Formato de telefone requer revisão.")
                conn.execute(insert(S.import_rows).values(id=uid(), import_id=import_id, lead_id=lead_id, line_number=row["line"], raw_json=row["raw_json"], result=result, notes=" ".join(notes)))
            conn.execute(update(S.imports).where(S.imports.c.id == import_id).values(summary_json=json.dumps(summary)))
            return summary

    def create_lead(self, token, row, campaign="Prospecção GMB", list_id=None):
        if not row["valid"]:
            raise DomainError("Preencha empresa, nicho e cidade.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            if list_id:
                self._list(conn, list_id, actor, write=True)
            lead_id, created = self._add_candidate(conn, actor, row, campaign)
            if created:
                conn.execute(update(S.leads).where(S.leads.c.id == lead_id).values(owner_id=actor["id"]))
            if list_id:
                self._join_list(conn, list_id, lead_id, actor)
            return lead_id, created

    def verify_identity(self, token, lead_id, source, maps_url, expected_version):
        source = safe_url(source)
        if not source or ("/maps/search" in source and "query_place_id=" not in source):
            raise DomainError("Informe o perfil selecionado ou uma página oficial da empresa, não uma busca genérica.")
        maps_url = safe_url(maps_url) if maps_url else ""
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            conn.execute(update(S.leads).where(S.leads.c.id == lead_id).values(identity_verified=True, identity_source=source, maps_url=maps_url or lead["maps_url"], identity_verified_at=stamp(), identity_verified_by=actor["id"]))
            self._event(conn, actor, lead, "Identidade conferida", f"Empresa/estabelecimento conferido em {source}")

    def add_contact(self, token, lead_id, raw, source, expected_version):
        found, errors = phone_numbers(raw)
        if errors or not found:
            raise DomainError("Confira o número e o DDD. Separe números diferentes com /.")
        source = safe_url(source)
        if not source:
            raise DomainError("Registre a fonte comercial pública do telefone.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            for phone in found:
                self._ignore(conn, S.contacts, {"id": uid(), "lead_id": lead_id, **phone, "source_url": source}, ["lead_id", "e164"])
            self._event(conn, actor, lead, "Contato cadastrado", f"{len(found)} número(s) registrado(s) com fonte pública; aguardam validação.")

    def verify_contact(self, token, contact_id, business, source, whatsapp, whatsapp_source, permission, permission_note, expected_version):
        source = safe_url(source) if source else ""
        if business and not source:
            raise DomainError("Informe a fonte do vínculo entre o número e a empresa.")
        if whatsapp and (not business or not whatsapp_source.strip()):
            raise DomainError("Confirme o vínculo comercial e registre a evidência de WhatsApp.")
        if permission and (not whatsapp or not permission_note.strip()):
            raise DomainError("Registre como e quando a empresa autorizou o contato por WhatsApp.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            contact = one(conn, select(S.contacts).where(S.contacts.c.id == contact_id))
            if not contact:
                raise DomainError("Contato não encontrado.")
            lead = self._write_lead(conn, contact["lead_id"], actor, expected_version)
            if permission and self._blocked(conn, lead, contact):
                raise DomainError("Este contato está bloqueado. A validação não pode remover uma recusa.")
            conn.execute(update(S.contacts).where(S.contacts.c.id == contact_id).values(business_verified=bool(business), source_url=source,
                whatsapp_verified=bool(whatsapp), whatsapp_source=clean_text(whatsapp_source), permission=bool(permission),
                permission_note=clean_text(permission_note), permission_at=stamp() if permission else None, verified_at=stamp(), verified_by=actor["id"]))
            if not permission:
                self._cancel_followups(conn, lead["id"], "Permissão de contato ausente/revogada")
            self._event(conn, actor, lead, "Canal e permissão revisados", f"Número {contact['e164']}. Comercial: {bool(business)}; WhatsApp: {bool(whatsapp)}; permissão: {bool(permission)}. {permission_note}")

    def add_observation(self, token, lead_id, criterion, points, state, fact, source_url, source_type, observed_at, expected_version):
        if criterion not in {*CRITERIA, "fato"} or state not in OBS_STATES or source_type not in SOURCE_TYPES:
            raise DomainError("Selecione um critério e estados válidos.")
        if criterion in CRITERIA and points not in CRITERIA[criterion][1] and points is not None:
            raise DomainError("Pontuação fora das regras do critério.")
        if source_type == "Diretório" and state == "Verificado":
            raise DomainError("Diretórios ficam como evidência a validar. Confirme a informação em fonte direta.")
        source_url = safe_url(source_url) if source_url else ""
        if state == "Verificado" and (not fact.strip() or not source_url):
            raise DomainError("Um fato verificado precisa de descrição e fonte.")
        if parse_time(observed_at) > now_utc() + timedelta(minutes=5):
            raise DomainError("A data da observação não pode estar no futuro.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            obs_id = uid()
            conn.execute(insert(S.observations).values(id=obs_id, lead_id=lead_id, criterion=criterion, points=points if state == "Verificado" else None,
                state=state, fact=clean_text(fact), source_url=source_url, source_type=source_type, observed_at=observed_at, author_id=actor["id"], created_at=stamp()))
            self._event(conn, actor, lead, "Evidência registrada", f"{criterion}: {state}. {fact}")
            return obs_id

    def _blocked(self, conn, lead, contact=None):
        if lead["blocked"]:
            return True
        if contact:
            return bool(conn.execute(select(S.suppressions.c.e164).where(S.suppressions.c.e164 == contact["e164"])).first())
        return bool(conn.execute(select(S.contacts.c.id).join(S.suppressions, S.contacts.c.e164 == S.suppressions.c.e164).where(S.contacts.c.lead_id == lead["id"])).first())

    def _cancel_followups(self, conn, lead_id, reason, all_tasks=False):
        query = update(S.tasks).where(S.tasks.c.lead_id == lead_id, S.tasks.c.state == "Pendente")
        if not all_tasks:
            query = query.where(S.tasks.c.kind.in_(["followup1", "followup2", "close_sequence"]))
        conn.execute(query.values(state="Cancelada", cancel_reason=reason))

    def _block(self, conn, actor, lead, reason):
        conn.execute(update(S.leads).where(S.leads.c.id == lead["id"]).values(blocked=True, block_reason=reason, stage="Perdido"))
        phones = conn.execute(select(S.contacts.c.e164).where(S.contacts.c.lead_id == lead["id"])).scalars().all()
        for phone in phones:
            self._ignore(conn, S.suppressions, {"e164": phone, "reason": reason, "actor_id": actor["id"], "created_at": stamp()}, ["e164"])
        conn.execute(update(S.contacts).where(S.contacts.c.lead_id == lead["id"]).values(permission=False))
        self._cancel_followups(conn, lead["id"], reason, all_tasks=True)
        if phones:
            affected = conn.execute(select(S.contacts.c.lead_id).where(S.contacts.c.e164.in_(phones))).scalars().all()
            for other in set(affected):
                self._cancel_followups(conn, other, "Número compartilhado com contato bloqueado")

    def block_lead(self, token, lead_id, reason, expected_version):
        if not reason.strip():
            raise DomainError("Registre o motivo do bloqueio.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            self._block(conn, actor, lead, reason)
            self._event(conn, actor, lead, "Não abordar novamente", reason, stage="Perdido")

    def log_research(self, token, city, niche, source_url, notes):
        url = safe_url(source_url)
        if not city.strip() or not niche.strip() or not url:
            raise DomainError("Preencha cidade, nicho e fonte consultada.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            conn.execute(insert(S.research).values(id=uid(), actor_id=actor["id"], city=clean_text(city,100), niche=clean_text(niche,120), source_url=url, notes=clean_text(notes), created_at=stamp()))

    def snapshot(self, token):
        with self.engine.connect() as conn:
            self._actor(conn, token)
            result = {name: rows(conn, select(table)) for name, table in [("leads",S.leads),("contacts",S.contacts),("observations",S.observations),
                ("messages",S.messages),("interactions",S.interactions),("tasks",S.tasks),("suppressions",S.suppressions),("imports",S.imports),("research",S.research),
                ("lists",S.contact_lists),("list_members",S.list_members),("lead_details",S.lead_details),("app_events",S.app_events)]}
            result["users"] = rows(conn, select(S.users.c.id, S.users.c.username, S.users.c.name, S.users.c.role, S.users.c.active))
            return result

    def _eligible(self, conn, lead, contact, observation=None):
        problems = []
        if self._blocked(conn, lead, contact):
            problems.append("Não abordar novamente")
        if not lead["identity_verified"] or not lead["identity_verified_at"] or parse_time(lead["identity_verified_at"]) < now_utc()-timedelta(days=30):
            problems.append("Identidade da empresa precisa de conferência")
        if not contact["business_verified"] or not contact["verified_at"] or parse_time(contact["verified_at"]) < now_utc()-timedelta(days=30):
            problems.append("Vínculo comercial do telefone precisa de conferência")
        if not contact["whatsapp_verified"]:
            problems.append("WhatsApp não confirmado")
        if not contact["permission"]:
            problems.append("Permissão de contato não registrada")
        if observation is not None and not current_evidence(observation):
            problems.append("A observação da mensagem precisa de revisão")
        if problems:
            raise DomainError(" • ".join(problems))

    def _new_task(self, conn, actor, lead, kind, title, due_at, origin=None):
        due_at = stamp(parse_time(due_at))
        task_id = uid()
        conn.execute(insert(S.tasks).values(id=task_id, lead_id=lead["id"], assigned_to=lead["owner_id"] or actor["id"],
            created_by=actor["id"], kind=kind, title=clean_text(title), due_at=due_at, state="Pendente", created_at=stamp(), origin_interaction=origin))
        return task_id

    def prepare_message(self, token, lead_id, contact_id, observation_id, kind="initial", task_id=None, expected_version=None):
        if kind not in {"initial", "followup1", "followup2", "reply"}:
            raise DomainError("Tipo de mensagem inválido.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            contact = one(conn, select(S.contacts).where(S.contacts.c.id == contact_id, S.contacts.c.lead_id == lead_id))
            observation = one(conn, select(S.observations).where(S.observations.c.id == observation_id, S.observations.c.lead_id == lead_id)) if observation_id else None
            if not contact:
                raise DomainError("Selecione um contato do lead.")
            if (kind != "reply" or observation_id) and not observation:
                raise DomainError("Selecione uma observação verificada para personalizar a mensagem.")
            self._eligible(conn, lead, contact, observation)
            task = None
            if kind in {"followup1", "followup2"}:
                task = one(conn, select(S.tasks).where(S.tasks.c.id == task_id, S.tasks.c.lead_id == lead_id, S.tasks.c.kind == kind, S.tasks.c.state == "Pendente"))
                if not task or parse_time(task["due_at"]) > now_utc():
                    raise DomainError("Este follow-up ainda não está pendente/vencido.")
                if lead["stage"] != "Contatado":
                    raise DomainError("A sequência foi interrompida pela evolução do atendimento.")
            if kind == "initial" and conn.execute(select(S.messages.c.id).where(S.messages.c.lead_id == lead_id, S.messages.c.sent_at.is_not(None))).first():
                raise DomainError("Já existe envio registrado. Use a próxima tarefa ou uma resposta à conversa.")
            if kind == "initial" and lead["stage"] not in {"Novo", "Contatado"}:
                raise DomainError("A etapa atual não permite uma abordagem inicial.")
            if kind == "reply" and lead["stage"] not in {"Em conversa", "Interessado", "Reunião marcada", "Proposta enviada", "Ganho"}:
                raise DomainError("Registre a resposta recebida antes de preparar uma resposta à conversa.")
            fact = observation["fact"] if observation else ""
            if kind == "initial":
                body = f"Oi, tudo bem? Sou {actor['name']}, da Engage Flow. Conforme autorizado, conferi as informações da {lead['company']} e notei: {fact}\n\nPosso te mostrar uma sugestão para esse ponto?"
            elif kind == "followup1":
                body = f"Oi, tudo bem? Aqui é {actor['name']}, da Engage Flow. Conseguiu ver o ponto que comentei sobre a {lead['company']}? Se quiser, explico a sugestão."
            elif kind == "followup2":
                body = f"Oi, tudo bem? Aqui é {actor['name']}, da Engage Flow. Vou encerrar o acompanhamento por aqui. Se quiser retomar a análise da {lead['company']}, fico à disposição."
            else:
                body = f"Oi! Aqui é {actor['name']}, da Engage Flow. "
            message_id = uid()
            conn.execute(insert(S.messages).values(id=message_id, lead_id=lead_id, contact_id=contact_id, observation_id=observation_id or None,
                kind=kind, body=body, created_by=actor["id"], created_at=stamp(), task_id=task_id or None))
            return message_id

    def revise_message(self, token, message_id, body, expected_version):
        if not 5 <= len(body.strip()) <= 4000:
            raise DomainError("A mensagem deve ter entre 5 e 4.000 caracteres.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            message = one(conn, select(S.messages).where(S.messages.c.id == message_id))
            if not message or message["sent_at"]:
                raise DomainError("A mensagem não existe ou já foi enviada.")
            lead = self._write_lead(conn, message["lead_id"], actor, expected_version)
            if self._blocked(conn, lead):
                raise DomainError("Lead bloqueado para abordagem.")
            conn.execute(update(S.messages).where(S.messages.c.id == message_id).values(body=body.strip()))
            self._event(conn, actor, lead, "Mensagem revisada", body)

    def message_link(self, token, message_id):
        with self.engine.connect() as conn:
            actor = self._actor(conn, token)
            message = one(conn, select(S.messages).where(S.messages.c.id == message_id))
            if not message or message["sent_at"]:
                raise DomainError("Selecione um rascunho ainda não enviado.")
            lead = self._lead(conn, message["lead_id"])
            if actor["role"] != "admin" and lead["owner_id"] != actor["id"]:
                raise DomainError("O lead está atribuído a outro usuário.")
            contact = one(conn, select(S.contacts).where(S.contacts.c.id == message["contact_id"]))
            observation = one(conn, select(S.observations).where(S.observations.c.id == message["observation_id"])) if message["observation_id"] else None
            self._eligible(conn, lead, contact, observation)
            self._check_message_stage(conn, lead, message)
            if message["kind"].startswith("followup"):
                task = one(conn, select(S.tasks).where(S.tasks.c.id == message["task_id"]))
                if not task or task["state"] != "Pendente" or task["due_at"] > stamp() or lead["stage"] != "Contatado":
                    raise DomainError("O follow-up não está mais disponível. Confira a conversa.")
            return whatsapp_url(contact["e164"], message["body"])

    def _check_message_stage(self, conn, lead, message):
        if message["kind"] == "initial":
            other_sent = conn.execute(select(S.messages.c.id).where(S.messages.c.lead_id == lead["id"], S.messages.c.sent_at.is_not(None))).first()
            if other_sent or lead["stage"] not in {"Novo", "Contatado"}:
                raise DomainError("A abordagem inicial não está mais disponível. Confira a conversa.")
        if message["kind"] == "reply" and lead["stage"] not in {"Em conversa", "Interessado", "Reunião marcada", "Proposta enviada", "Ganho"}:
            raise DomainError("A etapa atual não permite continuar essa conversa.")

    def mark_sent(self, token, message_id, expected_version, conversation_checked=False, performed_at=None):
        performed_at = stamp(parse_time(performed_at)) if performed_at else stamp()
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            message = one(conn, select(S.messages).where(S.messages.c.id == message_id))
            if not message:
                raise DomainError("Mensagem não encontrada.")
            existing = one(conn, select(S.interactions).where(S.interactions.c.idempotency_key == "send:"+message_id))
            if existing:
                return existing["id"]
            lead = self._write_lead(conn, message["lead_id"], actor, expected_version)
            contact = one(conn, select(S.contacts).where(S.contacts.c.id == message["contact_id"]))
            observation = one(conn, select(S.observations).where(S.observations.c.id == message["observation_id"])) if message["observation_id"] else None
            self._eligible(conn, lead, contact, observation)
            self._check_message_stage(conn, lead, message)
            if message["kind"].startswith("followup"):
                task = one(conn, select(S.tasks).where(S.tasks.c.id == message["task_id"]))
                if not task or task["state"] != "Pendente" or task["kind"] != message["kind"] or task["due_at"] > performed_at or lead["stage"] != "Contatado":
                    raise DomainError("O follow-up foi cancelado, já realizado ou ainda não venceu.")
                if not conversation_checked:
                    raise DomainError("Confira se houve resposta ou recusa antes de continuar.")
                conn.execute(update(S.tasks).where(S.tasks.c.id == task["id"]).values(state="Concluída", completed_at=stamp(), completed_by=actor["id"]))
            if message["kind"] == "initial" and conn.execute(select(S.messages.c.id).where(S.messages.c.lead_id == lead["id"], S.messages.c.sent_at.is_not(None))).first():
                raise DomainError("Outro envio já foi registrado para este lead. Atualize a conversa.")
            stage = "Contatado" if message["kind"] == "initial" and lead["stage"] == "Novo" else lead["stage"]
            conn.execute(update(S.messages).where(S.messages.c.id == message_id).values(sent_at=performed_at, sent_by=actor["id"]))
            conn.execute(update(S.leads).where(S.leads.c.id == lead["id"]).values(stage=stage))
            event_id = self._event(conn, actor, lead, "Envio manual registrado", message["body"], "WhatsApp", "outgoing", stage=stage,
                performed_at=performed_at, message_id=message_id, key="send:"+message_id)
            self._cancel_followups(conn, lead["id"], "Próxima etapa da sequência")
            if stage == "Contatado":
                options = {"initial": ("followup1", "Primeiro follow-up", 2), "followup1": ("followup2", "Último follow-up", 5),
                    "followup2": ("close_sequence", "Conferir retorno e encerrar sem resposta", 5)}
                if message["kind"] in options:
                    kind, title, days = options[message["kind"]]
                    self._new_task(conn, actor, lead, kind, title, stamp(next_business_day(parse_time(performed_at), days)), event_id)
            return event_id

    def record_interaction(self, token, lead_id, kind, channel, body, expected_version, performed_at=None, next_title="", next_due=None, key=None):
        if kind not in {"Contato realizado", "Resposta recebida", "Observação", "Sem interesse / opt-out"}:
            raise DomainError("Selecione um tipo válido de interação.")
        if channel not in {"WhatsApp", "Ligação", "E-mail", "Instagram", "Presencial", "Outro"} or not body.strip():
            raise DomainError("Informe o canal e o conteúdo do contato.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            if key and (existing := one(conn, select(S.interactions).where(S.interactions.c.idempotency_key == key))):
                return existing["id"]
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            block = kind == "Sem interesse / opt-out" or (kind == "Resposta recebida" and is_optout(body))
            stage = lead["stage"]
            direction = "incoming" if kind in {"Resposta recebida", "Sem interesse / opt-out"} else "outgoing" if kind == "Contato realizado" else "internal"
            if block:
                self._block(conn, actor, lead, body)
                stage = "Perdido"
            elif kind == "Resposta recebida":
                self._cancel_followups(conn, lead_id, "Resposta recebida")
                stage = "Em conversa" if stage in {"Novo", "Contatado", "Encerrado sem resposta"} and not lead["blocked"] else stage
            elif kind == "Contato realizado":
                if self._blocked(conn, lead):
                    raise DomainError("Contato bloqueado. Use Observação para registrar ocorrências passadas.")
                stage = "Contatado" if stage == "Novo" else stage
            conn.execute(update(S.leads).where(S.leads.c.id == lead_id).values(stage=stage))
            event_id = self._event(conn, actor, lead, "Não abordar novamente" if block else kind, body, channel, direction, stage, performed_at, key=key)
            if kind == "Contato realizado" and stage == "Contatado" and not next_title.strip():
                has_pending = conn.execute(select(S.tasks.c.id).where(S.tasks.c.lead_id == lead_id, S.tasks.c.state == "Pendente")).first()
                if not has_pending:
                    next_title = "Conferir retorno e definir o próximo passo"
                    next_due = stamp(next_business_day(parse_time(performed_at) if performed_at else now_utc(), 2))
            if next_title.strip() and not block and not self._blocked(conn, lead):
                if not next_due:
                    raise DomainError("Informe a data da próxima ação.")
                self._new_task(conn, actor, lead, "manual", next_title, next_due, event_id)
            return event_id

    def update_pipeline(self, token, lead_id, stage, value_cents, note, expected_version, next_title="", next_due=None):
        if stage not in STAGES or not 0 <= value_cents <= 1_000_000_000:
            raise DomainError("Etapa ou valor inválido.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            if self._blocked(conn, lead) and stage != "Perdido":
                raise DomainError("Um bloqueio não pode ser removido pela mudança de etapa.")
            if stage in {"Reunião marcada", "Proposta enviada"} and (not next_title.strip() or not next_due):
                raise DomainError("Informe a próxima ação e a data para acompanhar esta etapa.")
            if stage == "Perdido" and not note.strip():
                raise DomainError("Registre o motivo da perda.")
            conn.execute(update(S.leads).where(S.leads.c.id == lead_id).values(stage=stage, value_cents=int(value_cents)))
            if stage != "Contatado":
                self._cancel_followups(conn, lead_id, f"Etapa alterada para {stage}")
            if stage in {"Ganho", "Perdido", "Encerrado sem resposta"}:
                self._cancel_followups(conn, lead_id, f"Etapa encerrada: {stage}", all_tasks=True)
            event_id = self._event(conn, actor, lead, "Etapa comercial alterada", note or f"Etapa: {stage}", stage=stage)
            if next_title.strip() and stage not in {"Ganho", "Perdido", "Encerrado sem resposta"}:
                if not next_due:
                    raise DomainError("Defina a data da próxima ação.")
                self._new_task(conn, actor, lead, "meeting" if stage == "Reunião marcada" else "manual", next_title, next_due, event_id)

    def add_task(self, token, lead_id, title, due_at, expected_version):
        if not title.strip():
            raise DomainError("Descreva a próxima ação.")
        parse_time(due_at)
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            if self._blocked(conn, lead):
                raise DomainError("Lead bloqueado para novas ações comerciais.")
            task_id = self._new_task(conn, actor, lead, "manual", title, due_at)
            self._event(conn, actor, lead, "Próxima ação agendada", title)
            return task_id

    def finish_task(self, token, task_id, cancel=False, note=""):
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            task = one(conn, select(S.tasks).where(S.tasks.c.id == task_id))
            if not task or task["state"] != "Pendente":
                raise DomainError("Esta tarefa já foi encerrada.")
            lead = self._write_lead(conn, task["lead_id"], actor)
            if not cancel and task["kind"].startswith("followup"):
                raise DomainError("Registre o envio pela tela de mensagem ou cancele a tarefa.")
            if not cancel and task["kind"] == "close_sequence":
                if lead["stage"] != "Contatado" or task["due_at"] > stamp():
                    raise DomainError("Confira o prazo e a etapa antes de encerrar a sequência.")
                conn.execute(update(S.leads).where(S.leads.c.id == lead["id"]).values(stage="Encerrado sem resposta"))
                self._cancel_followups(conn, lead["id"], "Sequência encerrada")
            conn.execute(update(S.tasks).where(S.tasks.c.id == task_id).values(state="Cancelada" if cancel else "Concluída", completed_at=stamp(), completed_by=actor["id"], cancel_reason=note if cancel else ""))
            self._event(conn, actor, lead, "Tarefa cancelada" if cancel else "Tarefa concluída", task["title"] + (f" — {note}" if note else ""),
                stage="Encerrado sem resposta" if not cancel and task["kind"] == "close_sequence" else None)

    def backup(self, token):
        with self.engine.connect() as conn:
            self._actor(conn, token, admin=True)
            conn.rollback()
            if self.engine.dialect.name == "postgresql":
                conn = conn.execution_options(isolation_level="REPEATABLE READ")
            else:
                conn.exec_driver_sql("BEGIN")
            payload = {"format": "engage-flow-v2", "schema_version": "2.1.0", "created_at": stamp(),
                "tables": {table.name: rows(conn, select(table)) for table in S.BACKUP_TABLES}}
            return json.dumps(payload, ensure_ascii=False, indent=2).encode()

    def restore_empty(self, data: bytes):
        """CLI-only restore into a new empty database. Never invoked by an unauthenticated web page."""
        payload = json.loads(data)
        if payload.get("format") != "engage-flow-v2" or payload.get("schema_version") not in {"2.0.0", "2.1.0"}:
            raise DomainError("Backup incompatível.")
        with self.engine.begin() as conn:
            if any(conn.execute(select(func.count()).select_from(t)).scalar_one() for t in S.BACKUP_TABLES if t is not S.settings):
                raise DomainError("A restauração exige um banco novo, sem usuários ou leads.")
            conn.execute(delete(S.settings))
            for table in S.BACKUP_TABLES:
                records = payload["tables"].get(table.name, [])
                if records:
                    conn.execute(insert(table), records)
            if payload["schema_version"] == "2.0.0":
                self._migrate_lists(conn)
            conn.execute(update(S.settings).where(S.settings.c.key == "schema_version").values(value="2.1.0"))

    def _list(self, conn, list_id, actor, write=False, allow_archived=False):
        item = one(conn, select(S.contact_lists).where(S.contact_lists.c.id == list_id))
        if not item:
            raise DomainError("Lista não encontrada.")
        if write and actor["role"] != "admin" and item["created_by"] != actor["id"]:
            raise DomainError("Somente o criador da lista ou o administrador pode organizá-la.")
        if write and item["archived"] and not allow_archived:
            raise DomainError("Restaure a lista arquivada antes de adicionar contatos.")
        return item

    def _app_event(self, conn, actor, kind, body):
        conn.execute(insert(S.app_events).values(id=uid(), actor_id=actor["id"], kind=kind, body=body, created_at=stamp()))

    def create_list(self, token, name, description="", city="", niche="", color="#7050C4"):
        name = clean_text(name, 160)
        if not name:
            raise DomainError("Dê um nome à lista.")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise DomainError("Cor inválida.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            if any(normalized(x["name"]) == normalized(name) for x in rows(conn, select(S.contact_lists).where(S.contact_lists.c.archived.is_(False)))):
                raise DomainError("Já existe uma lista ativa com esse nome.")
            list_id = uid()
            conn.execute(insert(S.contact_lists).values(id=list_id, name=name, description=clean_text(description), city=clean_text(city,100),
                niche=clean_text(niche,120), color=color, created_by=actor["id"], created_at=stamp(), updated_at=stamp()))
            self._app_event(conn, actor, "Lista criada", name)
            return list_id

    def update_list(self, token, list_id, name, description, city, niche, archived, expected_version):
        if not name.strip():
            raise DomainError("Dê um nome à lista.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            self._list(conn, list_id, actor, write=True, allow_archived=True)
            if not archived and any(normalized(x["name"]) == normalized(name) for x in rows(conn, select(S.contact_lists).where(S.contact_lists.c.id != list_id, S.contact_lists.c.archived.is_(False)))):
                raise DomainError("Já existe uma lista ativa com esse nome.")
            changed = conn.execute(update(S.contact_lists).where(S.contact_lists.c.id == list_id, S.contact_lists.c.version == expected_version).values(
                name=clean_text(name,160), description=clean_text(description), city=clean_text(city,100), niche=clean_text(niche,120), archived=bool(archived),
                updated_at=stamp(), version=S.contact_lists.c.version+1))
            if changed.rowcount != 1:
                raise ConflictError("A lista foi atualizada. Atualize a página antes de salvar.")
            self._app_event(conn, actor, "Lista atualizada", f"{name}; arquivada: {bool(archived)}")

    def _join_list(self, conn, list_id, lead_id, actor):
        self._ignore(conn, S.list_members, {"list_id": list_id, "lead_id": lead_id, "added_by": actor["id"], "added_at": stamp()}, ["list_id", "lead_id"])

    def list_membership(self, token, list_id, lead_ids, remove=False):
        if not lead_ids:
            raise DomainError("Selecione pelo menos um contato.")
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            item = self._list(conn, list_id, actor, write=True)
            for lead_id in set(lead_ids):
                self._lead(conn, lead_id)
                if remove:
                    conn.execute(delete(S.list_members).where(S.list_members.c.list_id == list_id, S.list_members.c.lead_id == lead_id))
                else:
                    self._join_list(conn, list_id, lead_id, actor)
            self._app_event(conn, actor, "Contatos removidos da lista" if remove else "Contatos adicionados à lista", f"{item['name']}: {len(set(lead_ids))} contato(s).")

    def edit_lead(self, token, lead_id, company, city, niche, address, website, instagram, contact_person, email, tags, expected_version):
        if not company.strip() or not city.strip() or not niche.strip():
            raise DomainError("Preencha empresa, cidade e nicho.")
        if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise DomainError("Confira o e-mail informado.")
        website = safe_url(website) if website else ""
        with self.engine.begin() as conn:
            actor = self._actor(conn, token)
            lead = self._write_lead(conn, lead_id, actor, expected_version)
            key = identity_key(company, city, address)
            if conn.execute(select(S.leads.c.id).where(S.leads.c.identity_key == key, S.leads.c.id != lead_id)).first():
                raise DomainError("Já existe uma ficha para essa empresa, cidade e endereço.")
            changed_identity = key != lead["identity_key"]
            values = dict(identity_key=key, company=clean_text(company,250), city=clean_text(city,100), niche=clean_text(niche,120),
                address=clean_text(address), website=website, instagram=clean_text(instagram))
            if changed_identity:
                values.update(identity_verified=False, identity_verified_at=None)
                conn.execute(update(S.contacts).where(S.contacts.c.lead_id == lead_id).values(business_verified=False, whatsapp_verified=False, permission=False))
                self._cancel_followups(conn, lead_id, "Identidade alterada: reconferir canais")
            conn.execute(update(S.leads).where(S.leads.c.id == lead_id).values(**values))
            self._ignore(conn, S.lead_details, {"lead_id": lead_id, "updated_by": actor["id"], "updated_at": stamp()}, ["lead_id"])
            conn.execute(update(S.lead_details).where(S.lead_details.c.lead_id == lead_id).values(contact_person=clean_text(contact_person,160), email=clean_text(email,254),
                tags=clean_text(tags,500), updated_by=actor["id"], updated_at=stamp()))
            self._event(conn, actor, lead, "Dados da ficha atualizados", f"Empresa: {company}; cidade: {city}; contato: {contact_person}; e-mail: {email}; etiquetas: {tags}.")

    def create_user(self, token, username, name, password):
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,31}", username) or not name.strip():
            raise DomainError("Informe nome e usuário (3 a 32 caracteres, sem espaços).")
        if problem := password_problem(password):
            raise DomainError(problem)
        with self.engine.begin() as conn:
            actor = self._actor(conn, token, admin=True)
            if conn.execute(select(S.users.c.id).where(S.users.c.username == username)).first():
                raise DomainError("Este usuário já existe.")
            conn.execute(insert(S.users).values(id=uid(), username=username, name=clean_text(name,120), role="operator", password_hash=hash_password(password),
                active=True, must_change_password=True, created_at=stamp()))
            self._app_event(conn, actor, "Usuário criado", username)



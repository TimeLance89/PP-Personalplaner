from __future__ import annotations

import json
import secrets
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .auth import (
    SESSION_COOKIE,
    clear_login_attempts,
    create_session,
    current_user,
    delete_session,
    hash_password,
    rate_limit_login,
    require_admin,
    require_csrf,
    require_department_access,
    verify_password,
)
from .config import Settings
from .db import Database, json_load, utcnow
from .mailer import send_mail
from .services import (
    FIELD_KEY_RE,
    active_assignment_for_worker,
    active_assignment_sql,
    audit,
    normalize_custom_data,
    offboarding_message,
)


def clean_text(value: str, limit: int = 500) -> str:
    return value.strip()[:limit]


class SetupBody(BaseModel):
    token: str
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=256)


class LoginBody(BaseModel):
    username: str
    password: str


class DepartmentBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(default="", max_length=40)
    active: bool = True
    custom_data: dict[str, Any] = Field(default_factory=dict)


class AgencyBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    contact_name: str = Field(default="", max_length=160)
    email: str = Field(default="", max_length=240)
    phone: str = Field(default="", max_length=80)
    active: bool = True


class UserBody(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=2, max_length=120)
    password: str | None = Field(default=None, min_length=10, max_length=256)
    role: Literal["admin", "leader"] = "leader"
    department_id: int | None = None
    active: bool = True


class WorkerBody(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    employee_code: str = Field(default="", max_length=80)
    agency_id: int
    start_date: str | None = None
    notes: str = Field(default="", max_length=2000)
    status: Literal["active", "inactive", "archived"] = "active"
    custom_data: dict[str, Any] = Field(default_factory=dict)


class AssignmentBody(BaseModel):
    worker_id: int
    department_id: int
    assigned_from: str | None = None
    assigned_until: str | None = None
    notes: str = Field(default="", max_length=1000)


class FieldBody(BaseModel):
    entity_type: Literal["worker", "department"]
    field_key: str
    label: str = Field(min_length=1, max_length=120)
    field_type: Literal["text", "number", "date", "boolean", "select"]
    required: bool = False
    options: list[str] = Field(default_factory=list)
    active: bool = True
    sort_order: int = 100


class ReasonBody(BaseModel):
    label: str = Field(min_length=2, max_length=160)
    active: bool = True
    sort_order: int = 100


class OffboardingBody(BaseModel):
    worker_id: int
    effective_at: str
    reason_id: int
    reason_text: str = Field(default="", max_length=1500)
    replacement_required: bool = False
    replacement_notes: str = Field(default="", max_length=1500)


def build_router(db: Database, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api")

    def user_for(request: Request) -> dict[str, Any]:
        return current_user(db, request)

    def mutate_user(request: Request) -> dict[str, Any]:
        user = user_for(request)
        require_csrf(request, user)
        return user

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "database": db.path.exists()}

    @router.get("/setup/status")
    def setup_status() -> dict[str, Any]:
        count = db.one("SELECT COUNT(*) AS n FROM users")
        return {"required": not bool(count and count["n"]), "token_file": "data/setup-token.txt"}

    @router.post("/setup")
    def setup(body: SetupBody) -> dict[str, Any]:
        count = db.one("SELECT COUNT(*) AS n FROM users")
        if count and count["n"]:
            raise HTTPException(status_code=409, detail="Ein Administrator wurde bereits eingerichtet.")
        if not secrets.compare_digest(body.token.strip(), settings.setup_token):
            raise HTTPException(status_code=403, detail="Setup-Token ungültig")
        try:
            password_hash = hash_password(body.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        user_id = db.execute(
            "INSERT INTO users(username,display_name,password_hash,role,department_id,active,created_at) VALUES (?,?,?,?,NULL,1,?)",
            (clean_text(body.username, 80), clean_text(body.display_name, 120), password_hash, "admin", utcnow()),
        )
        audit(db, user_id, "setup_admin_created", "user", user_id)
        return {"ok": True}

    @router.post("/auth/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        ip = request.client.host if request.client else "unknown"
        rate_limit_login(ip)
        user = db.one("SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1", (body.username.strip(),))
        if not user or not verify_password(user["password_hash"], body.password):
            raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
        clear_login_attempts(ip)
        raw, csrf = create_session(db, int(user["id"]), settings.session_hours, request.headers.get("user-agent", ""), ip)
        response.set_cookie(
            SESSION_COOKIE,
            raw,
            max_age=settings.session_hours * 3600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        db.execute("UPDATE users SET last_login_at=? WHERE id=?", (utcnow(), user["id"]))
        audit(db, int(user["id"]), "login", "user", int(user["id"]))
        return {"ok": True, "csrf_token": csrf}

    @router.post("/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, Any]:
        user = user_for(request)
        require_csrf(request, user)
        delete_session(db, request.cookies.get(SESSION_COOKIE, ""))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        user = user_for(request)
        department = None
        if user.get("department_id"):
            department = db.one("SELECT id,name,code FROM departments WHERE id=?", (user["department_id"],))
        return {
            "id": user["id"], "username": user["username"], "display_name": user["display_name"],
            "role": user["role"], "department_id": user["department_id"], "department": department,
            "csrf_token": user["csrf_token"],
        }

    @router.get("/dashboard")
    def dashboard(request: Request) -> dict[str, Any]:
        user = user_for(request)
        if user["role"] == "admin":
            workers = db.all(active_assignment_sql())
            dept_count = db.one("SELECT COUNT(*) AS n FROM departments WHERE active=1")["n"]
            unassigned = db.one(
                """SELECT COUNT(*) AS n FROM workers w WHERE w.status='active' AND NOT EXISTS (
                    SELECT 1 FROM assignments a WHERE a.worker_id=w.id AND date(a.assigned_from)<=date('now','localtime')
                    AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date('now','localtime')))
                """
            )["n"]
        else:
            if not user.get("department_id"):
                workers = []
            else:
                workers = db.all(active_assignment_sql(" AND a.department_id=?"), (user["department_id"],))
            dept_count = 1 if user.get("department_id") else 0
            unassigned = 0
        for row in workers:
            row["custom_data"] = json_load(row.get("custom_data"), {})
            scheduled = db.one(
                "SELECT id,effective_at,status FROM offboarding_requests WHERE assignment_id=? AND status!='cancelled' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            )
            row["offboarding"] = scheduled
        if user["role"] == "admin":
            offboardings = db.all("SELECT * FROM offboarding_requests ORDER BY id DESC LIMIT 20")
        else:
            offboardings = db.all("SELECT * FROM offboarding_requests WHERE department_id=? ORDER BY id DESC LIMIT 20", (user["department_id"],)) if user.get("department_id") else []
        return {
            "counts": {"workers": len(workers), "departments": dept_count, "unassigned": unassigned, "offboardings": len(offboardings)},
            "workers": workers,
            "recent_offboardings": offboardings,
            "smtp_configured": bool(settings.smtp_host and settings.smtp_from),
        }

    @router.get("/departments")
    def departments(request: Request) -> list[dict[str, Any]]:
        user = user_for(request)
        if user["role"] == "leader":
            rows = db.all("SELECT * FROM departments WHERE id=?", (user["department_id"],)) if user.get("department_id") else []
        else:
            rows = db.all("SELECT * FROM departments ORDER BY active DESC,name COLLATE NOCASE")
        for row in rows:
            row["custom_data"] = json_load(row.get("custom_data"), {})
        return rows

    @router.post("/departments")
    def create_department(body: DepartmentBody, request: Request) -> dict[str, Any]:
        user = mutate_user(request); require_admin(user)
        custom = normalize_custom_data(db, "department", body.custom_data)
        try:
            entity_id = db.execute(
                "INSERT INTO departments(name,code,active,custom_data) VALUES (?,?,?,?)",
                (clean_text(body.name,120), clean_text(body.code,40), int(body.active), json.dumps(custom, ensure_ascii=False)),
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail="Abteilungsname bereits vorhanden oder ungültig") from exc
        audit(db, user["id"], "department_created", "department", entity_id)
        return db.one("SELECT * FROM departments WHERE id=?", (entity_id,)) or {}

    @router.patch("/departments/{department_id}")
    def update_department(department_id: int, body: DepartmentBody, request: Request) -> dict[str, Any]:
        user = mutate_user(request); require_admin(user)
        if not db.one("SELECT id FROM departments WHERE id=?", (department_id,)):
            raise HTTPException(status_code=404, detail="Abteilung nicht gefunden")
        custom = normalize_custom_data(db, "department", body.custom_data)
        db.execute("UPDATE departments SET name=?,code=?,active=?,custom_data=? WHERE id=?", (clean_text(body.name,120), clean_text(body.code,40), int(body.active), json.dumps(custom,ensure_ascii=False), department_id))
        audit(db, user["id"], "department_updated", "department", department_id)
        return db.one("SELECT * FROM departments WHERE id=?", (department_id,)) or {}

    @router.get("/agencies")
    def agencies(request: Request) -> list[dict[str, Any]]:
        user_for(request)
        return db.all("SELECT * FROM agencies ORDER BY active DESC,name COLLATE NOCASE")

    @router.post("/agencies")
    def create_agency(body: AgencyBody, request: Request) -> dict[str, Any]:
        user = mutate_user(request); require_admin(user)
        entity_id = db.execute("INSERT INTO agencies(name,contact_name,email,phone,active) VALUES (?,?,?,?,?)", (clean_text(body.name,160),clean_text(body.contact_name,160),clean_text(body.email,240),clean_text(body.phone,80),int(body.active)))
        audit(db,user["id"],"agency_created","agency",entity_id)
        return db.one("SELECT * FROM agencies WHERE id=?",(entity_id,)) or {}

    @router.patch("/agencies/{agency_id}")
    def update_agency(agency_id: int, body: AgencyBody, request: Request) -> dict[str, Any]:
        user = mutate_user(request); require_admin(user)
        db.execute("UPDATE agencies SET name=?,contact_name=?,email=?,phone=?,active=? WHERE id=?",(clean_text(body.name,160),clean_text(body.contact_name,160),clean_text(body.email,240),clean_text(body.phone,80),int(body.active),agency_id))
        audit(db,user["id"],"agency_updated","agency",agency_id)
        return db.one("SELECT * FROM agencies WHERE id=?",(agency_id,)) or {}

    @router.get("/users")
    def users(request: Request) -> list[dict[str, Any]]:
        user = user_for(request); require_admin(user)
        return db.all("""SELECT u.id,u.username,u.display_name,u.role,u.department_id,u.active,u.created_at,u.last_login_at,d.name AS department_name
                       FROM users u LEFT JOIN departments d ON d.id=u.department_id ORDER BY u.active DESC,u.display_name COLLATE NOCASE""")

    @router.post("/users")
    def create_user(body: UserBody, request: Request) -> dict[str, Any]:
        user = mutate_user(request); require_admin(user)
        if body.role == "leader" and not body.department_id:
            raise HTTPException(status_code=422, detail="Bereichsleiter benötigen eine Abteilung")
        department_id = None if body.role == "admin" else body.department_id
        if not body.password:
            raise HTTPException(status_code=422, detail="Passwort erforderlich")
        entity_id = db.execute("INSERT INTO users(username,display_name,password_hash,role,department_id,active,created_at) VALUES (?,?,?,?,?,?,?)",(clean_text(body.username,80),clean_text(body.display_name,120),hash_password(body.password),body.role,department_id,int(body.active),utcnow()))
        audit(db,user["id"],"user_created","user",entity_id,{"role":body.role,"department_id":department_id})
        return {"id":entity_id}

    @router.patch("/users/{user_id}")
    def update_user(user_id: int, body: UserBody, request: Request) -> dict[str, Any]:
        user = mutate_user(request); require_admin(user)
        existing = db.one("SELECT * FROM users WHERE id=?",(user_id,))
        if not existing: raise HTTPException(status_code=404,detail="Benutzer nicht gefunden")
        department_id = None if body.role == "admin" else body.department_id
        if body.role == "leader" and not department_id: raise HTTPException(status_code=422,detail="Bereichsleiter benötigen eine Abteilung")
        password_hash = existing["password_hash"] if not body.password else hash_password(body.password)
        db.execute("UPDATE users SET username=?,display_name=?,password_hash=?,role=?,department_id=?,active=? WHERE id=?",(clean_text(body.username,80),clean_text(body.display_name,120),password_hash,body.role,department_id,int(body.active),user_id))
        if not body.active: db.execute("DELETE FROM sessions WHERE user_id=?",(user_id,))
        audit(db,user["id"],"user_updated","user",user_id)
        return {"ok":True}

    @router.get("/workers")
    def workers(request: Request) -> list[dict[str, Any]]:
        user = user_for(request)
        if user["role"] == "admin":
            rows = db.all("""SELECT w.*,ag.name AS agency_name,
                (SELECT a.department_id FROM assignments a WHERE a.worker_id=w.id AND date(a.assigned_from)<=date('now','localtime') AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date('now','localtime')) ORDER BY a.id DESC LIMIT 1) AS department_id,
                (SELECT d.name FROM assignments a JOIN departments d ON d.id=a.department_id WHERE a.worker_id=w.id AND date(a.assigned_from)<=date('now','localtime') AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date('now','localtime')) ORDER BY a.id DESC LIMIT 1) AS department_name
                FROM workers w JOIN agencies ag ON ag.id=w.agency_id WHERE w.status!='archived' ORDER BY w.last_name COLLATE NOCASE,w.first_name COLLATE NOCASE""")
        else:
            rows = db.all(active_assignment_sql(" AND a.department_id=?"),(user["department_id"],)) if user.get("department_id") else []
            seen=set(); dedup=[]
            for row in rows:
                if row["worker_id"] in seen: continue
                seen.add(row["worker_id"]); row["id"]=row["worker_id"]; row["notes"]=row.pop("worker_notes",""); dedup.append(row)
            rows=dedup
        for row in rows: row["custom_data"] = json_load(row.get("custom_data"),{})
        return rows

    @router.post("/workers")
    def create_worker(body: WorkerBody, request: Request) -> dict[str, Any]:
        user = mutate_user(request); require_admin(user)
        if not db.one("SELECT id FROM agencies WHERE id=? AND active=1",(body.agency_id,)): raise HTTPException(status_code=422,detail="Zeitarbeitsfirma ungültig")
        custom=normalize_custom_data(db,"worker",body.custom_data)
        entity_id=db.execute("INSERT INTO workers(first_name,last_name,employee_code,agency_id,start_date,status,notes,custom_data,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(clean_text(body.first_name,120),clean_text(body.last_name,120),clean_text(body.employee_code,80),body.agency_id,body.start_date,body.status,clean_text(body.notes,2000),json.dumps(custom,ensure_ascii=False),utcnow(),utcnow()))
        audit(db,user["id"],"worker_created","worker",entity_id)
        return {"id":entity_id}

    @router.patch("/workers/{worker_id}")
    def update_worker(worker_id:int, body:WorkerBody, request:Request)->dict[str,Any]:
        user=mutate_user(request); require_admin(user)
        if not db.one("SELECT id FROM workers WHERE id=?",(worker_id,)): raise HTTPException(status_code=404,detail="Zeitarbeiter nicht gefunden")
        custom=normalize_custom_data(db,"worker",body.custom_data)
        db.execute("UPDATE workers SET first_name=?,last_name=?,employee_code=?,agency_id=?,start_date=?,status=?,notes=?,custom_data=?,updated_at=? WHERE id=?",(clean_text(body.first_name,120),clean_text(body.last_name,120),clean_text(body.employee_code,80),body.agency_id,body.start_date,body.status,clean_text(body.notes,2000),json.dumps(custom,ensure_ascii=False),utcnow(),worker_id))
        audit(db,user["id"],"worker_updated","worker",worker_id)
        return {"ok":True}

    @router.post("/assignments")
    def create_assignment(body: AssignmentBody, request: Request) -> dict[str, Any]:
        user=mutate_user(request); require_admin(user)
        if active_assignment_for_worker(db,body.worker_id): raise HTTPException(status_code=409,detail="Der Zeitarbeiter ist aktuell bereits einer Abteilung zugeteilt")
        if not db.one("SELECT id FROM departments WHERE id=? AND active=1",(body.department_id,)): raise HTTPException(status_code=422,detail="Abteilung ungültig")
        assigned_from=body.assigned_from or date.today().isoformat()
        entity_id=db.execute("INSERT INTO assignments(worker_id,department_id,assigned_from,assigned_until,notes,created_by,created_at) VALUES (?,?,?,?,?,?,?)",(body.worker_id,body.department_id,assigned_from,body.assigned_until,clean_text(body.notes,1000),user["id"],utcnow()))
        audit(db,user["id"],"worker_assigned","assignment",entity_id,{"worker_id":body.worker_id,"department_id":body.department_id})
        return {"id":entity_id}

    @router.get("/custom-fields")
    def custom_fields(request:Request)->list[dict[str,Any]]:
        user_for(request)
        rows=db.all("SELECT * FROM custom_fields ORDER BY entity_type,sort_order,id")
        for row in rows: row["options"]=json_load(row.pop("options_json"),[])
        return rows

    @router.post("/custom-fields")
    def create_field(body:FieldBody,request:Request)->dict[str,Any]:
        user=mutate_user(request); require_admin(user)
        if not FIELD_KEY_RE.fullmatch(body.field_key): raise HTTPException(status_code=422,detail="Feldschlüssel: Kleinbuchstaben/Zahlen/Unterstrich, beginnend mit Buchstabe")
        options=[clean_text(v,80) for v in body.options if clean_text(v,80)]
        entity_id=db.execute("INSERT INTO custom_fields(entity_type,field_key,label,field_type,required,options_json,active,sort_order) VALUES (?,?,?,?,?,?,?,?)",(body.entity_type,body.field_key,clean_text(body.label,120),body.field_type,int(body.required),json.dumps(options,ensure_ascii=False),int(body.active),body.sort_order))
        audit(db,user["id"],"custom_field_created","custom_field",entity_id)
        return {"id":entity_id}

    @router.patch("/custom-fields/{field_id}")
    def update_field(field_id:int,body:FieldBody,request:Request)->dict[str,Any]:
        user=mutate_user(request); require_admin(user)
        if not FIELD_KEY_RE.fullmatch(body.field_key): raise HTTPException(status_code=422,detail="Feldschlüssel ungültig")
        db.execute("UPDATE custom_fields SET entity_type=?,field_key=?,label=?,field_type=?,required=?,options_json=?,active=?,sort_order=? WHERE id=?",(body.entity_type,body.field_key,clean_text(body.label,120),body.field_type,int(body.required),json.dumps([clean_text(v,80) for v in body.options],ensure_ascii=False),int(body.active),body.sort_order,field_id))
        audit(db,user["id"],"custom_field_updated","custom_field",field_id)
        return {"ok":True}

    @router.get("/offboarding-reasons")
    def reasons(request:Request)->list[dict[str,Any]]:
        user_for(request); return db.all("SELECT * FROM offboarding_reasons WHERE active=1 ORDER BY sort_order,id")

    @router.get("/admin/offboarding-reasons")
    def admin_reasons(request:Request)->list[dict[str,Any]]:
        user=user_for(request); require_admin(user); return db.all("SELECT * FROM offboarding_reasons ORDER BY active DESC,sort_order,id")

    @router.post("/offboarding-reasons")
    def create_reason(body:ReasonBody,request:Request)->dict[str,Any]:
        user=mutate_user(request); require_admin(user)
        entity_id=db.execute("INSERT INTO offboarding_reasons(label,active,sort_order) VALUES (?,?,?)",(clean_text(body.label,160),int(body.active),body.sort_order))
        audit(db,user["id"],"offboarding_reason_created","offboarding_reason",entity_id); return {"id":entity_id}

    @router.patch("/offboarding-reasons/{reason_id}")
    def update_reason(reason_id:int,body:ReasonBody,request:Request)->dict[str,Any]:
        user=mutate_user(request); require_admin(user)
        db.execute("UPDATE offboarding_reasons SET label=?,active=?,sort_order=? WHERE id=?",(clean_text(body.label,160),int(body.active),body.sort_order,reason_id))
        audit(db,user["id"],"offboarding_reason_updated","offboarding_reason",reason_id); return {"ok":True}

    def prepare_offboarding(body:OffboardingBody,user:dict[str,Any])->tuple[dict[str,Any],dict[str,Any],str,str]:
        try: date.fromisoformat(body.effective_at)
        except ValueError as exc: raise HTTPException(status_code=422,detail="Abmeldedatum ungültig") from exc
        assignment=active_assignment_for_worker(db,body.worker_id,user.get("department_id") if user["role"]=="leader" else None)
        if not assignment: raise HTTPException(status_code=404,detail="Keine aktive Zuteilung für diesen Zeitarbeiter gefunden")
        require_department_access(user,int(assignment["department_id"]))
        existing=db.one("SELECT id,status FROM offboarding_requests WHERE assignment_id=? AND status!='cancelled' ORDER BY id DESC LIMIT 1",(assignment["id"],))
        if existing: raise HTTPException(status_code=409,detail="Für diese Zuteilung existiert bereits eine Abmeldung")
        reason=db.one("SELECT * FROM offboarding_reasons WHERE id=? AND active=1",(body.reason_id,))
        if not reason: raise HTTPException(status_code=422,detail="Abmeldegrund ungültig")
        record={**assignment,"effective_at":body.effective_at,"reason_text":clean_text(body.reason_text,1500),"replacement_required":int(body.replacement_required),"replacement_notes":clean_text(body.replacement_notes,1500)}
        subject,text=offboarding_message(settings,record,reason["label"],user["display_name"])
        return assignment,reason,subject,text

    @router.post("/offboardings/preview")
    def offboarding_preview(body:OffboardingBody,request:Request)->dict[str,Any]:
        user=user_for(request); _,_,subject,text=prepare_offboarding(body,user)
        return {"subject":subject,"body":text}

    @router.post("/offboardings")
    def create_offboarding(body:OffboardingBody,request:Request)->dict[str,Any]:
        user=mutate_user(request); assignment,reason,subject,text=prepare_offboarding(body,user)
        to=assignment.get("agency_email","")
        entity_id=db.execute("""INSERT INTO offboarding_requests(worker_id,assignment_id,department_id,agency_id,requested_by,effective_at,reason_id,reason_text,replacement_required,replacement_notes,status,notification_to,notification_subject,notification_body,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(body.worker_id,assignment["id"],assignment["department_id"],assignment["agency_id"],user["id"],body.effective_at,reason["id"],clean_text(body.reason_text,1500),int(body.replacement_required),clean_text(body.replacement_notes,1500),"pending",to,subject,text,utcnow()))
        status_value="sent"; error=""
        try: send_mail(settings,to,subject,text)
        except Exception as exc: status_value="mail_failed"; error=str(exc)[:1000]
        sent_at=utcnow() if status_value=="sent" else None
        db.execute("UPDATE offboarding_requests SET status=?,mail_error=?,sent_at=? WHERE id=?",(status_value,error,sent_at,entity_id))
        db.execute("UPDATE assignments SET assigned_until=? WHERE id=?",(body.effective_at,assignment["id"]))
        audit(db,user["id"],"worker_offboarding_requested","offboarding",entity_id,{"status":status_value,"effective_at":body.effective_at,"replacement_required":body.replacement_required})
        return db.one("SELECT * FROM offboarding_requests WHERE id=?",(entity_id,)) or {}

    @router.get("/offboardings")
    def offboardings(request:Request)->list[dict[str,Any]]:
        user=user_for(request)
        where=""; params:tuple[Any,...]=()
        if user["role"]=="leader": where="WHERE o.department_id=?"; params=(user["department_id"],)
        return db.all(f"""SELECT o.*,w.first_name,w.last_name,w.employee_code,d.name AS department_name,ag.name AS agency_name,r.label AS reason_label,u.display_name AS requested_by_name
                       FROM offboarding_requests o JOIN workers w ON w.id=o.worker_id JOIN departments d ON d.id=o.department_id JOIN agencies ag ON ag.id=o.agency_id LEFT JOIN offboarding_reasons r ON r.id=o.reason_id JOIN users u ON u.id=o.requested_by {where} ORDER BY o.id DESC""",params)

    @router.post("/offboardings/{offboarding_id}/retry")
    def retry_offboarding(offboarding_id:int,request:Request)->dict[str,Any]:
        user=mutate_user(request)
        row=db.one("SELECT * FROM offboarding_requests WHERE id=?",(offboarding_id,))
        if not row: raise HTTPException(status_code=404,detail="Abmeldung nicht gefunden")
        require_department_access(user,row["department_id"])
        try: send_mail(settings,row["notification_to"],row["notification_subject"],row["notification_body"])
        except Exception as exc:
            db.execute("UPDATE offboarding_requests SET status='mail_failed',mail_error=? WHERE id=?",(str(exc)[:1000],offboarding_id))
            raise HTTPException(status_code=502,detail=f"E-Mail konnte nicht versendet werden: {exc}") from exc
        db.execute("UPDATE offboarding_requests SET status='sent',mail_error='',sent_at=? WHERE id=?",(utcnow(),offboarding_id))
        audit(db,user["id"],"offboarding_mail_retried","offboarding",offboarding_id)
        return {"ok":True}

    @router.get("/audit")
    def audit_log(request:Request)->list[dict[str,Any]]:
        user=user_for(request); require_admin(user)
        rows=db.all("""SELECT a.*,u.display_name AS user_name FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 300""")
        for row in rows: row["details"]=json_load(row.pop("details_json"),{})
        return rows

    return router

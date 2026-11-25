"""HTMX routes.

Pages map 1:1 to the UI mockup (12 pages) at a visual level, with v1 scope:
    /ui/campaigns          — Campaign Studio (Step 1)
    /ui/opportunities      — ranked list + right rail (default landing)
    /ui/business/{id}      — Business 360
    /ui/approvals          — approval queue
    /ui/market             — Market and learning
    /ui/sources            — Sources, cost, accuracy
Stubs (present but minimal):
    /ui/panic, /ui/map, /ui/dialer

Auth: cookie-based single-operator login against LB_API_TOKEN. A GET /ui/login
accepts the token, sets the cookie, redirects to /ui/opportunities. Simple
but matches the spec's "single operator" posture.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadbeast.api.deps import db_session
from leadbeast.config import get_settings
from leadbeast.db.models import (
    Business,
    CallOutcome,
    CallTask,
    CallTaskStatus,
    Campaign,
    Draft,
    DraftStatus,
    EvidenceEvent,
    LeadClass,
    Pack,
    PanicAlert,
    PanicAlertStatus,
    PanicWatch,
    ScoreSnapshot,
)
from leadbeast.panic import evaluate_watch, evaluate_all_watches

router = APIRouter(prefix="/ui", tags=["ui"])

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_COOKIE = "lb_token"


def _panic_unread() -> int:
    # Jinja global invoked on every render; opens its own session.
    from leadbeast.db.session import SessionLocal

    try:
        with SessionLocal() as s:
            return int(
                s.execute(
                    select(func.count(PanicAlert.id)).where(
                        PanicAlert.status == PanicAlertStatus.NEW
                    )
                ).scalar_one()
                or 0
            )
    except Exception:
        return 0


_TEMPLATES.env.globals["panic_unread"] = _panic_unread


def ui_auth(request: Request) -> None:
    expected = get_settings().api_token
    token = request.cookies.get(_COOKIE, "")
    if token != expected:
        # Let the browser bounce to login; API code never reaches here.
        raise HTTPException(status_code=307, headers={"Location": "/ui/login"})


UiAuthDep = Depends(ui_auth)
SessDep = Depends(db_session)


# --- Auth ---------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login(token: Annotated[str, Form()]) -> RedirectResponse:
    expected = get_settings().api_token
    if token != expected:
        return RedirectResponse(
            url="/ui/login?err=1", status_code=status.HTTP_303_SEE_OTHER
        )
    resp = RedirectResponse(url="/ui/opportunities", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 14)
    return resp


@router.get("/logout")
def logout() -> RedirectResponse:
    resp = RedirectResponse(url="/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(_COOKIE)
    return resp


# --- Dashboard: Opportunities ------------------------------------------


@router.get("/opportunities", response_class=HTMLResponse, dependencies=[UiAuthDep])
def opportunities(
    request: Request,
    session: Annotated[Session, SessDep],
    cls: str | None = None,
) -> HTMLResponse:
    stmt = (
        select(Business, ScoreSnapshot)
        .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
        .order_by(ScoreSnapshot.score.desc().nullslast(), Business.created_at.desc())
        .limit(100)
    )
    valid = {"A", "B", "C", "D"}
    if cls and cls.upper() in valid:
        stmt = stmt.where(ScoreSnapshot.lead_class == LeadClass(cls.upper()))

    rows = session.execute(stmt).all()

    pending_count = int(
        session.execute(
            select(func.count(Draft.id)).where(Draft.status == DraftStatus.PENDING)
        ).scalar_one()
        or 0
    )

    total_found = int(
        session.execute(select(func.count(Business.id))).scalar_one() or 0
    )
    scored = int(
        session.execute(
            select(func.count(func.distinct(ScoreSnapshot.business_id)))
        ).scalar_one()
        or 0
    )
    class_ab = int(
        session.execute(
            select(func.count(ScoreSnapshot.id)).where(
                ScoreSnapshot.lead_class.in_([LeadClass.A, LeadClass.B])
            )
        ).scalar_one()
        or 0
    )

    opps = []
    for biz, snap in rows:
        opps.append(
            {
                "id": biz.id,
                "name": biz.name,
                "city": biz.city,
                "region": biz.region,
                "category": biz.category,
                "website": biz.website,
                "phone": biz.phone,
                "score": snap.score if snap else None,
                "lead_class": snap.lead_class.value if snap else None,
                "confidence": snap.confidence.value if snap else None,
                "sub_scores": snap.sub_scores if snap else None,
                "reasons": snap.reasons if snap else None,
            }
        )

    highlight = opps[0] if opps else None

    return _TEMPLATES.TemplateResponse(
        request,
        "opportunities.html",
        {
            "opps": opps,
            "active_class": cls.upper() if cls and cls.upper() in valid else "ALL",
            "kpis": {
                "found": total_found,
                "scored": scored,
                "class_ab": class_ab,
                "pending": pending_count,
            },
            "highlight": highlight,
            "pending_count": pending_count,
            "nav_active": "opportunities",
        },
    )


# --- Business 360 ------------------------------------------------------


@router.get("/business/{business_id}", response_class=HTMLResponse, dependencies=[UiAuthDep])
def business_detail(
    business_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, SessDep],
) -> HTMLResponse:
    biz = session.get(Business, business_id)
    if biz is None:
        raise HTTPException(status_code=404, detail="Business not found")

    evidence = list(
        session.execute(
            select(EvidenceEvent)
            .where(EvidenceEvent.business_id == business_id)
            .order_by(EvidenceEvent.observed_at.desc())
        )
        .scalars()
        .all()
    )
    latest_snap = session.execute(
        select(ScoreSnapshot)
        .where(ScoreSnapshot.business_id == business_id)
        .order_by(ScoreSnapshot.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    pending_draft = session.execute(
        select(Draft).where(
            Draft.business_id == business_id,
            Draft.status.in_([DraftStatus.PENDING, DraftStatus.EDITED]),
        )
    ).scalar_one_or_none()

    return _TEMPLATES.TemplateResponse(
        request,
        "business.html",
        {
            "biz": biz,
            "evidence": evidence,
            "snap": latest_snap,
            "pending_draft": pending_draft,
            "nav_active": "opportunities",
        },
    )


# --- Approvals ---------------------------------------------------------


@router.get("/approvals", response_class=HTMLResponse, dependencies=[UiAuthDep])
def approvals(
    request: Request, session: Annotated[Session, SessDep]
) -> HTMLResponse:
    drafts = list(
        session.execute(
            select(Draft, Business)
            .join(Business, Business.id == Draft.business_id)
            .where(Draft.status.in_([DraftStatus.PENDING, DraftStatus.EDITED]))
            .order_by(Draft.created_at.asc())
        ).all()
    )
    return _TEMPLATES.TemplateResponse(
        request, "approvals.html", {"drafts": drafts, "nav_active": "approvals"}
    )


# --- Market and learning -----------------------------------------------


@router.get("/market", response_class=HTMLResponse, dependencies=[UiAuthDep])
def market(request: Request, session: Annotated[Session, SessDep]) -> HTMLResponse:
    class_rows = session.execute(
        select(ScoreSnapshot.lead_class, func.count(ScoreSnapshot.id)).group_by(
            ScoreSnapshot.lead_class
        )
    ).all()
    gap = {c.value: 0 for c in LeadClass}
    for cls, n in class_rows:
        gap[cls.value] = int(n)

    sent = int(
        session.execute(
            select(func.count(Draft.id)).where(Draft.status == DraftStatus.SENT)
        ).scalar_one()
        or 0
    )
    approved = int(
        session.execute(
            select(func.count(Draft.id)).where(Draft.status == DraftStatus.APPROVED)
        ).scalar_one()
        or 0
    )
    # No REPLIED status in the Draft model; placeholder until Outcome wiring.
    replied = 0
    total_biz = int(session.execute(select(func.count(Business.id))).scalar_one() or 0)
    passed_busy = int(
        session.execute(
            select(func.count(ScoreSnapshot.business_id.distinct()))
        ).scalar_one()
        or 0
    )
    class_ab = gap["A"] + gap["B"]
    with_phone = int(
        session.execute(
            select(func.count(Business.id)).where(Business.phone.is_not(None))
        ).scalar_one()
        or 0
    )

    # Simplified "precision" table: signals shown with a placeholder precision
    # until we wire golden_label outcomes.
    signals = [
        {"name": "No website", "precision": 96, "status": "Live"},
        {"name": "Unclaimed map listing", "precision": 93, "status": "Live"},
        {"name": "Marketing quiet 12 months", "precision": 81, "status": "Held back"},
        {"name": "Non-tech operator", "precision": 88, "status": "Held back"},
    ]

    return _TEMPLATES.TemplateResponse(
        request,
        "market.html",
        {
            "gap": gap,
            "sent": sent,
            "approved": approved,
            "replied": replied,
            "total_biz": total_biz,
            "passed_busy": passed_busy,
            "class_ab": class_ab,
            "with_phone_pct": round(100 * with_phone / total_biz) if total_biz else 0,
            "gap_pct": round(100 * (gap["A"] + gap["B"] + gap["C"]) / total_biz) if total_biz else 0,
            "signals": signals,
            "nav_active": "market",
        },
    )


# --- Sources / cost / accuracy -----------------------------------------


@router.get("/sources", response_class=HTMLResponse, dependencies=[UiAuthDep])
def sources(request: Request, session: Annotated[Session, SessDep]) -> HTMLResponse:
    settings = get_settings()
    return _TEMPLATES.TemplateResponse(
        request,
        "sources.html",
        {
            "settings_view": {
                "model_provider": settings.model_provider,
                "channel_provider": settings.channel_provider,
                "crm_provider": settings.crm_provider,
                "dry_run": settings.dry_run,
                "cap_per_day": settings.cap_per_day_cents,
                "cap_per_month": settings.cap_per_month_cents,
            },
            "nav_active": "sources",
        },
    )


# --- Campaign Studio (Step 1) ------------------------------------------


@router.get("/campaigns", response_class=HTMLResponse, dependencies=[UiAuthDep])
def campaigns_list(
    request: Request, session: Annotated[Session, SessDep]
) -> HTMLResponse:
    rows = list(
        session.execute(
            select(Campaign).order_by(Campaign.created_at.desc())
        )
        .scalars()
        .all()
    )
    packs = list(session.execute(select(Pack)).scalars().all())
    return _TEMPLATES.TemplateResponse(
        request,
        "campaigns.html",
        {"campaigns": rows, "packs": packs, "nav_active": "campaigns"},
    )


@router.post("/campaigns")
def campaigns_create(
    name: Annotated[str, Form()],
    pack_key: Annotated[str, Form()],
    session: Annotated[Session, SessDep],
) -> RedirectResponse:
    pack = session.execute(select(Pack).where(Pack.key == pack_key)).scalar_one_or_none()
    if pack is None:
        return RedirectResponse(url="/ui/campaigns?err=pack", status_code=303)
    c = Campaign(name=name, pack_id=pack.id)
    session.add(c)
    session.commit()
    return RedirectResponse(url="/ui/campaigns", status_code=303)


# --- Minimal stubs for remaining nav items -----------------------------


@router.get("/panic", response_class=HTMLResponse, dependencies=[UiAuthDep])
def panic(
    request: Request, session: Annotated[Session, SessDep]
) -> HTMLResponse:
    watches = list(
        session.execute(
            select(PanicWatch).order_by(PanicWatch.enabled.desc(), PanicWatch.created_at.desc())
        ).scalars()
    )
    alerts = list(
        session.execute(
            select(PanicAlert, Business, PanicWatch, ScoreSnapshot)
            .join(Business, Business.id == PanicAlert.business_id)
            .join(PanicWatch, PanicWatch.id == PanicAlert.watch_id)
            .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
            .order_by(
                # NEW alerts first, then by recency
                (PanicAlert.status != PanicAlertStatus.NEW).asc(),
                PanicAlert.created_at.desc(),
            )
            .limit(100)
        ).all()
    )

    active = sum(1 for w in watches if w.enabled)
    paused = sum(1 for w in watches if not w.enabled)
    new_count = sum(1 for a, *_ in alerts if a.status == PanicAlertStatus.NEW)
    today_count = sum(
        1
        for a, *_ in alerts
        if a.status == PanicAlertStatus.NEW
        and a.created_at.date() == datetime.now(UTC).date()
    )

    alert_items = []
    for alert, biz, watch, snap in alerts:
        alert_items.append(
            {
                "id": str(alert.id),
                "business_id": str(biz.id),
                "name": biz.name,
                "city": biz.city,
                "region": biz.region,
                "category": biz.category,
                "watch_name": watch.name,
                "reason": alert.reason,
                "status": alert.status.value,
                "created_at": alert.created_at,
                "score": snap.score if snap else None,
                "lead_class": snap.lead_class.value if snap else None,
            }
        )

    watch_items = [
        {
            "id": str(w.id),
            "name": w.name,
            "enabled": w.enabled,
            "region": w.region,
            "city": w.city,
            "category": w.category,
            "min_score": w.min_score,
            "lead_class_at_least": w.lead_class_at_least.value if w.lead_class_at_least else None,
            "last_evaluated_at": w.last_evaluated_at,
        }
        for w in watches
    ]

    return _TEMPLATES.TemplateResponse(
        request,
        "panic.html",
        {
            "nav_active": "panic",
            "alerts": alert_items,
            "watches": watch_items,
            "kpis": {
                "active": active,
                "paused": paused,
                "today": today_count,
                "awaiting": new_count,
            },
            "classes": [c.value for c in LeadClass],
        },
    )


@router.post("/panic/watches")
def panic_watch_create(
    session: Annotated[Session, SessDep],
    name: Annotated[str, Form()],
    city: Annotated[str | None, Form()] = None,
    region: Annotated[str | None, Form()] = None,
    category: Annotated[str | None, Form()] = None,
    min_score: Annotated[str | None, Form()] = None,
    lead_class_at_least: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    def _clean(v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    lc: LeadClass | None = None
    lca = _clean(lead_class_at_least)
    if lca:
        try:
            lc = LeadClass(lca)
        except ValueError:
            lc = None
    ms: int | None = None
    mss = _clean(min_score)
    if mss:
        try:
            ms = int(mss)
        except ValueError:
            ms = None

    watch = PanicWatch(
        name=name.strip(),
        enabled=True,
        city=_clean(city),
        region=_clean(region),
        category=_clean(category),
        min_score=ms,
        lead_class_at_least=lc,
    )
    session.add(watch)
    session.commit()
    inserted = evaluate_watch(session, watch)
    return RedirectResponse(url=f"/ui/panic?created={inserted}", status_code=303)


@router.post("/panic/watches/{watch_id}/toggle")
def panic_watch_toggle(
    watch_id: uuid.UUID, session: Annotated[Session, SessDep]
) -> RedirectResponse:
    w = session.get(PanicWatch, watch_id)
    if w is None:
        raise HTTPException(status_code=404, detail="watch not found")
    w.enabled = not w.enabled
    session.add(w)
    session.commit()
    return RedirectResponse(url="/ui/panic", status_code=303)


@router.post("/panic/watches/{watch_id}/delete")
def panic_watch_delete(
    watch_id: uuid.UUID, session: Annotated[Session, SessDep]
) -> RedirectResponse:
    w = session.get(PanicWatch, watch_id)
    if w is None:
        raise HTTPException(status_code=404, detail="watch not found")
    # delete alerts first (no cascade declared)
    session.execute(
        PanicAlert.__table__.delete().where(PanicAlert.watch_id == watch_id)
    )
    session.delete(w)
    session.commit()
    return RedirectResponse(url="/ui/panic", status_code=303)


@router.post("/panic/evaluate")
def panic_evaluate(session: Annotated[Session, SessDep]) -> RedirectResponse:
    inserted = evaluate_all_watches(session)
    return RedirectResponse(url=f"/ui/panic?evaluated={inserted}", status_code=303)


@router.post("/panic/alerts/{alert_id}/ack")
def panic_alert_ack(
    alert_id: uuid.UUID, session: Annotated[Session, SessDep]
) -> RedirectResponse:
    a = session.get(PanicAlert, alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail="alert not found")
    a.status = PanicAlertStatus.ACKNOWLEDGED
    session.add(a)
    session.commit()
    return RedirectResponse(url="/ui/panic", status_code=303)


@router.post("/panic/alerts/{alert_id}/dismiss")
def panic_alert_dismiss(
    alert_id: uuid.UUID, session: Annotated[Session, SessDep]
) -> RedirectResponse:
    a = session.get(PanicAlert, alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail="alert not found")
    a.status = PanicAlertStatus.DISMISSED
    session.add(a)
    session.commit()
    return RedirectResponse(url="/ui/panic", status_code=303)


@router.get("/map", response_class=HTMLResponse, dependencies=[UiAuthDep])
def map_view(
    request: Request,
    session: Annotated[Session, SessDep],
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 10.0,
    category: str | None = None,
) -> HTMLResponse:
    results: list[dict[str, object]] = []
    searched = lat is not None and lng is not None
    if searched:
        # Haversine distance in km. Earth radius 6371km. Avoids PostGIS dep.
        # distance = 2*R*asin(sqrt(sin²((lat2-lat1)/2) + cos(lat1)*cos(lat2)*sin²((lng2-lng1)/2)))
        distance_km = (
            2
            * 6371.0
            * func.asin(
                func.sqrt(
                    func.power(func.sin(func.radians(Business.latitude - lat) / 2), 2)
                    + func.cos(func.radians(lat))
                    * func.cos(func.radians(Business.latitude))
                    * func.power(func.sin(func.radians(Business.longitude - lng) / 2), 2)
                )
            )
        )
        stmt = (
            select(Business, ScoreSnapshot, distance_km.label("distance_km"))
            .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
            .where(Business.latitude.is_not(None), Business.longitude.is_not(None))
            .where(distance_km <= radius_km)
            .order_by(distance_km.asc())
            .limit(200)
        )
        if category:
            stmt = stmt.where(Business.category == category)
        for biz, snap, dist in session.execute(stmt).all():
            results.append(
                {
                    "id": str(biz.id),
                    "name": biz.name,
                    "city": biz.city,
                    "category": biz.category,
                    "phone": biz.phone,
                    "website": biz.website,
                    "latitude": float(biz.latitude) if biz.latitude is not None else None,
                    "longitude": float(biz.longitude) if biz.longitude is not None else None,
                    "distance_km": round(float(dist), 2),
                    "score": snap.score if snap else None,
                    "lead_class": snap.lead_class.value if snap else None,
                }
            )

    categories = [
        c
        for (c,) in session.execute(
            select(Business.category)
            .where(Business.category.is_not(None))
            .distinct()
            .order_by(Business.category)
        ).all()
    ]

    return _TEMPLATES.TemplateResponse(
        request,
        "map.html",
        {
            "nav_active": "map",
            "lat": lat,
            "lng": lng,
            "radius_km": radius_km,
            "category": category,
            "categories": categories,
            "results": results,
            "searched": searched,
        },
    )


@router.get("/dialer", response_class=HTMLResponse, dependencies=[UiAuthDep])
def dialer(
    request: Request, session: Annotated[Session, SessDep]
) -> HTMLResponse:
    rows = session.execute(
        select(CallTask, Business, ScoreSnapshot)
        .join(Business, Business.id == CallTask.business_id)
        .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
        .order_by(
            # active tasks (queued/in_progress) first; completed last
            CallTask.completed_at.asc().nullsfirst(),
            CallTask.priority.desc(),
            CallTask.created_at.asc(),
        )
    ).all()

    tasks = []
    counts = {s.value: 0 for s in CallTaskStatus}
    for task, biz, snap in rows:
        counts[task.status.value] += 1
        tasks.append(
            {
                "id": str(task.id),
                "name": biz.name,
                "business_id": str(biz.id),
                "phone": biz.phone,
                "city": biz.city,
                "category": biz.category,
                "status": task.status.value,
                "priority": task.priority,
                "outcome": task.outcome.value if task.outcome else None,
                "note": task.note,
                "score": snap.score if snap else None,
                "lead_class": snap.lead_class.value if snap else None,
                "updated_at": task.updated_at,
            }
        )

    unqueued_with_phone = int(
        session.execute(
            select(func.count(Business.id))
            .outerjoin(CallTask, CallTask.business_id == Business.id)
            .where(Business.phone.is_not(None))
            .where(CallTask.id.is_(None))
        ).scalar_one()
        or 0
    )

    return _TEMPLATES.TemplateResponse(
        request,
        "dialer.html",
        {
            "nav_active": "dialer",
            "tasks": tasks,
            "counts": counts,
            "unqueued_with_phone": unqueued_with_phone,
            "outcomes": [o.value for o in CallOutcome],
        },
    )


@router.post("/dialer/queue")
def dialer_queue(
    session: Annotated[Session, SessDep],
    limit: Annotated[int, Form()] = 20,
) -> RedirectResponse:
    """Enqueue up to `limit` top-scored businesses with a phone that aren't already queued."""
    stmt = (
        select(Business.id, func.coalesce(ScoreSnapshot.score, 0).label("priority"))
        .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
        .outerjoin(CallTask, CallTask.business_id == Business.id)
        .where(Business.phone.is_not(None))
        .where(CallTask.id.is_(None))
        .order_by(func.coalesce(ScoreSnapshot.score, 0).desc(), Business.created_at.asc())
        .limit(limit)
    )
    added = 0
    for business_id, priority in session.execute(stmt).all():
        session.add(
            CallTask(business_id=business_id, priority=int(priority), status=CallTaskStatus.QUEUED)
        )
        added += 1
    session.commit()
    return RedirectResponse(url=f"/ui/dialer?added={added}", status_code=303)


@router.post("/dialer/{task_id}/start")
def dialer_start(
    task_id: uuid.UUID, session: Annotated[Session, SessDep]
) -> RedirectResponse:
    task = session.get(CallTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    task.status = CallTaskStatus.IN_PROGRESS
    session.add(task)
    session.commit()
    return RedirectResponse(url="/ui/dialer", status_code=303)


@router.post("/dialer/{task_id}/outcome")
def dialer_outcome(
    task_id: uuid.UUID,
    outcome: Annotated[str, Form()],
    session: Annotated[Session, SessDep],
    note: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    task = session.get(CallTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    try:
        parsed = CallOutcome(outcome)
    except ValueError:
        return RedirectResponse(url="/ui/dialer?err=outcome", status_code=303)
    task.outcome = parsed
    task.note = (note or "").strip() or None
    task.completed_at = datetime.now(UTC)
    task.status = (
        CallTaskStatus.COMPLETED
        if parsed != CallOutcome.CALLBACK
        else CallTaskStatus.QUEUED
    )
    session.add(task)
    session.commit()
    return RedirectResponse(url="/ui/dialer", status_code=303)


@router.post("/dialer/{task_id}/skip")
def dialer_skip(
    task_id: uuid.UUID, session: Annotated[Session, SessDep]
) -> RedirectResponse:
    task = session.get(CallTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    task.status = CallTaskStatus.SKIPPED
    task.completed_at = datetime.now(UTC)
    session.add(task)
    session.commit()
    return RedirectResponse(url="/ui/dialer", status_code=303)

from fastapi import APIRouter, Depends

from ..config.database import db_session
from ..schemas.link_plan import LinkPlanInput, LinkPreviewInput
from ..services.auth import current_user, writer, admin
from ..services.link_export import plan_csv, active_plan_csv
from ..utils.serialization import row
from ..controllers.link_plans import LinkPlansController as C

router = APIRouter()


@router.get('/link-plans')
def list_plans(run_id: int | None = None, db=Depends(db_session), u=Depends(current_user)):
    return C.list(db, run_id)


@router.get('/link-plans/active')
def active(db=Depends(db_session), u=Depends(current_user)):
    plan = C.active(db)
    return row(plan) if plan else None


@router.post('/link-plans/preview')
def preview(data: LinkPreviewInput, db=Depends(db_session), u=Depends(current_user)):
    return C.preview(db, data)


@router.post('/link-plans')
def create(data: LinkPlanInput, db=Depends(db_session), u=Depends(writer)):
    return C.create(db, u, data)


@router.get('/link-plans/{plan_id}')
def detail(plan_id: int, db=Depends(db_session), u=Depends(current_user)):
    return row(C.get(db, plan_id))


@router.post('/link-plans/{plan_id}/approve')
def approve(plan_id: int, db=Depends(db_session), u=Depends(admin)):
    return C.approve(db, u, plan_id)


@router.get('/link-plans/{plan_id}/export')
def export(plan_id: int, db=Depends(db_session), u=Depends(current_user)):
    return plan_csv(db, plan_id)


@router.get('/link-plans-active/export')
def export_active(db=Depends(db_session), u=Depends(current_user)):
    return active_plan_csv(db)

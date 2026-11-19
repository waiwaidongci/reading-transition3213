"""章节链接名额方案的版本化与批准。

口径：
  - 候选链接 = 指定研究（TransitionRun）冻结样本中的全部会话内相邻边，没上榜也能选；
  - 每次名额/必留改版都新增不可变版本，配置 checksum 变化即新口径；
  - 旧草案在名额或必留改版后不能批准（只能批准最新版本，且必须仍可行）；
  - 并发批准同一版本只生效一次，切换失败（唯一约束冲突）回滚并保留旧生效版本。
"""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..models.link_plan import LinkPlan
from ..models.run import Run
from ..utils.serialization import row, now
from .link_allocator import allocate
from .audit import log

ACTIVE_KEY = 'ACTIVE'


def _completed_run(db, run_id):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(404, '未找到分析任务')
    if run.state != 'completed':
        raise HTTPException(409, '只能基于已完成研究的冻结样本配名额')
    return run


def _normalize_payload(data):
    """规整入参为可哈希、可比较的纯结构，并做基本形状校验。"""
    default_cap = int(data.default_cap)
    if default_cap < 0:
        raise HTTPException(422, '默认名额不能为负')

    quotas = {}
    if not isinstance(data.quotas, dict):
        raise HTTPException(422, '名额需为 {章节: {out, in}} 的对象')
    for chapter, q in data.quotas.items():
        if not isinstance(chapter, str) or not chapter.strip():
            raise HTTPException(422, '名额章节名不能为空')
        if not isinstance(q, dict) or 'out' not in q or 'in' not in q:
            raise HTTPException(422, '章节「%s」名额需同时给出 out 与 in' % chapter)
        try:
            out_v = int(q['out'])
            in_v = int(q['in'])
        except (TypeError, ValueError):
            raise HTTPException(422, '章节「%s」名额必须为非负整数' % chapter)
        if out_v < 0 or in_v < 0:
            raise HTTPException(422, '章节「%s」名额不能为负' % chapter)
        quotas[chapter.strip()] = {'out': out_v, 'in': in_v}

    required = []
    if not isinstance(data.required_links, list):
        raise HTTPException(422, '必留链接需为 [起章, 止章] 数组的列表')
    seen = set()
    for pair in data.required_links:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise HTTPException(422, '每条必留链接需是 [起章, 止章] 两元素数组')
        a, b = str(pair[0]).strip(), str(pair[1]).strip()
        if not a or not b:
            raise HTTPException(422, '必留链接章节名不能为空')
        if (a, b) not in seen:
            seen.add((a, b))
            required.append([a, b])
    return default_cap, quotas, required


def _checksum(run_id, default_cap, quotas, required):
    body = json.dumps({
        'run_id': run_id,
        'default_cap': default_cap,
        'quotas': quotas,
        'required_links': required,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def _build(db, run_id, default_cap, quotas, required):
    run = _completed_run(db, run_id)
    records = run.snapshot['records']
    try:
        result = allocate(records, quotas, required, default_cap)
    except ValueError as e:
        raise HTTPException(422, str(e))
    checksum = _checksum(run_id, default_cap, quotas, required)
    return run, result, checksum


def preview(db, data):
    """不入库的试算，用于页面实时查看候选、选中与名额占用。"""
    default_cap, quotas, required = _normalize_payload(data)
    _, result, checksum = _build(db, data.run_id, default_cap, quotas, required)
    result['config_checksum'] = checksum
    return result


def _next_version(db, run_id):
    last = db.scalar(select(LinkPlan).where(LinkPlan.run_id == run_id)
                     .order_by(LinkPlan.version.desc()).limit(1))
    return (last.version + 1) if last else 1


def create_plan(db, user, data):
    default_cap, quotas, required = _normalize_payload(data)
    run, result, checksum = _build(db, data.run_id, default_cap, quotas, required)
    plan = LinkPlan(
        run_id=run.id,
        version=_next_version(db, run.id),
        state='draft',
        default_cap=default_cap,
        quotas=quotas,
        required_links=required,
        config_checksum=checksum,
        result=result,
        conflicts=result.get('conflicts', []),
        author=user.email,
        created_at=now(),
    )
    db.add(plan)
    db.flush()
    log(db, user, 'link_plan.created', plan.id,
        'run#%s v%s feasible=%s' % (run.id, plan.version, result['feasible']))
    db.commit()
    return row(plan)


def list_plans(db, run_id=None):
    stmt = select(LinkPlan).order_by(LinkPlan.run_id.desc(), LinkPlan.version.desc())
    if run_id is not None:
        stmt = select(LinkPlan).where(LinkPlan.run_id == run_id).order_by(LinkPlan.version.desc())
    return [row(p) for p in db.scalars(stmt)]


def get_plan(db, plan_id):
    plan = db.get(LinkPlan, plan_id)
    if not plan:
        raise HTTPException(404, '未找到链接方案版本')
    return plan


def active_plan(db):
    return db.scalar(select(LinkPlan).where(LinkPlan.active_key == ACTIVE_KEY))


def approve_plan(db, user, plan_id):
    """原子批准：仅最新且可行的草案可批准；并发下唯一约束保证只生效一次。"""
    plan = get_plan(db, plan_id)
    if plan.state == 'approved' and plan.active_key == ACTIVE_KEY:
        raise HTTPException(409, '该版本已生效，无需重复批准')
    if plan.state == 'approved':
        raise HTTPException(409, '该版本已批准但未生效，请刷新后重试')

    # 旧草案：名额或必留改版后会出现更新版本，旧版不能批准
    latest = db.scalar(select(LinkPlan).where(LinkPlan.run_id == plan.run_id)
                       .order_by(LinkPlan.version.desc()).limit(1))
    if latest and latest.id != plan.id:
        raise HTTPException(409, '名额或必留链接已改版，旧草案不能批准；请批准最新版本 v%s' % latest.version)

    if not plan.result.get('feasible'):
        raise HTTPException(422, '必留链接超额冲突未解决，不能批准：' +
                            '；'.join(c.get('reason', '') for c in plan.conflicts))

    previous = active_plan(db)
    # 先撤下旧生效版本，再占位唯一键；任一失败整体回滚，保留旧版
    if previous is not None:
        previous.active_key = None
        previous.state = 'draft'
        previous.approved_by = ''
        previous.activated_at = ''
    plan.active_key = ACTIVE_KEY
    plan.state = 'approved'
    plan.approved_by = user.email
    plan.activated_at = now()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '同一版本的并发批准只生效一次，当前仍保留旧生效方案')
    log(db, user, 'link_plan.approved', plan.id,
        'run#%s v%s 生效；旧版 %s' % (plan.run_id, plan.version, previous.id if previous else '无'))
    db.commit()
    return row(plan)

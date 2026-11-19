import csv
import io

from fastapi import HTTPException
from fastapi.responses import Response

from .link_plans import active_plan, get_plan, ACTIVE_KEY


def _csv(rows, fields, filename):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, '') for k in fields})
    return Response('﻿' + buf.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="%s"' % filename})


def plan_csv(db, plan_id):
    plan = get_plan(db, plan_id)
    if plan.state != 'approved' or plan.active_key != ACTIVE_KEY:
        raise HTTPException(403, '仅当前生效版本可导出')
    fields = ['from', 'to', 'count', 'required']
    rows = [dict(r, required='是' if r.get('required') else '否') for r in plan.result['selected']]
    return _csv(rows, fields, 'link-plan-v%s.csv' % plan.version)


def active_plan_csv(db):
    plan = active_plan(db)
    if not plan:
        raise HTTPException(404, '还没有生效的链接方案')
    fields = ['from', 'to', 'count', 'required']
    rows = [dict(r, required='是' if r.get('required') else '否') for r in plan.result['selected']]
    return _csv(rows, fields, 'link-plan-active-v%s.csv' % plan.version)

"""端到端 HTTP 集成测试：SQLite + 直接构造已完成研究，覆盖链接方案全流程。"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = 'sqlite:///%s/test.db' % _tmp
os.environ['REDIS_URL'] = 'redis://127.0.0.1:6390/0'  # 不会真正连接
os.environ['SEED_DEMO'] = 'false'
os.environ['JWT_SECRET'] = 'test-secret'
os.environ['ARTIFACT_DIR'] = _tmp
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from src.main import app  # noqa: E402
from src.config.database import Session  # noqa: E402
from src.models.user import User  # noqa: E402
from src.models.source import Source  # noqa: E402
from src.models.record import Record  # noqa: E402
from src.models.run import Run  # noqa: E402
from src.models.link_plan import LinkPlan  # noqa: E402
from src.models.audit import Audit  # noqa: E402
from src.services.algorithm import calculate  # noqa: E402
from src.services.link_plans import ACTIVE_KEY  # noqa: E402
from src.utils.security import hash_password  # noqa: E402
from src.utils.serialization import now  # noqa: E402

PASS = 'Research2026!'
fails = []


def check(name, cond, extra=''):
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails.append(name)


def login(client, role):
    r = client.post('/auth/login', json={'email': '%s@reading-transition.demo' % role, 'password': PASS})
    check('login-%s' % role, r.status_code == 200)
    return r.json()['token']


def auth(tok):
    return {'Authorization': 'Bearer ' + tok}


with TestClient(app) as client:
    # 准备用户
    with Session() as db:
        for role in ('admin', 'analyst', 'viewer'):
            email = '%s@reading-transition.demo' % role
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(email=email, password_hash=hash_password(PASS), role=role))
        db.commit()

    admin_tok = login(client, 'admin')
    analyst_tok = login(client, 'analyst')
    viewer_tok = login(client, 'viewer')

    # 构造来源 + 样本（含一条次数很低、不会进 top_n 榜单的边）
    with Session() as db:
        src = Source(key='T-01', name='测试来源', filename='t.csv', description='d')
        db.add(src)
        db.flush()
        paths = ['序章>材料>工艺', '序章>材料>案例', '序章>案例>附录',
                 '材料>工艺>案例', '序章>材料', '材料>工艺', '工艺>附录']
        records = []
        for i, p in enumerate(paths):
            records.append(Record(source_id=src.id, reference='R-%02d' % i,
                                  values={'session': 'SES-%02d' % i, 'path': p}))
        db.add_all(records)
        db.flush()
        snap_records = [{'id': r.id, 'source_id': r.source_id, 'reference': r.reference,
                         'values': r.values} for r in records]
        result = calculate(snap_records, {'min_count': 1, 'top_n': 3})
        run = Run(source_id=src.id, name='已完成研究', state='completed',
                  parameters={'min_count': 1, 'top_n': 3},
                  snapshot={'source': {'id': src.id, 'name': src.name, 'filename': src.filename},
                            'records': snap_records},
                  result=result, created_at=now())
        db.add(run)
        db.commit()
        run_id = run.id
        topn_edges = {(r['from'], r['to']) for r in result['rows']}

    # 1. 试算：可行
    payload = {'run_id': run_id, 'default_cap': 1, 'quotas': {}, 'required_links': []}
    r = client.post('/link-plans/preview', json=payload, headers=auth(analyst_tok))
    check('preview-200', r.status_code == 200, str(r.status_code))
    prev = r.json()
    check('preview-feasible', prev['feasible'] is True)
    check('candidate-includes-non-topn',
          any((c['from'], c['to']) not in topn_edges for c in prev['candidates']),
          '候选 %d 条 vs 榜单 %d 条' % (len(prev['candidates']), len(topn_edges)))
    check('quota-usage-present', all('out_used' in q and 'in_used' in q for q in prev['quotas']))

    # 2. 必留超额冲突
    conflict_payload = {'run_id': run_id, 'default_cap': 0,
                        'quotas': {'序章': {'out': 1, 'in': 0}},
                        'required_links': [['序章', '材料'], ['序章', '案例']]}
    r = client.post('/link-plans/preview', json=conflict_payload, headers=auth(analyst_tok))
    check('preview-conflict-detected', r.status_code == 200 and r.json()['feasible'] is False
          and len(r.json()['conflicts']) > 0)

    # 3. 分析师保存草案 v1
    r = client.post('/link-plans', json=payload, headers=auth(analyst_tok))
    check('create-v1', r.status_code == 200 and r.json()['version'] == 1 and r.json()['state'] == 'draft',
          str(r.status_code))
    v1 = r.json()
    checksum_v1 = v1['config_checksum']

    # viewer 不能创建
    r = client.post('/link-plans', json=payload, headers=auth(viewer_tok))
    check('viewer-create-403', r.status_code == 403)

    # 4. viewer 不能批准；admin 批准 v1 生效
    r = client.post('/link-plans/%d/approve' % v1['id'], headers=auth(viewer_tok))
    check('viewer-approve-403', r.status_code == 403)
    r = client.post('/link-plans/%d/approve' % v1['id'], headers=auth(admin_tok))
    check('admin-approve-v1', r.status_code == 200 and r.json()['state'] == 'approved'
          and r.json()['active_key'] == ACTIVE_KEY, str(r.status_code))

    # 重复批准同版 → 409，且仍只有一个生效
    r = client.post('/link-plans/%d/approve' % v1['id'], headers=auth(admin_tok))
    check('double-approve-409', r.status_code == 409)
    with Session() as db:
        n_active = db.query(LinkPlan).filter(LinkPlan.active_key == ACTIVE_KEY).count()
        check('single-active', n_active == 1, 'active=%d' % n_active)

    # 5. 名额改版 → v2；旧 v1 不能批准（已批准但被切换前先测改版拦截）
    payload_v2 = dict(payload, quotas={'序章': {'out': 2, 'in': 2}}, default_cap=1)
    r = client.post('/link-plans', json=payload_v2, headers=auth(analyst_tok))
    check('create-v2', r.status_code == 200 and r.json()['version'] == 2)
    v2 = r.json()
    check('checksum-changed', v2['config_checksum'] != checksum_v1)
    # v1 此时是 approved+active；尝试再"批准"v1 应 409（已生效）
    r = client.post('/link-plans/%d/approve' % v1['id'], headers=auth(admin_tok))
    check('reapprove-active-v1-409', r.status_code == 409)

    # 6. 再建一个旧草案场景：v3 改版后，v2 成为旧草案，批准 v2 应被拒
    payload_v3 = dict(payload, default_cap=2)
    r = client.post('/link-plans', json=payload_v3, headers=auth(analyst_tok))
    v3 = r.json()
    check('create-v3', v3['version'] == 3)
    r = client.post('/link-plans/%d/approve' % v2['id'], headers=auth(admin_tok))
    check('stale-draft-v2-cannot-approve', r.status_code == 409, str(r.status_code))

    # 当前生效仍是 v1
    r = client.get('/link-plans/active', headers=auth(admin_tok))
    check('active-still-v1', r.json() and r.json()['id'] == v1['id'])

    # 7. 批准 v3 → 生效切换；v1 回退为草案保留
    r = client.post('/link-plans/%d/approve' % v3['id'], headers=auth(admin_tok))
    check('approve-v3-switch', r.status_code == 200 and r.json()['active_key'] == ACTIVE_KEY,
          str(r.status_code))
    with Session() as db:
        old = db.get(LinkPlan, v1['id'])
        check('old-v1-reverted-to-draft', old.state == 'draft' and old.active_key is None)
        cur = db.query(LinkPlan).filter(LinkPlan.active_key == ACTIVE_KEY).one()
        check('active-is-v3', cur.id == v3['id'])

    # 8. 冲突草案不能批准（422）
    r = client.post('/link-plans', json=conflict_payload, headers=auth(analyst_tok))
    check('create-conflict-draft-allowed', r.status_code == 200)  # 允许留存草案
    conflict_plan = r.json()
    check('conflict-plan-marked', conflict_plan['result']['feasible'] is False
          and len(conflict_plan['conflicts']) > 0)
    # 它是最新版本，批准应因不可行被 422
    r = client.post('/link-plans/%d/approve' % conflict_plan['id'], headers=auth(admin_tok))
    check('approve-conflict-422', r.status_code == 422, str(r.status_code))
    # 生效方案未受影响
    r = client.get('/link-plans/active', headers=auth(admin_tok))
    check('active-unchanged-after-conflict', r.json()['id'] == v3['id'])

    # 9. 导出生效 CSV
    r = client.get('/link-plans/%d/export' % v3['id'], headers=auth(viewer_tok))
    check('export-active-csv', r.status_code == 200 and 'text/csv' in r.headers['content-type'])
    r = client.get('/link-plans-active/export', headers=auth(viewer_tok))
    check('export-active-endpoint', r.status_code == 200)
    # 非生效版本导出被拒
    r = client.get('/link-plans/%d/export' % v1['id'], headers=auth(viewer_tok))
    check('export-non-active-403', r.status_code == 403)

    # 10. 列表与详情
    r = client.get('/link-plans?run_id=%d' % run_id, headers=auth(admin_tok))
    check('list-by-run', r.status_code == 200 and len(r.json()) >= 4)
    r = client.get('/link-plans/%d' % v3['id'], headers=auth(admin_tok))
    check('get-detail', r.status_code == 200 and r.json()['id'] == v3['id'])

    # 11. 审计事件
    with Session() as db:
        actions = {a.action for a in db.scalars(select(Audit)).all()}
    check('audit-link-events',
          {'link_plan.created', 'link_plan.approved'} <= actions, str(sorted(actions)))

    # 12. 唯一约束：手工插两个 ACTIVE 必触发 IntegrityError
    from sqlalchemy.exc import IntegrityError
    raised = False
    try:
        with Session() as db:
            dup = LinkPlan(run_id=run_id, version=99, state='approved', default_cap=1,
                           quotas={}, required_links=[], config_checksum='x',
                           result={'feasible': True}, conflicts=[], author='t',
                           active_key=ACTIVE_KEY, created_at=now())
            db.add(dup)
            db.commit()
    except IntegrityError:
        raised = True
    check('unique-active-constraint', raised)

    # 13. 并发批准同一版本只生效一次（两个独立会话并行）
    import threading
    # 先造一个全新可行草案 v4
    r = client.post('/link-plans', json=payload, headers=auth(analyst_tok))
    v4 = r.json()
    results = []

    def concurrent_approve(plan_id):
        try:
            with TestClient(app) as c2:
                tok = login(c2, 'admin')
                rr = c2.post('/link-plans/%d/approve' % plan_id, headers=auth(tok))
                results.append(rr.status_code)
        except Exception as e:  # noqa
            results.append('ERR:%s' % e)

    threads = [threading.Thread(target=concurrent_approve, args=(v4['id'],)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check('concurrent-approve-one-effect', sorted(results) == [200, 409], str(results))
    with Session() as db:
        n_active = db.query(LinkPlan).filter(LinkPlan.active_key == ACTIVE_KEY).count()
        check('still-single-active-after-concurrency', n_active == 1, str(n_active))
        check('v4-became-active', db.get(LinkPlan, v4['id']).active_key == ACTIVE_KEY)

print('\n==== TOTAL FAILS: %d ====' % len(fails))
sys.exit(1 if fails else 0)

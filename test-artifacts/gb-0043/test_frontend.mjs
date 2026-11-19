// 前端页面渲染冒烟测试：桩掉浏览器全局，校验 links 页在各角色/状态下不抛错且输出关键内容
globalThis.localStorage = {getItem: () => '', setItem() {}, removeItem() {}};
globalThis.location = {hash: '#links', port: '18247'};

const {research} = await import('../../frontend/src/stores/research.js');
const {session} = await import('../../frontend/src/stores/session.js');
const {linksPage} = await import('../../frontend/src/pages/links.js');

const fails = [];
const ok = (name, cond, extra = '') => {
  console.log(cond ? 'PASS' : 'FAIL', name, extra);
  if (!cond) fails.push(name);
};

const completedRun = {id: 7, name: '接续研究', state: 'completed'};
const plan = {
  id: 11, run_id: 7, version: 2, state: 'draft', default_cap: 1,
  quotas: {'序章': {out: 2, in: 1}}, required_links: [['序章', '材料']],
  config_checksum: 'abcdef1234567890', author: 'analyst@x.demo', approved_by: '',
  active_key: null, created_at: new Date().toISOString(),
  result: {
    feasible: true, selected_count: 3, total_count: 9,
    chapters: ['序章', '材料', '工艺'],
    quotas: [
      {chapter: '序章', out_cap: 2, in_cap: 1, out_used: 1, in_used: 0, custom: true},
      {chapter: '材料', out_cap: 1, in_cap: 1, out_used: 1, in_used: 2, custom: false},
      {chapter: '工艺', out_cap: 1, in_cap: 1, out_used: 1, in_used: 1, custom: false},
    ],
    selected: [
      {from: '序章', to: '材料', count: 4, required: true},
      {from: '材料', to: '工艺', count: 3, required: false},
      {from: '工艺', to: '材料', count: 2, required: false},
    ],
    candidates: [
      {from: '序章', to: '材料', count: 4}, {from: '序章', to: '工艺', count: 1},
      {from: '材料', to: '工艺', count: 3}, {from: '工艺', to: '材料', count: 2},
    ],
    conflicts: [],
  },
};

research.runs = [completedRun, {id: 9, name: '排队中', state: 'queued'}];
research.runId = 7;
research.linkPlans = [plan];
research.activeLink = null;

// 1. 分析师视图：含表单、试算按钮、候选/选中/名额表
session.user = {email: 'analyst@x.demo', role: 'analyst'};
let html = '';
try { html = linksPage(); } catch (e) { ok('analyst-render-no-throw', false, e.stack); }
ok('analyst-render-no-throw', typeof html === 'string' && html.length > 0);
ok('analyst-has-form', html.includes('link-form'));
ok('analyst-has-preview-btn', html.includes('link-preview'));
ok('analyst-shows-selected', html.includes('选中链接'));
ok('analyst-shows-quota-rows', html.includes('data-chapter="序章"'));
ok('analyst-shows-required-textarea', html.includes('序章&gt;材料') || html.includes('序章>材料'));
ok('analyst-no-approve-btn-for-draft-admin-only', !html.includes('data-approve'));
ok('analyst-lists-version', html.includes('研究 #7 · v2'));

// 2. 负责人视图：出现批准按钮
session.user = {email: 'admin@x.demo', role: 'admin'};
html = linksPage();
ok('admin-has-approve', html.includes('data-approve="11"'));

// 3. viewer：无表单，仍可看版本与生效导出
session.user = {email: 'viewer@x.demo', role: 'viewer'};
html = linksPage();
ok('viewer-no-form', !html.includes('id="link-form"'));
ok('viewer-still-ledger', html.includes('版本与批准账册'));

// 4. 生效版本：导出按钮 + 当前生效标签
const activePlan = {...plan, id: 12, version: 3, state: 'approved', active_key: 'ACTIVE',
  approved_by: 'admin@x.demo'};
research.linkPlans = [activePlan, plan];
research.activeLink = activePlan;
html = linksPage();
ok('active-tag-shown', html.includes('当前生效'));
ok('active-export-btn', html.includes('data-plan-export="12"'));
ok('active-banner', html.includes('当前生效：研究 #7 v3'));

// 5. 冲突草案：失败提示 + 不可批准 + 旧草案标签（用全新模块实例隔离本地试算状态）
const freshLinks = (await import('../../frontend/src/pages/links.js?t=conflict')).linksPage;
const conflictPlan = {...plan, id: 13, version: 4, active_key: null,
  result: {...plan.result, feasible: false, selected: [], selected_count: 0, total_count: 0,
    conflicts: [{from: '序章', to: '案例', reason: '起章「序章」必留出站 2 条，超出出名额 1'}]}};
research.linkPlans = [conflictPlan, activePlan, plan];
html = freshLinks();
ok('conflict-rendered', html.includes('必留链接超额冲突'));
ok('conflict-no-approve', !html.includes('data-approve="13"'));
ok('stale-draft-tag', html.includes('旧草案·改版后不可批准'));

// 6. 无已完成研究
research.runs = [{id: 9, state: 'queued', name: 'q'}];
html = linksPage();
ok('no-completed-run-notice', html.includes('还没有已完成研究'));

console.log('\n==== FRONTEND SMOKE FAILS: ' + fails.length + ' ====');
process.exit(fails.length ? 1 : 0);

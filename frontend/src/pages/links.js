import {research} from '../stores/research.js';
import {session} from '../stores/session.js';
import {linkPlansApi} from '../api/research.js';
import {download} from '../api/client.js';
import {runOptions} from '../components/common/business.js';
import {status} from '../components/common/status.js';
import {table} from '../components/common/table.js';
import {esc,localTime} from '../utils/format.js';
import {action,toast,bind} from '../hooks/actions.js';

// 页面本地状态：
//   preview 最近一次试算结果；runId 当前研究；
//   draft 按 run 保存最近一次试算/录入的完整名额口径，避免重渲染时输入框回退到旧版本值。
const ui={preview:null,runId:null,draft:{}};

function completedRuns(){return research.runs.filter(r=>r.state==='completed')}
function currentRunId(){return ui.runId||research.runId||completedRuns()[0]?.id||null}
function latestVersion(runId){const rows=research.linkPlans.filter(p=>p.run_id===runId).sort((a,b)=>b.version-a.version);return rows[0]||null}

function quotaInputs(preview,current,runId){
  const chapters=preview?preview.chapters:[];
  const draft=ui.draft[runId]?.quotas||{};
  const saved=current?.quotas||{};
  return chapters.map(c=>{
    const q=preview.quotas.find(x=>x.chapter===c)||{};
    const base=saved[c]||{};
    const out=draft[c]?.out??base.out??q.out_cap??1;
    const inV=draft[c]?.in??base.in??q.in_cap??1;
    return '<tr><td>'+esc(c)+'</td>'+
      '<td><input class="q-in" data-chapter="'+esc(c)+'" data-kind="out" type="number" min="0" value="'+out+'"></td>'+
      '<td><input class="q-in" data-chapter="'+esc(c)+'" data-kind="in" type="number" min="0" value="'+inV+'"></td>'+
      '<td class="used">'+(q.out_used??0)+' / '+(q.in_used??0)+'</td></tr>';
  }).join('')
}

function readForm(form){
  const defaultCap=Number(form.default_cap.value);
  const quotas={};
  form.querySelectorAll('.q-in').forEach(inp=>{
    const ch=inp.dataset.chapter,kind=inp.dataset.kind;
    quotas[ch]=quotas[ch]||{};quotas[ch][kind]=Number(inp.value);
  });
  const required=form.required_links.value.split('\n').map(s=>s.trim()).filter(Boolean)
    .map(line=>line.split('>').map(x=>x.trim())).filter(p=>p.length===2&&p[0]&&p[1]);
  const payload={run_id:Number(form.run_id.value),default_cap:defaultCap,quotas,required_links:required};
  ui.draft[payload.run_id]=payload;
  return payload
}

function previewBlock(p){
  if(!p)return '<div class="empty">填写名额与必留链接后点击“试算”，这里显示候选、选中名单与名额占用。</div>';
  const conflict=p.feasible?'':'<div class="failure"><h2>必留链接超额冲突</h2>'+p.conflicts.map(c=>'<p><b>'+esc(c.from)+' → '+esc(c.to)+'</b>：'+esc(c.reason)+'</p>').join('')+'<p class="fine">冲突未解决前不能保存为可批准方案。</p></div>';
  return conflict+
    '<div class="plan-metrics"><span>选中链接 <b>'+p.selected_count+'</b></span><span>接续次数总和 <b>'+p.total_count+'</b></span><span>候选（含未上榜） <b>'+p.candidates.length+'</b></span></div>'+
    '<h2>名额占用 <small>出/进 已用</small></h2>'+
    table(p.quotas.map(q=>({chapter:q.chapter,out_cap:q.out_cap,in_cap:q.in_cap,used:q.out_used+' / '+q.in_used,scope:q.custom?'录入':'默认'})),
      [{key:'chapter',label:'章节'},{key:'out_cap',label:'出名额'},{key:'in_cap',label:'进名额'},{key:'used',label:'出/进已用'},{key:'scope',label:'来源'}],{limit:100})+
    '<h2>选中链接名单 <small>先链接数最多，再次数总和最大，同分取起止章名最靠前</small></h2>'+
    table(p.selected.map(r=>({from:r.from,to:r.to,count:r.count,required:r.required?'必留':''})),
      [{key:'from',label:'起章'},{key:'to',label:'止章'},{key:'count',label:'接续次数'},{key:'required',label:'必留'}],{limit:200})+
    '<h2>全部候选链接 <small>没上榜也能选，共 '+p.candidates.length+' 条</small></h2>'+
    table(p.candidates, [{key:'from',label:'起章'},{key:'to',label:'止章'},{key:'count',label:'接续次数'}],{limit:12})
}

function versionLedger(){
  const rows=research.linkPlans;
  if(!rows.length)return '<div class="empty">还没有任何版本。完成一次研究并保存草案后，这里显示每版批准方案。</div>';
  return '<div class="ledger plan-ledger">'+rows.map(p=>{
    const active=p.active_key==='ACTIVE';
    const latest=latestVersion(p.run_id);
    const isLatest=latest&&latest.id===p.id;
    return '<article class="plan-version '+(active?'is-active':'')+'">'+
      '<header>'+status(p.state)+(active?'<span class="tag">当前生效</span>':'')+(!isLatest&&p.state==='draft'?'<span class="tag warn">旧草案·改版后不可批准</span>':'')+'<small>研究 #'+p.run_id+' · v'+p.version+'</small></header>'+
      '<p class="fine">选中 '+p.result.selected_count+' 条 · 次数总和 '+p.result.total_count+' · 默认名额 '+p.default_cap+' · 必留 '+p.required_links.length+' 条</p>'+
      '<p class="fine">口径 '+p.config_checksum.slice(0,12)+'… · '+esc(p.author)+' · '+localTime(p.created_at)+(p.approved_by?' · 批准 '+esc(p.approved_by):'')+'</p>'+
      '<footer><button class="secondary" data-view="'+p.id+'">查看方案</button>'+
      (p.state==='draft'&&isLatest&&p.result.feasible&&session.user.role==='admin'?'<button data-approve="'+p.id+'">批准并生效 ✓</button>':'')+
      (active?'<button class="secondary" data-plan-export="'+p.id+'">下载生效 CSV ↗</button>':'')+'</footer></article>';
  }).join('')+'</div>';
}

export function linksPage(){
  const runId=currentRunId();
  ui.runId=runId;
  const runs=completedRuns();
  const current=latestVersion(runId);
  // 初次进入且该 run 已有版本，直接展示最新版本结果；否则等待试算
  if(!ui.preview||ui.preview.run_id!==runId){
    ui.preview=current?{...current.result,run_id:current.run_id}:null;
  }
  const savedDefault=current?current.default_cap:1;
  const savedReq=(current?.required_links||[]).map(p=>p.join('>')).join('\n');
  const draft=ui.draft[runId];
  const defaultCap=draft?draft.default_cap:savedDefault;
  const reqText=draft?draft.required_links.map(p=>p.join('>')).join('\n'):savedReq;
  return '<section class="page-heading"><p class="eyebrow">06 / LINK QUOTA</p><h1>给章节配链接，名额之内取最优接续。</h1><p>候选取自指定研究冻结样本的全部会话内相邻边，没上榜也能选。先让链接数最多，再让接续次数总和最大，同分取起止章名排序最靠前的名单。</p></section>'+
  (runs.length?'<label class="compact">指定研究（已完成）<select id="link-run-select">'+runOptions(runs,runId)+'</select></label>':
    '<div class="failure">还没有已完成研究，请先在“分析配置”执行一次接续研究。</div>')+
  '<div class="split links-split"><section>'+
    (session.writable&&runs.length?'<form id="link-form" class="config-sheet">'+
      '<input type="hidden" name="run_id" value="'+runId+'">'+
      '<label>未录入章节默认进/出名额<input name="default_cap" type="number" min="0" value="'+defaultCap+'"></label>'+
      '<label>各章进出名额（仅录入需覆盖默认值的章节）<small>留作默认值即不占录入口径</small></label>'+
      '<div class="table-wrap qtable"><table><thead><tr><th>章节</th><th>出名额</th><th>进名额</th><th>出/进已用</th></tr></thead><tbody>'+
        (ui.preview?quotaInputs(ui.preview,current,runId):'<tr><td colspan="4" class="fine">选择研究并点击试算后加载章节</td></tr>')+
      '</tbody></table></div>'+
      '<label>必留链接（每行一条，用 &gt; 分隔起止章）<textarea name="required_links" rows="3" placeholder="序章&gt;材料">'+esc(reqText)+'</textarea></label>'+
      '<div class="form-actions"><button type="button" id="link-preview" class="secondary">试算名额</button><button type="submit">保存为新草案版本 →</button></div>'+
    '</form>':'')+
    '<div id="link-preview-box">'+previewBlock(ui.preview)+'</div>'+
  '</section><aside class="entry-sheet"><h2>版本与批准账册</h2>'+
    (research.activeLink?'<p class="fine">当前生效：研究 #'+research.activeLink.run_id+' v'+research.activeLink.version+'，选中 '+research.activeLink.result.selected_count+' 条链接。</p>':'<p class="fine">尚无生效方案。</p>')+
    versionLedger()+
    (research.activeLink?'<button class="secondary" id="active-export">下载当前生效 CSV ↗</button>':'')+
  '</aside></div>';
}

export function bindLinks(refresh){
  bind('#link-run-select','change',async e=>{ui.runId=Number(e.target.value);research.runId=ui.runId;ui.preview=null;await refresh()});
  bind('#link-preview','click',async()=>{
    const form=document.getElementById('link-form');if(!form)return;
    try{const p=await linkPlansApi.preview(readForm(form));p.run_id=Number(form.run_id.value);ui.preview=p;await refresh();toast(p.feasible?'试算完成，名额口径可行':'存在必留超额冲突')}
    catch(e){toast(e.message,true)}
  });
  action('#link-form',async form=>{
    const payload=readForm(form);
    const p=await linkPlansApi.preview(payload);
    if(!p.feasible){toast('必留链接超额冲突未解决，不能保存可批准方案',true);ui.preview=p;await refresh();return}
    await linkPlansApi.create(payload);ui.preview=null;await refresh();toast('已保存为新草案版本；旧草案保留但不可批准');
  });
  for(const b of document.querySelectorAll('[data-approve]'))b.onclick=async()=>{
    try{await linkPlansApi.approve(b.dataset.approve);ui.preview=null;await refresh();toast('已批准并切换为当前生效方案')}catch(e){toast(e.message,true)}
  };
  for(const b of document.querySelectorAll('[data-view]'))b.onclick=async()=>{
    try{const plan=await linkPlansApi.get(b.dataset.view);ui.runId=plan.run_id;research.runId=plan.run_id;ui.preview={...plan.result,run_id:plan.run_id};await refresh()}catch(e){toast(e.message,true)}
  };
  for(const b of document.querySelectorAll('[data-plan-export]'))b.onclick=async()=>{
    try{await download('/link-plans/'+b.dataset.planExport+'/export','link-plan-'+b.dataset.planExport+'.csv')}catch(e){toast(e.message,true)}
  };
  bind('#active-export','click',async()=>{try{await download('/link-plans-active/export','link-plan-active.csv')}catch(e){toast(e.message,true)}});
}

/* AI 工作台：短会话 + 持久化分析页。每轮请求独立状态，旧请求不能覆盖新会话。 */
window.DSH_AUTH = {token:()=>localStorage.getItem('dsh_token')||'demo-token-region-a'};
window.DSH_CHAT = (()=>{
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const headers=()=>({'Authorization':'Bearer '+window.DSH_AUTH.token(),'Content-Type':'application/json'});
  const sessionKey=()=> 'dsh_session_'+window.DSH_AUTH.token();
  let sessionId=null,active=null,generation=0,lastAnalysis=null,lastQuestion='',lastContext={},origin='view-radar',restoring=false;
  const content=()=>$('analysis-content');
  const context=()=>{const c=window.DSH_CHAT_CONTEXT||{};return {scode:c.scode||null,year:c.year||null,view:c.view||'radar'};};
  function notice(text){$('report-state').textContent=text;}
  function show(){
    const current=document.querySelector('.view.on');
    if(current && current.id!=='view-assistant') origin=current.id;
    switchView('view-assistant');
  }
  function onWorkspace(){return $('view-assistant').classList.contains('on');}
  function clearRoute(){if(location.hash.startsWith('#analysis=')) history.replaceState(null,'',location.pathname+location.search);}
  function route(id){history.replaceState(null,'',location.pathname+location.search+'#analysis='+encodeURIComponent(id));}
  function addMessage(role,text){
    const m=document.createElement('div');m.className='chat-msg '+role;
    const who=document.createElement('div');who.className='who';who.textContent=role==='user'?'你':'数智链海';
    const b=document.createElement('div');b.className='bubble';b.textContent=text;
    m.append(who,b);$('chat-body').appendChild(m);$('chat-body').scrollTop=$('chat-body').scrollHeight;return b;
  }
  function messageLink(b,id,question){const a=document.createElement('button');a.type='button';a.className='message-open';a.textContent='展开分析页面 ↗';a.onclick=()=>openSaved(id,question);b.appendChild(a);}
  function intro(){
    content().innerHTML='<div class="report-empty"><div class="core-orb" aria-hidden="true"></div><span class="eyebrow">ASK · EXPLORE · ACT</span><h2>让线索，变成可核查的判断。</h2><p>提出一个问题，助手会把企业事实、服务建议与依据整理在这里。每一个光球，都通向可以展开的详情。</p><div class="empty-steps"><span>01 提出问题</span><span>02 查看判断</span><span>03 点开依据</span></div></div>';
    notice('准备就绪');$('report-copy').disabled=true;
  }
  function syncMeta(c){$('chat-meta').textContent=c.scode?`默认参考 ${c.scode}${c.year?' · '+c.year+' 年':''}`:'全库探索 · 可指定企业、年度或行业';}
  function busy(value){
    $('chat-send').disabled=value||restoring;$('chat-cancel').hidden=!value;
    $('chat-retry').disabled=value||restoring||!lastQuestion;
    const dot=document.querySelector('#chat-toggle .dot');if(dot)dot.classList.toggle('busy',value);
    $('analysis-workspace').setAttribute('aria-busy',String(value));
  }
  function stop(reason='已停止生成，可重新生成或提出新问题。'){
    const run=active;if(!run)return;
    active=null;generation++;
    if(run.requestId)fetch(API+'/api/v1/chat/requests/'+encodeURIComponent(run.requestId)+'/cancel',{method:'POST',headers:run.headers}).catch(()=>{});
    run.controller.abort();run.message.textContent=reason;notice(reason);busy(false);
    content().querySelector('.report-empty')?.classList.remove('is-thinking');
  }
  function newConversation(){
    stop();generation++;restoring=false;sessionId=null;lastAnalysis=null;lastQuestion='';lastContext={};
    window.DSH_CHAT_CONTEXT={scode:null,year:null,view:'assistant'};
    localStorage.removeItem(sessionKey());clearRoute();window.DSHDrawer.close();
    $('chat-body').replaceChildren();$('chat-input').value='';intro();syncMeta(context());busy(false);show();$('chat-input').focus();
  }
  function textHTML(text){
    // 仅排版文字，不执行模型给出的HTML、链接或脚本。
    const lines=String(text||'').split('\n');let html='',list='';
    const inline=t=>esc(t).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
    const close=()=>{if(list){html+='</'+list+'>';list='';}};
    for(const line of lines){
      if(!line.trim()){close();continue;}
      const item=/^\s*(?:[-*•]|\d+[.、)])\s+(.+)$/.exec(line);
      if(item){if(!list){list='ul';html+='<ul>';}html+='<li>'+inline(item[1])+'</li>';continue;}
      close();const heading=/^#{1,6}\s+(.+)$/.exec(line);
      html+=heading?'<h3>'+inline(heading[1])+'</h3>':'<p>'+inline(line)+'</p>';
    }close();return html;
  }
  function refButtons(refs){return (refs||[]).map((r,i)=>`<button type="button" class="refmark" data-ref="${esc(r)}">依据 ${i+1} ↗</button>`).join('');}
  function blockHTML(b){return `<div class="blk ${esc(['fact','hypothesis','product','checklist','note'].includes(b.kind)?b.kind:'note')}" data-refs="${esc((b.refs||[]).join('|'))}">${textHTML(b.text)}${refButtons(b.refs)}</div>`;}
  function bindRefs(){content().querySelectorAll('.refmark[data-ref]').forEach(b=>b.onclick=()=>window.DSHDrawer.open(b.dataset.ref,'依据详情'));}
  function renderReport(payload,question,focus=true){
    lastAnalysis=payload;const c=payload.context||{},blocks=payload.answer_blocks||[],recs=payload.recommendations||[],qs=payload.questions||[];
    lastContext=c;syncMeta(c);window.DSH_CHAT_CONTEXT={...c,view:context().view};
    const engine=payload.engine==='rules-demo'?'本地规则演示':payload.engine==='coze'?'Coze 分析':payload.engine==='langgraph'?'AI 分析':'已保存分析';
    content().innerHTML=`<div class="report-eyebrow"><span>${esc(engine)}</span>${c.year?`<span>${esc(c.year)} 数据年度</span>`:''}${c.coname||c.scode?`<span>${esc(c.coname||c.scode)}</span>`:''}</div><h1 class="report-title" id="report-title" tabindex="-1">${esc(question||'已保存的分析结果')}</h1><p class="report-intro">先阅读判断，再点开光球核查依据。结果已按本次分析保存。</p>`;
    const groups=[['fact','事实与核心发现'],['hypothesis','分析与判断'],['product','服务思路'],['checklist','需要进一步确认']];let number=0;
    const section=(title,html)=>`<section class="report-section"><h2><span class="section-index">${String(++number).padStart(2,'0')}</span>${title}</h2>${html}</section>`;
    const first=blocks.filter(b=>b.kind==='fact');
    if(first.length)content().insertAdjacentHTML('beforeend',section('事实与核心发现',first.map(blockHTML).join('')));
    const constellation=document.createElement('div');constellation.className='evidence-constellation';
    constellation.innerHTML='<p>探索本次分析的依据 · 点击光球展开</p>';
    const orbsAll=payload.orbs||[];
    if(orbsAll.length){
      window.DSHOrbs.render(constellation,orbsAll,content());
      /* 有依据但没有任何可回溯原文证据时明确说明，避免用户以为"这个系统没有证据功能" */
      if(!orbsAll.some(o=>o.kind==='evidence'))
        constellation.insertAdjacentHTML('beforeend','<p class="orb-hint">本次分析未附可回溯的原文证据（可能为辖区名单类问题，或该企业当年暂无披露信号）。</p>');
    }
    else constellation.innerHTML='<p>本次没有可展开的依据；可补充企业、年份或更具体的问题。</p>';
    content().appendChild(constellation);
    for(const [kind,label] of groups.slice(1)){const bs=blocks.filter(b=>b.kind===kind);if(bs.length)content().insertAdjacentHTML('beforeend',section(label,bs.map(blockHTML).join('')));}
    if(recs.length){
      const cards=recs.map((r,i)=>{
        const orb=(payload.orbs||[]).find(o=>o.ref_id===r.product_ref);
        const key=(r.product_ref||'').split(':').pop();
        const name=window.DSHOrbs.PRODUCT_CN[key] || (orb && !/^[a-z_]+$/.test(orb.label||'')?orb.label:null) || '候选服务 '+(i+1);
        const state={eligible:'条件已满足',not_eligible:'当前不适用',unknown:'条件待确认'}[r.eligibility]||'条件待确认';
        return `<div class="service-card"><span class="service-state">建议 ${String(i+1).padStart(2,'0')} · ${state}</span><h3>${esc(name)}</h3><p>${esc(r.reason)}</p>${(r.missing_conditions||[]).length?`<p class="muted">需确认：${esc(r.missing_conditions.join('、'))}</p>`:''}${refButtons([r.product_ref,...(r.evidence_refs||[])].filter(Boolean))}</div>`;
      }).join('');content().insertAdjacentHTML('beforeend',section('服务建议',`<div class="service-grid">${cards}</div>`));
    }
    if(qs.length)content().insertAdjacentHTML('beforeend',section('下一步，带着这些问题沟通',`<ol class="question-list">${qs.map(q=>`<li>${esc(q.text)}</li>`).join('')}</ol>`));
    const notes=[...blocks.filter(b=>!['fact','hypothesis','product','checklist'].includes(b.kind)).map(b=>b.text),...(payload.warnings||[])];
    if(notes.length)content().insertAdjacentHTML('beforeend',`<details class="report-notes" ${!first.length&&!recs.length?'open':''}><summary>补充说明与使用边界（${notes.length}）</summary>${notes.map(t=>`<p>${esc(t)}</p>`).join('')}</details>`);
    content().insertAdjacentHTML('beforeend',`<div class="report-actions"><button class="work-btn primary" id="report-follow">继续追问 ↗</button><button class="work-btn" id="report-brief">生成访前简报</button>${c.scode?'<button class="work-btn" id="report-company">企业详情</button>':''}<button class="work-btn" id="report-print">打印 / PDF</button></div>`);
    bindRefs();$('report-follow').onclick=()=>{$('chat-input').focus();$('chat-panel').scrollIntoView({block:'start',behavior:'smooth'});};
    $('report-brief').onclick=()=>briefing(payload);
    if($('report-company'))$('report-company').onclick=()=>window.DSHOpenCompany(c.scode,c.year);
    $('report-print').onclick=()=>window.print();$('report-copy').disabled=false;
    notice(payload.status==='partial'?'已整理 · 部分内容需核实':'已整理 · 点击光球查看依据');
    if(onWorkspace())route(payload.analysis_id);
    if(focus && onWorkspace()){$('report-title').focus({preventScroll:true});$('analysis-workspace').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}
  }
  async function briefing(payload){
    const gen=generation;const b=$('report-brief');b.disabled=true;b.textContent='正在整理简报…';
    try{const r=await fetch(API+'/api/v1/briefings',{method:'POST',headers:headers(),body:JSON.stringify({analysis_id:payload.analysis_id})});if(!r.ok)throw Error();const result=await r.json();if(gen===generation)window.DSHShowBriefing(result);}
    catch(e){b.textContent='生成失败，点击重试';}finally{b.disabled=false;}
  }
  async function openSaved(id,question){
    stop();const gen=++generation;restoring=true;busy(false);show();notice('正在恢复分析…');
    content().innerHTML='<div class="report-message">正在读取已保存的分析页面…</div>';
    try{
      const r=await fetch(API+'/api/v1/analyses/'+encodeURIComponent(id),{headers:headers()});if(!r.ok)throw Error(r.status===404?'该结果不存在或当前身份无权查看。':'暂时无法读取结果，请重试。');
      const a=await r.json();if(gen!==generation)return;
      const payload={...a.draft,analysis_id:a.analysis_id,engine:a.engine,status:a.status};
      lastQuestion=question||a.question||'';lastContext=payload.context||{};renderReport(payload,lastQuestion);
      syncMeta(lastContext);window.DSH_CHAT_CONTEXT={...lastContext,view:'assistant'};busy(false);
    }catch(e){if(gen!==generation)return;errorPage(e.message,()=>openSaved(id,question));}
    finally{if(gen===generation){restoring=false;busy(false);}}
  }
  function errorPage(message,retry){
    content().innerHTML=`<div class="report-message"><h2>这次没有完成</h2><p>${esc(message)}</p><button class="work-btn" id="report-error-retry">重新尝试</button></div>`;
    $('report-error-retry').onclick=retry;notice('未完成 · 可以重试');$('report-copy').disabled=true;
  }
  function live(run){return active===run && generation===run.gen;}
  function updatePhase(run,text){if(!live(run))return;notice(text);const p=content().querySelector('.thinking-note');if(p)p.textContent=text;}
  function handle(ev,run){
    if(!live(run))return;
    const d=ev.data;
    if(ev.event==='request_started'){
      run.requestId=d.request_id;sessionId=d.session_id;localStorage.setItem(sessionKey(),sessionId);syncMeta(d.context||{});return;
    }
    if(d.request_id && d.request_id!==run.requestId)return;
    if(ev.event==='status')updatePhase(run,{querying:'正在查找相关事实与依据',analyzing:'正在结合资料分析你的问题',validating:'正在核对年份与引用，整理分析页面'}[d.phase]||'正在整理结果…');
    if(ev.event==='answer_delta')run.blocks.push({kind:d.kind||'fact',text:d.text||'',refs:d.refs||[]});
    if(ev.event==='orbs_ready')run.orbs=d.orbs||[];
    if(ev.event==='analysis_ready')run.result={...d,answer_blocks:run.blocks,orbs:run.orbs};
    if(ev.event==='clarification'){
      run.clarified=true;run.message.textContent=d.message||'请补充信息';
      content().innerHTML=`<div class="report-message"><h2>再明确一点，分析会更准确。</h2><p>${esc(d.message||'请补充企业、年份或你想了解的问题。')}</p><div class="clarify-options" id="clarify-options"></div></div>`;
      for(const o of d.options||[]){const b=document.createElement('button');b.type='button';b.textContent=o.label||o.scode;b.onclick=()=>{if(o.scode)window.DSH_CHAT_CONTEXT={scode:o.scode,year:o.year||null,view:'assistant'};send('分析企业 '+(o.scode||o.label));};$('clarify-options').appendChild(b);}
    }
    if(ev.event==='error')throw Error(d.message||'服务暂时不可用');
    if(ev.event==='done')run.done=true;
  }
  async function send(message,unused,forcedContext){
    if(active||restoring)return;
    const msg=(typeof message==='string'?message:$('chat-input').value).trim();if(!msg)return;
    const page=forcedContext||context();show();clearRoute();window.DSHDrawer.close();
    $('chat-input').value='';lastQuestion=msg;lastContext=page;lastAnalysis=null;$('report-copy').disabled=true;
    addMessage('user',msg);
    const run={gen:++generation,controller:new AbortController(),headers:headers(),requestId:null,blocks:[],orbs:[],done:false,message:addMessage('assistant','正在分析，结果将在右侧整理呈现…')};
    active=run;busy(true);
    content().innerHTML=`<div class="report-empty is-thinking"><div class="core-orb" aria-hidden="true"></div><span class="eyebrow">CONNECTING THE EVIDENCE</span><h2>正在梳理你的问题</h2><p>${esc(msg)}</p><div class="loading-track" aria-hidden="true"></div><p class="thinking-note" role="status">正在查找相关事实与依据</p><p>依据核对完成后，可点击的光球会逐个浮现。</p></div>`;
    notice('开始分析');
    try{
      const response=await fetch(API+'/api/v1/chat/stream',{method:'POST',headers:run.headers,signal:run.controller.signal,body:JSON.stringify({session_id:sessionId,client_request_id:'crid_'+crypto.randomUUID(),message:msg,page_context:page})});
      if(!response.ok||!response.body)throw Error(response.status===401?'登录状态失效，请切换有效身份后重试。':'服务暂时不可用（'+response.status+'），请重试。');
      await window.DSHStream.consume(response.body,event=>handle(event,run));
      if(!live(run))return;
      if(!run.done)throw Error('连接提前中断，未完成的结果没有作为最终分析展示。');
      if(run.result){renderReport(run.result,msg);run.message.textContent=(run.blocks.find(b=>b.kind==='fact')?.text||'本次分析已整理为独立页面。').slice(0,150);messageLink(run.message,run.result.analysis_id,msg);}
      else if(run.clarified)notice('等待补充信息');
      else throw Error('没有收到完整分析，请重试。');
    }catch(e){
      if(!live(run))return;run.controller.abort();run.message.textContent=e.message||'生成失败';errorPage(run.message.textContent,retryLast);
    }finally{if(active===run){active=null;busy(false);}}
  }
  function retryLast(){if(lastQuestion)send(lastQuestion,false,lastContext);}
  function contextChanged(){stop('企业或年度已切换，本轮已停止。');syncMeta(context());}
  async function restore(){
    const sid=localStorage.getItem(sessionKey());if(!sid)return;
    const gen=++generation;restoring=true;busy(false);
    try{
      const r=await fetch(API+'/api/v1/chat/sessions/'+encodeURIComponent(sid),{headers:headers()});
      if(!r.ok){if(gen===generation&&(r.status===404||r.status===401))localStorage.removeItem(sessionKey());return;}
      const s=await r.json();if(gen!==generation)return;
      sessionId=s.session_id;$('chat-body').replaceChildren();
      for(const m of s.messages||[]){const b=addMessage(m.role==='user'?'user':'assistant',m.content);if(m.role==='assistant'&&m.analysis_id)messageLink(b,m.analysis_id,m.question);if(m.role==='user')lastQuestion=m.content;}
      lastContext=s.context||{};syncMeta(lastContext);
      if(!context().scode)window.DSH_CHAT_CONTEXT={...lastContext,view:context().view};
    }catch(e){if(gen===generation)notice('历史对话暂时无法恢复；仍可开始新对话。');}
    finally{if(gen===generation){restoring=false;busy(false);}}
  }
  async function copyReport(){
    if(!lastAnalysis)return;
    const a=lastAnalysis;const text=[lastQuestion,...(a.answer_blocks||[]).map(b=>b.text),'服务建议',...(a.recommendations||[]).map(r=>r.reason),'待沟通问题',...(a.questions||[]).map(q=>q.text),...(a.warnings||[])].join('\n\n');
    try{await navigator.clipboard.writeText(text);notice('结果已复制');}catch(e){notice('浏览器不允许自动复制，可选中结果文字复制。');}
  }
  async function init(){
    intro();syncMeta(context());
    $('chat-toggle').onclick=show;$('btn-assistant').onclick=show;$('chat-close').onclick=()=>switchView(origin);
    $('chat-new').onclick=newConversation;$('chat-explore').onclick=newConversation;$('chat-retry').onclick=retryLast;$('report-copy').onclick=copyReport;
    $('chat-form').onsubmit=e=>{e.preventDefault();send();};$('chat-cancel').onclick=()=>stop();
    $('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}});
    document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('chat-input').value=b.dataset.prompt;$('chat-input').focus();});
    $('chat-identity').value=window.DSH_AUTH.token();
    $('chat-identity').onchange=async e=>{stop();generation++;restoring=false;localStorage.setItem('dsh_token',e.target.value);sessionId=null;lastAnalysis=null;lastQuestion='';$('chat-body').replaceChildren();intro();clearRoute();window.DSHDrawer.close();await restore();};
    const id=location.hash.startsWith('#analysis=')?decodeURIComponent(location.hash.slice(10)):null;
    const restoringPromise=restore();const gen=generation;await restoringPromise;if(gen!==generation)return;if(id)await openSaved(id);busy(false);
  }
  document.addEventListener('DOMContentLoaded',init);
  return {send,contextChanged,restore,newConversation,show,get lastAnalysis(){return lastAnalysis;}};
})();

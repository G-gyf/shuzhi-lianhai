/* 每个真实引用保留独立光球；不再把同名依据折叠成不可访问的首条。 */
window.DSHOrbs = (() => {
  const KIND_CN = {evidence:'原文依据',product:'产品依据',analysis:'服务方案',compare:'企业对比',company:'企业详情',profile:'企业画像',checklist:'待核实事项',regional:'地区资料'};
  /* 产品中文名：必须与后端 rules/products.json 的 catalog 逐键对齐（15 项）。
     产品球的 orb.label 是产品键（如 project_loan），证据球的 orb.label 已是中文文案。
     历史问题：旧表 15 条里有 7 个键后端已不存在（死代码）、7 个后端存在的键缺失，
     导致 clearing_path / project_loan 等直接以英文键显示给客户经理。
     维护提醒：新增产品时同步此表，最好改由 catalog 自动生成。 */
  const PRODUCT_CN = {
    account_setup:'账户方案', settlement_arch:'跨境结算架构', guarantee_prequal:'保函预授信',
    settlement:'跨境人民币结算', clearing_path:'清算行网络接入', hedging:'汇率避险',
    treasury:'工银全球司库', project_loan:'境外项目贷款', neibaowaidai:'内保外贷',
    ma_loan:'跨境并购融资', bid_bond:'投标保函', performance_bond:'履约保函',
    advance_bond:'预付款保函', offshore:'离岸账户（OSA/NRA）', offshore_cny:'离岸人民币融资',
  };
  /* 兜底链：产品键→中文；纯英文键查不到映射时退回类型中文名，绝不把英文键显示给用户 */
  const label = (o) => PRODUCT_CN[o.label]
    || (/^[a-z0-9_]+$/.test(o.label || '') ? '' : o.label)
    || KIND_CN[o.kind] || '查看依据';
  function button(o, index, report) {
    const b = document.createElement('button'); b.type='button';
    const kind = Object.hasOwn(KIND_CN,o.kind) ? o.kind : 'evidence';
    /* supplemented=true 表示该球是后端在引擎未给出合法引用时补挂的确定性证据，
       不是模型引用——必须让客户经理一眼看出来，避免误当成模型结论的依据。 */
    const sup = !!o.supplemented;
    b.className='orb kind-'+kind+' lit'+(sup?' supplemented':'');
    b.style.setProperty('--arrival',Math.min(index,8)*110+'ms');
    b.dataset.ref=o.ref_id || '';
    b.dataset.supplemented=sup?'1':'';
    b.setAttribute('aria-label',(sup?'后端补充依据：':'')+label(o)+'：'+(o.summary||KIND_CN[kind]));
    b.title=(sup?'【后端补充】':'')+(o.summary || label(o));
    for (const [cls,text] of [['orb-sphere',''],['orb-label',label(o)],['orb-kind',KIND_CN[kind]+(sup?' · 后端补充':'')]]) {
      const el=document.createElement('span');el.className=cls;el.textContent=text;
      if (cls==='orb-sphere') el.setAttribute('aria-hidden','true');b.appendChild(el);
    }
    b.disabled = ['pending','blocked'].includes(o.state) || (!o.ref_id && kind!=='checklist');
    b.onclick=()=>{
      b.classList.add('viewed');
      if(o.ref_id) window.DSHDrawer.open(o.ref_id,label(o));
      else window.DSHDrawer.openList(o,label(o));
      if(report) report.querySelectorAll('.blk').forEach(el=>el.classList.toggle('hl-ref',(el.dataset.refs||'').split('|').includes(o.ref_id)));
    };
    return b;
  }
  function render(container,orbs,report) {
    const box=document.createElement('div');box.className='orb-bar';
    const list=orbs||[];list.slice(0,5).forEach((o,i)=>box.appendChild(button(o,i,report)));
    if(list.length>5) {
      const extra=document.createElement('div');extra.className='orb-bar';extra.hidden=true;
      list.slice(5).forEach((o,i)=>extra.appendChild(button(o,i,report)));
      const toggle=document.createElement('button');toggle.className='work-btn orb-more';toggle.type='button';
      toggle.textContent='展开其余 '+(list.length-5)+' 个依据';toggle.setAttribute('aria-expanded','false');
      toggle.onclick=()=>{extra.hidden=!extra.hidden;toggle.setAttribute('aria-expanded',String(!extra.hidden));toggle.textContent=extra.hidden?'展开其余 '+(list.length-5)+' 个依据':'收起更多依据';};
      box.append(toggle,extra);
    }
    container.appendChild(box);return box;
  }
  return {render,KIND_CN,label,PRODUCT_CN};
})();

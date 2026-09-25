/* 每个真实引用保留独立光球；不再把同名依据折叠成不可访问的首条。 */
window.DSHOrbs = (() => {
  const KIND_CN = {evidence:'原文依据',product:'产品依据',analysis:'服务方案',compare:'企业对比',company:'企业详情',profile:'企业画像',checklist:'待核实事项',regional:'地区资料'};
  const PRODUCT_CN = {account_setup:'账户方案',settlement:'跨境结算',rmb_settlement:'跨境人民币结算',hedging:'汇率避险',bid_bond:'投标保函',advance_bond:'保函预授信',performance_bond:'履约保函',advance_payment_bond:'预付款保函',offshore:'境外账户',treasury:'跨境司库',trade_finance:'贸易融资',project_finance:'项目融资',export_credit:'出口信贷',ma_finance:'并购融资',lc:'信用证'};
  const label = (o) => PRODUCT_CN[o.label] || o.label || KIND_CN[o.kind] || '查看依据';
  function button(o, index, report) {
    const b = document.createElement('button'); b.type='button';
    const kind = Object.hasOwn(KIND_CN,o.kind) ? o.kind : 'evidence';
    b.className='orb kind-'+kind+' lit'; b.style.setProperty('--arrival',Math.min(index,8)*110+'ms');
    b.dataset.ref=o.ref_id || '';
    b.setAttribute('aria-label',label(o)+'：'+(o.summary||KIND_CN[kind]));
    b.title=o.summary || label(o);
    for (const [cls,text] of [['orb-sphere',''],['orb-label',label(o)],['orb-kind',KIND_CN[kind]]]) {
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

/* Anonymization (gatitod/mask.py): the on/off switch of the chat and the editor of
   placeholders. With it on, what you type leaves for Claude with consistent placeholders;
   the conversation is always shown with the real values ("As sent" shows what the AI saw). */
function anonOn(){return stored('gatito-anon')==='1'}
function setAnon(on){store('gatito-anon',on?'1':null);paintAnon();
  toast(on?'Anonymize on: real names leave as placeholders':'Anonymize off: what you type leaves as is')}
function paintAnon(){
  const on=anonOn();
  document.querySelectorAll('[data-anon-tog]').forEach(b=>b.setAttribute('aria-pressed',on));
  document.querySelectorAll('#composer,#r-box').forEach(b=>b.classList.toggle('anon',on));
}
document.addEventListener('click',e=>{
  if(e.target.closest('[data-anon-tog]')){e.preventDefault();setAnon(!anonOn())}
  else if(e.target.closest('[data-anon-cfg]')){e.preventDefault();openMask()}
});

const MASK={data:null};
// the placeholder a kind suggests: tenant-alpha, rg-bravo, a fake GUID...
function suggestFake(kind,used){
  const k=(MASK.data.kinds.find(x=>x.id===kind)||MASK.data.kinds.at(-1)).fake;
  const taken=s=>used.has(s.toLowerCase());
  for(let n=1;n<2000;n++){
    const w=MASK.data.nato[(n-1)%26]+(n>26?Math.ceil(n/26):'');
    const s=k.replace('{w}',w).replace('{guid}','00000000-0000-4000-b000-'+n.toString(16).padStart(12,'0'))
      .replace('{aws}','8888'+String(n).padStart(8,'0'));
    if(!taken(s))return s;
  }
  return '';
}
// rows of the starter list: the usual cloud and DevOps names, real value left for you
const TEMPLATE=['tenant','tenant_id','subscription','subscription_id','client','domain','rg','cluster',
  'namespace','keyvault','storage','registry','vnet','app','devops_org','devops_project','repo','pipeline'];

function maskRow(e){
  const kinds=MASK.data.kinds.map(k=>`<option value="${k.id}"${k.id===e.kind?' selected':''}>${esc(k.label)}</option>`).join('');
  return `<tr${e.on===false?' class="off"':''}>
    <td><input type="checkbox" class="m-on"${e.on===false?'':' checked'} title="Use this row"></td>
    <td><select class="m-kind">${kinds}</select></td>
    <td><input class="m-real" value="${esc(e.real||'')}" placeholder="Real value (e.g. Contoso)" spellcheck="false" autocomplete="off"></td>
    <td><input class="m-fake" value="${esc(e.fake||'')}" placeholder="Placeholder" spellcheck="false" autocomplete="off"
      ${e.auto?'data-auto="1"':''}></td>
    <td><button class="btn ghost icon m-del" type="button" title="Delete row" aria-label="Delete row">${ICON('x')}</button></td></tr>`;
}
function maskRows(){
  return [...document.querySelectorAll('#m-rows tr')].map(tr=>({tr,kind:tr.querySelector('.m-kind').value,
    real:tr.querySelector('.m-real').value.trim(),fake:tr.querySelector('.m-fake').value.trim(),
    on:tr.querySelector('.m-on').checked}));
}
function usedFakes(except){return new Set(maskRows().filter(r=>r.tr!==except).map(r=>r.fake.toLowerCase()).filter(Boolean))}
function wireRow(tr){
  const fake=tr.querySelector('.m-fake'), kind=tr.querySelector('.m-kind');
  const fill=()=>{if(!fake.value.trim()||fake.dataset.auto){fake.value=suggestFake(kind.value,usedFakes(tr));fake.dataset.auto='1'}};
  kind.onchange=fill;
  tr.querySelector('.m-real').oninput=()=>{if(!fake.value.trim())fill()};
  fake.oninput=()=>delete fake.dataset.auto;
  tr.querySelector('.m-on').onchange=e=>tr.classList.toggle('off',!e.target.checked);
  tr.querySelector('.m-del').onclick=()=>{tr.remove();maskCount()};
}
function addRow(e,top){
  const tb=$('#m-rows'); tb.insertAdjacentHTML(top?'afterbegin':'beforeend',maskRow(e));
  const tr=top?tb.firstElementChild:tb.lastElementChild; wireRow(tr); maskCount(); return tr;
}
function maskCount(){const n=maskRows().filter(r=>r.real).length;$('#m-n').textContent=n?`${n}`:''}

async function openMask(){
  const d0=await api('/api/mask').catch(()=>null);
  if(!d0)return toast('Could not load the anonymization settings',true);
  MASK.data=d0;
  const learned=d0.learned.map(x=>`<tr><td class="k">${esc(x.kind)}</td><td class="mono">${esc(x.real.length>80?x.real.slice(0,80)+'…':x.real)}</td>
    <td class="mono">${esc(x.fake)}</td><td><button class="btn ghost icon" data-forget="${esc(x.real)}" title="Forget" aria-label="Forget">${ICON('x')}</button></td></tr>`).join('');
  const draft=($('#r-text')&&$('#r-text').value)||$('#q').value||'';
  const d=dialog(`<div class="m-h"><h3>Anonymize</h3>
      <button class="btn ${anonOn()?'primary':'ghost'} m-sw" id="m-sw" type="button">${anonOn()?'On':'Off'} in the chat</button></div>
    <p>With it on, what you send to Claude leaves with placeholders (the same real value always gets the same one) and the
      conversation is shown to you with the real values. Only what you type is masked: what an agent reads from your
      files or commands reaches it as it is.</p>
    <details class="m-sec" open><summary>Your list <b id="m-n"></b></summary>
      <div class="m-tools"><button class="btn ghost" id="m-add" type="button">${ICON('plus')}Add</button>
        <button class="btn ghost" id="m-tpl" type="button" title="Adds empty rows for tenants, subscriptions, resource groups, clusters, vaults, repos…">${ICON('plus')}Cloud and DevOps rows</button>
        <span class="spacer"></span><input id="m-q" type="search" placeholder="Filter" autocomplete="off"></div>
      <div class="m-tbl"><table><thead><tr><th></th><th>Kind</th><th>Real value</th><th>Placeholder</th><th></th></tr></thead>
        <tbody id="m-rows"></tbody></table></div>
      <div class="fine">Case is kept both ways (ACME → TENANT-ALPHA) and it is replaced inside names
        (<code>rg-acme-prod</code>, <code>api.acme.com</code>) but not in the middle of a word (<code>acmeprod</code>).
        Keep the placeholder valid for that kind of resource (storage: lowercase letters and digits only).</div></details>
    <details class="m-sec"><summary>Automatic detection</summary>
      <div class="m-det">${d0.detectors.map(x=>`<label class="check"><input type="checkbox" data-det="${x.id}"${d0.detect[x.id]?' checked':''}>${esc(x.label)}</label>`).join('')}</div>
      <label class="fine" for="m-keep">Never mask (one per line), besides public DNS, Azure built-in roles and well-known app ids:</label>
      <textarea id="m-keep" rows="3" spellcheck="false">${esc(d0.keep.join('\n'))}</textarea></details>
    <details class="m-sec"><summary>Learned by the detectors <b>${d0.learned.length||''}</b></summary>
      ${learned?`<div class="m-tbl"><table><tbody>${learned}</tbody></table></div>
        <div class="m-tools"><span class="fine">If you forget them, the chats that used them can no longer show the real values.</span>
        <span class="spacer"></span><button class="btn ghost danger" id="m-forget" type="button">Forget all</button></div>`
        :'<div class="fine">Nothing yet: IPs, GUIDs, e-mails, secrets… appear here once they are sent.</div>'}</details>
    <details class="m-sec"${draft?' open':''}><summary>Try it</summary>
      <textarea id="m-test" rows="4" placeholder="Paste text: see what would leave for Claude, or paste an answer with placeholders to see the real values" spellcheck="false">${esc(draft)}</textarea>
      <div class="m-tools"><button class="btn ghost" id="m-prev" type="button">What would leave</button>
        <button class="btn ghost" id="m-unm" type="button">Put back the real values</button><span class="spacer"></span>
        <button class="btn ghost" id="m-copy" type="button" hidden>${ICON('copy')}Copy</button></div>
      <pre class="m-out" id="m-out" hidden></pre></details>
    <div class="acts"><button class="btn ghost" id="m-cancel" type="button">Close</button>
      <button class="btn primary" id="m-save" type="button">Save</button></div>`,'wide mask-dlg');
  d0.entries.forEach(e=>addRow(e));
  if(!d0.entries.length)addRow({kind:'tenant'});
  maskCount();
  $('#m-sw').onclick=()=>{setAnon(!anonOn());const b=$('#m-sw');b.textContent=`${anonOn()?'On':'Off'} in the chat`;
    b.className=`btn ${anonOn()?'primary':'ghost'} m-sw`};
  $('#m-add').onclick=()=>addRow({kind:'tenant'},true).querySelector('.m-real').focus();
  $('#m-tpl').onclick=()=>{
    const have=new Set(maskRows().filter(r=>!r.real).map(r=>r.kind));
    TEMPLATE.filter(k=>!have.has(k)).reverse().forEach(k=>{const tr=addRow({kind:k},true);tr.querySelector('.m-kind').onchange()});
    $('#m-rows').closest('.m-tbl').scrollTop=0;
  };
  $('#m-q').oninput=e=>{const q=e.target.value.toLowerCase();
    maskRows().forEach(r=>r.tr.hidden=!!q&&!`${r.real} ${r.fake} ${r.kind}`.toLowerCase().includes(q))};
  d.querySelectorAll('[data-forget]').forEach(b=>b.onclick=async()=>{
    await api('/api/mask/forget',{real:b.dataset.forget}); b.closest('tr').remove()});
  const fa=$('#m-forget'); if(fa)fa.onclick=async()=>{
    d.close();
    if(!await confirmBox('Forget what was learned','The detected values (IPs, GUIDs, e-mails, secrets…) and their placeholders are deleted. '+
      'Conversations that used them will show the placeholders instead of the real values.','Forget all'))return openMask();
    await api('/api/mask/forget',{}); toast('Forgotten'); openMask();
  };
  const out=(t,found)=>{const o=$('#m-out');o.hidden=false;$('#m-copy').hidden=false;o.textContent=t;
    if(found)o.insertAdjacentHTML('beforeend',`<span class="m-found">${found.length
      ?found.map(f=>`${esc(f.real.length>50?f.real.slice(0,50)+'…':f.real)} → ${esc(f.fake)}`).join('\n'):'Nothing to mask.'}</span>`)};
  // the preview uses the list as it is on screen, even if not saved yet
  $('#m-prev').onclick=async()=>{
    const entries=maskRows().filter(r=>r.real&&r.fake).map(({kind,real,fake,on})=>({kind,real,fake,on}));
    const r=await api('/api/mask/preview',{text:$('#m-test').value,entries});
    if(r.err)return toast(r.err,true);
    out(r.text,r.found)};
  $('#m-unm').onclick=async()=>{const r=await api('/api/mask/unmask',{text:$('#m-test').value});out(r.text)};
  $('#m-copy').onclick=()=>copy($('#m-out').firstChild?.textContent||'');
  $('#m-cancel').onclick=()=>d.close();
  $('#m-save').onclick=async()=>{
    const rows=maskRows(), empty=rows.filter(r=>!r.real).length;
    const entries=rows.filter(r=>r.real).map(({kind,real,fake,on})=>({kind,real,fake,on}));
    const detect={}; d.querySelectorAll('[data-det]').forEach(c=>detect[c.dataset.det]=c.checked);
    const keep=$('#m-keep').value.split('\n').map(s=>s.trim()).filter(Boolean);
    const r=await api('/api/mask/save',{entries,detect,keep}).catch(e=>({ok:false,err:e.message}));
    if(!r.ok)return toast(r.err||'Could not save',true);
    toast(`Saved · ${entries.length} ${entries.length===1?'value':'values'}${empty?` (${empty} empty ${empty===1?'row':'rows'} left out)`:''}`);
    if(CUR)loadConvo(false);
  };
}

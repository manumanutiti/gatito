/* "Sessions" view: agent list, conversation, reply and composer. */
/* ---------------- list ---------------- */
const SECTIONS=[
  ['waiting','Waiting for you'],['working','Working'],['recent','Finished today'],
  ['terminal','Open in terminal'],['archive','Archive']];
const STATE_TXT={waiting:'Waiting for your reply',working:'Working',recent:'Finished',
  terminal:'Open in terminal',archive:'Archived',history:'Earlier conversation'};

function note(a){
  if(a.ui==='blocked'&&a.needs)return{t:a.needs,cls:'ask'};
  if(a.result)return{t:a.result};
  if(a.detail)return{t:a.detail};
  if(a.intent)return{t:a.intent};
  return null;
}
function row(a){
  const n=note(a);
  return `<button class="row${CUR&&CUR.key===a.key?' sel-on':''}" data-key="${esc(a.key)}">
    <span class="st ${a.group}"></span>
    <span class="row-main">
      <span class="row-top"><span class="row-title">${esc(a.name||a.key)}</span>
        <span class="row-time">${ago(a.updatedAt)}</span></span>
      <span class="row-sub">${pdot(proj(a).split(' · ')[0])}${esc(proj(a))}${profileTag(a.profile,a.profileTitle,a.readOnly)}</span>
      ${n?`<span class="row-note ${n.cls||''}">${esc(n.t)}</span>`:''}
    </span></button>`;
}
function renderList(){
  const L=$('#groups'); const openArch=L.querySelector('details[open]')||(CUR&&CUR.group==='archive');
  let html='';
  for(const[g,label]of SECTIONS){
    const items=AGENTS.filter(a=>a.group===g);
    if(g==='archive'){
      if(!items.length)continue;
      const bg=items.filter(a=>a.kind==='background').length;
      html+=`<details class="sec archive"${openArch?' open':''}><summary class="sec-h">${ICON('chev')}
        ${label}<span class="n">${items.length}</span><span class="spacer"></span>
        ${bg?`<button class="btn ghost" id="purge" type="button">Empty</button>`:''}</summary>
        ${items.map(row).join('')}</details>`;
      continue;
    }
    if(!items.length&&g!=='waiting')continue;
    html+=`<div class="sec"><div class="sec-h">${label}<span class="n">${items.length||''}</span></div>
      ${items.length?items.map(row).join(''):'<div class="empty">Nothing pending.</div>'}</div>`;
  }
  L.innerHTML=html;
  L.querySelectorAll('.row[data-key]').forEach(b=>b.onclick=()=>select(b.dataset.key));
  const p=$('#purge'); if(p)p.onclick=e=>{e.preventDefault();e.stopPropagation();purge()};
}

/* ---------------- detail ---------------- */
function select(key){
  const a=AGENTS.find(x=>x.key===key)||HIST.items.find(x=>x.key===key); if(!a)return;
  CUR=a; CONVO={key,msgs:[],showAll:false};
  $('#app').classList.add('open');
  renderDetail(true); renderList();
  loadConvo(true);
}
function closeDetail(){
  CUR=null; $('#app').classList.remove('open');
  $('#detail').innerHTML=''; clearAtt('r');
  renderList(); renderHome();
}
// no session open: greeting and the composer in the center, like AI web apps
function renderHome(){
  const h=new Date().getHours();
  $('#hello').textContent=(h<6?'Good evening':h<12?'Good morning':h<19?'Good afternoon':'Good evening');
  const w=AGENTS.filter(a=>a.group==='waiting'), k=AGENTS.filter(a=>a.group==='working').length;
  const sub=$('#hello-sub');
  sub.innerHTML=w.length?`<a href="#${esc(w[0].key)}">${w.length===1?'One session is waiting for you':`${w.length} sessions are waiting for you`}</a>${k?`, and ${k} ${k===1?'is':'are'} still working.`:'.'}`
    :k?`${k===1?'One agent is':`${k} agents are`} still working. What else shall we do?`:'What shall we do today?';
}
function renderDetail(full){
  const a=CUR; if(!a)return;
  const hist=a.kind==='history', bg=a.kind==='background'||hist;  // history ones can be continued too
  const acts=[];
  if(bg&&a.ui==='working')acts.push(`<button class="btn ghost" data-act="stop" title="Stop" aria-label="Stop">${ICON('stop')}<span class="btn-t">Stop</span></button>`);
  // no project: it can move on to touch one without losing the conversation
  if(a.kind==='background'&&META.chats&&(a.cwd||'').startsWith(META.chats+'/'))
    acts.push(`<button class="btn ghost" data-act="attach" title="Open a project in this conversation" aria-label="Open project">${ICON('folder')}<span class="btn-t">Open project</span></button>`);
  const pzb=wbButton(a); if(pzb)acts.push(pzb);
  if(!hist)acts.push(a.group==='archive'
    ?`<button class="btn ghost" data-act="unhide" title="Restore" aria-label="Restore">${ICON('restore')}<span class="btn-t">Restore</span></button>`
    :`<button class="btn ghost" data-act="hide" title="Archive" aria-label="Archive">${ICON('archive')}<span class="btn-t">Archive</span></button>`);
  if(a.kind==='background')acts.push(`<button class="btn ghost danger" data-act="remove" title="Delete" aria-label="Delete">${ICON('trash')}<span class="btn-t">Delete</span></button>`);

  const head=`<div class="d-head">
    <button class="btn ghost d-back" data-act="back" aria-label="Back">${ICON('back')}</button>
    <button class="btn ghost icon show-list" data-show-list type="button" title="Show the list ([)" aria-label="Show the list">${ICON('sidebar')}</button>
    <div class="d-titles"><h2 class="d-title">${esc(a.name||a.key)}</h2>
      <div class="d-meta"><span>${STATE_TXT[a.group]}</span><span>${ago(a.updatedAt)}</span>
        ${a.live?`<span class="live" title="Connected to gatito through the mod: messages reach it without resuming it">● live</span>`:''}
        <span class="mono x">${esc(home(a.cwd))}</span>
        ${a.model?`<span class="x">model: ${esc(label('models',a.model))}</span>`:''}
        ${profileTag(a.profile,a.profileTitle,a.readOnly,true)}
        ${a.mode?`<span class="x">permissions: ${esc(label('modes',a.mode))}</span>`:''}
        ${a.effort?`<span class="x">effort: ${esc(a.effort)}</span>`:''}
        ${a.worktreeBranch?`<span class="mono x">branch: ${esc(a.worktreeBranch)}</span>`:''}
        ${a.tokens?`<span class="x">${Number(a.tokens).toLocaleString('en-GB')} tokens</span>`:''}</div></div>
    <div class="d-actions">${acts.join('')}</div></div>`;

  // what it asks you (permission, question) goes at the bottom, after the conversation: that's where it's needed
  let ask='';
  if(a.perm)ask=permCard(a.perm);
  else if(a.ui==='blocked'&&a.needs)ask=`<div class="callout ask"><div class="lbl">It asks you</div><div class="txt">${esc(a.needs)}</div></div>`;
  let call='';
  if(a.result)call+=`<div class="callout res"><div class="lbl">Result</div><div class="txt">${esc(a.result)}</div></div>`;
  call+=sumCallout(a);

  let reply;
  if(bg||a.live){
    const DIAG='Explain the latest to me with a diagram (mermaid block).';
    const INFRA='Make an architecture diagram of the infrastructure we are talking about, with the official icons '+
      '(skill "diagram", ~/gatito/bin/diagram) and with --png so it can be pasted into documentation.';
    const MERGE='Commit your changes on this branch and then integrate them into the main branch of the original repo '+
      '(local merge, no push). If there are conflicts, stop and tell me which ones.';
    // applied on resume: they start with what the session has now
    const ropts=`<span class="r-opts">
      <select class="sel" id="r-model" title="Model from this turn on">${selOpts('models',a.model,a.model?null:'Model: same')}</select>
      <select class="sel" id="r-mode" title="${a.readOnly?'Read-only session: the mode can\'t be raised':'Permissions from this turn on'}"${a.readOnly?' disabled':''}>${selOpts('modes',a.mode||META.defaults.mode)}</select>
      <select class="sel" id="r-effort" title="Effort from this turn on">${selOpts('efforts',a.effort)}</select></span>`;
    // in a terminal one none of that can be changed: only the mailbox
    const chips=`<div class="chips">${a.suggestedReply&&a.ui==='blocked'
      ?`<button class="chip" data-chip="${esc(a.suggestedReply)}">${esc(a.suggestedReply)}</button>`:''}
      <button class="chip" data-chip="${esc(DIAG)}">Ask for a diagram</button>
      <button class="chip" data-chip="${esc(INFRA)}">Infra diagram</button>
      ${a.worktreeBranch?`<button class="chip" data-chip="${esc(MERGE)}">Merge into the main branch</button>`:''}${bg?ropts:''}</div>`;
    const ph=hist?'Continue this conversation in the background…':a.perm?'Reason to deny, or an instruction…'
      :a.live==='working'?'Send an instruction (it reaches it when it finishes what it is doing)…':a.live?'Write to this session…'
      :a.ui==='blocked'?'Reply…':a.ui==='done'?'Continue this session with a new instruction…':'Send an instruction (interrupts and resumes)…';
    reply=`<div class="reply"><div class="reply-in">${chips}<div class="reply-box" id="r-box">
      <div class="att" id="r-att" hidden></div>
      <button class="btn ghost icon" id="r-attach" type="button" title="Attach image (or paste it)" aria-label="Attach image">${ICON('image')}</button>
      <textarea id="r-text" rows="1" placeholder="${ph}" enterkeyhint="send"></textarea>
      <button class="btn primary" id="r-send" aria-label="Send">${ICON('send')}</button>
      <input type="file" id="r-file" accept="image/*" multiple hidden></div></div></div>`;
  }else{
    reply=`<div class="reply"><div class="reply-in reply-note">Session open in a terminal: reply from there.</div></div>`;
  }

  if(full){
    clearAtt('r');
    $('#detail').innerHTML=head+`<div class="d-body" id="d-body"><div class="d-inner">
      <div id="d-call">${call}</div><div id="d-convo"></div><div id="d-typing"></div><div id="d-ask">${ask}</div></div></div>`+reply;
    wireDetail(); wbDraw(); loadWhiteboard(true);
  }else{
    // light refresh: header and alerts, without touching what you're typing
    const h=$('#detail .d-head'); if(h){h.outerHTML=head;}
    $('#d-call').innerHTML=call;
    // a card already on screen isn't repainted: you'd lose what you're choosing
    const box=$('#d-ask');
    if(box&&!(a.perm&&box.querySelector(`[data-pid="${a.perm.id}"]`))&&box.innerHTML!==ask){
      const body=$('#d-body'), atBottom=body.scrollHeight-body.scrollTop-body.clientHeight<120;
      box.innerHTML=ask;
      if(ask&&atBottom)body.scrollTop=body.scrollHeight;   // make sure what it asks is visible
    }
    wireHead();
  }
  paintTyping();
}
function wireHead(){
  $('#detail').querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>act(b.dataset.act));
  $('#detail').querySelectorAll('[data-perm]').forEach(b=>b.onclick=()=>decidePerm(b.dataset.perm));
  $('#detail').querySelectorAll('[data-ask]').forEach(b=>b.onclick=answerAsk);
  $('#detail').querySelectorAll('.ask-opt').forEach(b=>b.onclick=()=>{
    const box=b.closest('.ask-q');
    if(box.dataset.multi!=='1')box.querySelectorAll('.ask-opt.on').forEach(x=>x!==b&&x.classList.remove('on'));
    b.classList.toggle('on');
  });
  const sb=$('#sum-btn'); if(sb)sb.onclick=()=>summarize();
}

/* ---------------- summary (Haiku, only if you ask) ---------------- */
let SUM={key:null,text:null,stale:false,busy:false};
function sumCallout(a){
  if(!a.transcript)return `<div class="callout sum"><div class="lbl">Summary</div><div class="txt loading">No conversation yet.</div></div>`;
  const s=SUM.key===a.key?SUM:{text:null};
  const btn=s.busy?'':`<button class="btn ghost sum-btn" id="sum-btn" type="button">${s.text?(s.stale?'Update':'Redo'):'Summarize'}</button>`;
  const txt=s.busy?'Summarizing with Haiku…':s.text||'Press "Summarize" if you want a summary (Haiku writes it).';
  return `<div class="callout sum"><div class="lbl">Summary${s.stale&&!s.busy?' · the conversation has moved on':''}${btn}</div>
    <div class="txt${s.text&&!s.busy?'':' loading'}" id="sum">${esc(txt)}</div></div>`;
}
function paintSum(){const a=CUR, box=$('#d-call .callout.sum'); if(!a||!box)return;
  box.outerHTML=sumCallout(a); wireHead()}
async function summarize(){
  const a=CUR; if(!a||!a.transcript)return; const key=a.key;
  SUM={key,text:SUM.key===key?SUM.text:null,stale:false,busy:true}; paintSum();
  const s=await api('/api/summary?transcript='+encodeURIComponent(a.transcript)+'&sid='+a.sessionId).catch(()=>null);
  if(SUM.key!==key)return;
  SUM={key,text:s&&s.summary||SUM.text,stale:false,busy:false}; paintSum();
  if(!s)toast('Could not summarize',true);
}

/* ---------------- permissions (they arrive through the gatito mod) ---------------- */
function permRule(sug){
  // the rules Claude proposes for "always allow", exactly as it would save them
  const rules=(sug||[]).filter(u=>u.type==='addRules'&&u.behavior==='allow')
    .flatMap(u=>u.rules.map(r=>r.ruleContent?`${r.toolName}(${r.ruleContent})`:r.toolName));
  const dirs=(sug||[]).filter(u=>u.type==='addDirectories').flatMap(u=>u.directories||[]);
  const modes=(sug||[]).filter(u=>u.type==='setMode').map(u=>`mode "${label('modes',u.mode)}" in this session`);
  return [...rules,...dirs.map(d=>'folder '+home(d)),...modes].join(', ');
}
function permBody(p){
  const i=p.input&&typeof p.input==='object'?p.input:{};
  if(i.command)return `<pre class="perm-code">${esc(i.command)}</pre>${i.description?`<div class="perm-desc">${esc(i.description)}</div>`:''}`;
  if(i.file_path){
    const body=i.content??i.new_string??'';
    return `<div class="mono perm-path">${esc(home(i.file_path))}</div>${body?`<pre class="perm-code">${esc(String(body).slice(0,1200))}</pre>`:''}`;
  }
  if(i.url)return `<div class="mono perm-path">${esc(i.url)}</div>`;
  const j=JSON.stringify(p.input,null,2)||'';
  return j&&j!=='{}'?`<pre class="perm-code">${esc(j.slice(0,1200))}</pre>`:'';
}
function askCard(p){
  const qs=(p.input&&p.input.questions)||[];
  return `<div class="callout ask perm" data-pid="${esc(p.id)}"><div class="lbl">It asks you${qs.length>1?` · ${qs.length} questions`:''}</div>
    ${qs.map((q,i)=>`<div class="ask-q" data-q="${i}" data-multi="${q.multiSelect?1:0}">
      <div class="ask-t">${q.header?`<span class="ask-h">${esc(q.header)}</span>`:''}${esc(q.question)}${q.multiSelect?' <span class="ask-m">(you can pick several)</span>':''}</div>
      <div class="ask-opts">${(q.options||[]).map(o=>`<button class="ask-opt" type="button" data-opt="${esc(o.label)}">
        <span class="ask-l">${esc(o.label)}</span>${o.description?`<span class="ask-d">${esc(o.description)}</span>`:''}</button>`).join('')}</div>
      <input class="ask-other" placeholder="Another answer (type it here)"></div>`).join('')}
    <div class="perm-btns"><button class="btn primary" data-ask>Answer</button></div></div>`;
}
async function answerAsk(){
  const a=CUR; if(!a||!a.perm)return;
  const qs=(a.perm.input&&a.perm.input.questions)||[], answers={};
  $('#d-ask').querySelectorAll('.ask-q').forEach(box=>{
    const q=qs[+box.dataset.q]; if(!q)return;
    const other=box.querySelector('.ask-other').value.trim();
    const sel=[...box.querySelectorAll('.ask-opt.on')].map(b=>b.dataset.opt);
    const v=other||sel.join(', '); if(v)answers[q.question]=v;
  });
  if(!Object.keys(answers).length)return toast('Pick an option or type your answer',true);
  $('#detail').querySelectorAll('[data-ask]').forEach(b=>b.disabled=true);
  const r=await api('/api/perm/answer',{id:a.perm.id,answers}).catch(()=>({ok:false,err:'offline'}));
  toast(r.ok?'Answered, the agent continues':'Failed: '+(r.err||'unknown'),!r.ok);
  refresh();
}
function permCard(p){
  if(p.kind==='ask')return askCard(p);
  const rule=permRule(p.suggestions);
  return `<div class="callout ask perm" data-pid="${esc(p.id)}"><div class="lbl">Asks permission · ${esc(p.tool)}${p.agent?` · subagent ${esc(p.agent)}`:''}</div>
    ${permBody(p)}
    <div class="perm-btns">
      <button class="btn primary" data-perm="allow">Allow</button>
      ${rule?`<button class="btn" data-perm="always" title="It won't ask about this again">Always allow: <span class="mono">${esc(rule)}</span></button>`:''}
      <button class="btn ghost danger" data-perm="deny">Deny</button>
    </div></div>`;
}
async function decidePerm(kind){
  const a=CUR; if(!a||!a.perm)return;
  const t=$('#r-text'), message=kind==='deny'&&t?t.value.trim():'';
  $('#detail').querySelectorAll('[data-perm]').forEach(b=>b.disabled=true);
  const r=await api('/api/perm/decide',{id:a.perm.id,behavior:kind==='deny'?'deny':'allow',always:kind==='always',message})
    .catch(()=>({ok:false,err:'offline'}));
  if(r.ok&&message){t.value='';autosize(t)}
  toast(r.ok?(kind==='deny'?'Denied':'Allowed, the agent continues'):'Failed: '+(r.err||'unknown'),!r.ok);
  refresh();
}
function wireDetail(){
  wireHead();
  const t=$('#r-text'); if(!t)return;
  t.oninput=()=>autosize(t);
  t.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendReply()}};
  $('#r-send').onclick=sendReply;
  wireAttach('r',$('#r-box'),$('#r-file'),$('#r-attach'));
  $('#detail').querySelectorAll('[data-chip]').forEach(c=>c.onclick=()=>{t.value=c.dataset.chip;autosize(t);t.focus()});
}

// "Bash  npm test": the tool and what it does, on one line
function toolLine(t){
  const what=t.what||(t.text||'').replace(/^\S+\s*/,'');
  return `<b>${esc(t.tool||String(t.text||'').split(' ')[0])}</b> <span>${esc(home(what))}</span>`;
}
// while it works: dots at the end of the chat and what it is doing
function busy(a){return a.live==='working'||(a.kind==='background'&&a.ui==='working')}
function paintTyping(){
  const el=$('#d-typing'), a=CUR; if(!el||!a)return;
  if(!busy(a)){el.innerHTML='';return}
  // if the last thing in the conversation is a tool, that's what it is doing
  const last=[...CONVO.msgs].reverse().find(m=>m.kind==='tool'||m.kind==='text');
  const doing=last&&last.kind==='tool'?toolLine(last):esc(a.detail||'Thinking…');
  const html=`<div class="typing"><span class="dots" aria-label="Working"><i></i><i></i><i></i></span>
    <span class="doing">${doing}</span></div>`;
  if(el.innerHTML===html)return;
  const body=$('#d-body'), atBottom=body.scrollHeight-body.scrollTop-body.clientHeight<80;
  el.innerHTML=html;
  if(atBottom)body.scrollTop=body.scrollHeight;
}

async function loadConvo(withSummary){
  const a=CUR; if(!a||!a.transcript)return;
  const key=a.key;
  const msgs=await api('/api/convo?transcript='+encodeURIComponent(a.transcript)).catch(()=>null);
  if(!CUR||CUR.key!==key||!msgs)return;
  const last=x=>x.length?x[x.length-1].text:null;
  const changed=msgs.length!==CONVO.msgs.length||last(msgs)!==last(CONVO.msgs);
  CONVO.msgs=msgs; if(changed)renderConvo();
  if(withSummary&&SUM.key!==key){
    // only what's already saved: Haiku isn't called until you press "Summarize"
    const s=await api('/api/summary?cached=1&transcript='+encodeURIComponent(a.transcript)+'&sid='+a.sessionId).catch(()=>null);
    if(CUR&&CUR.key===key&&SUM.key!==key){SUM={key,text:s&&s.summary||null,stale:!!(s&&s.stale),busy:false};paintSum()}
  }
}
// the question with options and your answer, in its place in the chat
function askMsg(m){
  return `<div class="lbl">It asked you</div>`+m.questions.map(q=>`<div class="ask-t">${q.header?`<span class="ask-h">${esc(q.header)}</span>`:''}${esc(q.question)}</div>
    ${q.options.length?`<div class="ask-was">${q.options.map(esc).join(' · ')}</div>`:''}`).join('');
}
function answerMsg(m){
  const qs=Object.entries(m.answers);
  return qs.length===1?esc(qs[0][1])
    :qs.map(([q,a])=>`<div class="ask-was">${esc(q)}</div><div>${esc(a)}</div>`).join('');
}
function renderConvo(){
  const box=$('#d-convo'); if(!box)return;
  const body=$('#d-body'); const atBottom=body.scrollHeight-body.scrollTop-body.clientHeight<80;
  // group: text messages + the tools it used in between (collapsible)
  const items=[]; let tools=[];
  for(const m of CONVO.msgs){
    if(m.kind==='tool'){tools.push(m);continue}
    if(m.kind==='image'){if(tools.length){items.push({tools});tools=[]}
      items.push({role:'assistant',html:figImg(fileUrl(m.text),m.text.replace(/^\/home\/[^/]+/,'~'))});continue}
    if(m.kind==='ask'||m.kind==='answer'){if(tools.length){items.push({tools});tools=[]}
      items.push({role:m.role,html:m.kind==='ask'?askMsg(m):answerMsg(m)});continue}
    if(m.kind!=='text')continue;
    if(tools.length){items.push({tools});tools=[]}
    items.push(m);
  }
  if(tools.length)items.push({tools});
  const LIM=30, hidden=CONVO.showAll?0:Math.max(0,items.length-LIM);
  const shown=items.slice(hidden);
  // groups you opened stay open on repaint
  const open=new Set([...box.querySelectorAll('details.tools[open]')].map(d=>d.dataset.i));
  box.innerHTML=`<div class="convo-h">Conversation</div>`+
    (hidden?`<button class="btn ghost more" id="more">Show ${hidden} earlier</button>`:'')+
    (shown.length?shown.map((m,k)=>m.tools
      ?`<details class="tools" data-i="${k+hidden}"${open.has(String(k+hidden))?' open':''}><summary>${ICON('chev')}${m.tools.length} ${m.tools.length===1?'tool':'tools'}</summary>
        ${m.tools.map(t=>`<div class="tool-l">${toolLine(t)}</div>`).join('')}</details>`
      :`<div class="msg ${m.role==='user'?'user':'assistant'}">${m.html||md(m.text)}</div>`).join('')
      :'<div class="empty">No messages.</div>');
  paintTyping();
  const mb=$('#more'); if(mb)mb.onclick=()=>{CONVO.showAll=true;renderConvo()};
  // when opened it starts at the very bottom, like a chat; afterwards it only follows if you were at the bottom
  if(!box.dataset.init){box.dataset.init=1;const end=()=>body.scrollTop=body.scrollHeight;
    end();setTimeout(end,250);setTimeout(end,900)}  // diagrams and images grow later
  else if(atBottom){body.scrollTop=body.scrollHeight}
  enhance(box);
}

async function sendReply(){
  const t=$('#r-text'); if(!CUR)return;
  if(uploading('r'))return toast('Wait for the images to finish uploading');
  const typed=t.value.trim(), text=withImages('r',typed); if(!text)return;
  const a=CUR;
  // always sent: on resume, whatever isn't passed is lost
  const model=$('#r-model')?.value||undefined, mode=$('#r-mode')?.value||undefined,
    effort=$('#r-effort')?.value||undefined;
  const chg=[model&&model!==a.model&&label('models',model),
    mode&&mode!==(a.mode||META.defaults.mode)&&'permissions '+label('modes',mode),
    (effort||null)!==(a.effort||null)&&'effort '+(effort||'normal')].filter(Boolean);
  t.value=''; autosize(t); $('#r-send').disabled=true; toast('Sending…');
  const imgs=ATT.r.slice(); ATT.r=[]; renderAtt('r');
  try{
    const r=a.kind==='history'
      ?await api('/api/history/resume',{sid:a.sessionId,text,model,mode,effort})
      :await api('/api/reply',{id:a.id,session_id:a.sessionId,text,model,mode,effort});
    // on resume, Claude continues in a new session (the old one is archived): open that one
    if(r.ok&&r.id&&r.id!==a.id&&a.kind!=='history'){
      await refresh(); const n=AGENTS.find(x=>x.id===r.id); if(n)select(n.key)}
    // the history one continues as a new gatito session: open that one
    if(r.ok&&a.kind==='history'&&r.id){
      toast('Continues in the background'); await refresh();
      const n=AGENTS.find(x=>x.id===r.id); if(n){select(n.key);return}}
    toast(r.ok?(r.via==='mod'?(a.live==='working'?'It will reach it when it finishes what it is doing':'Sent')
             :chg.length?`Sent · now ${chg.join(', ')}`:'Sent, the agent continues')
             :'Error: '+(r.err||'unknown'),!r.ok);
    if(!r.ok){t.value=typed;ATT.r=imgs;renderAtt('r')}else imgs.forEach(x=>URL.revokeObjectURL(x.url));
  }finally{const b=$('#r-send'); if(b)b.disabled=false}
  refresh();
}

async function act(kind){
  const a=CUR; if(!a)return;
  if(kind==='back')return closeDetail();
  if(kind==='pz')return pzToggle();
  if(kind==='hide'||kind==='unhide'){
    await api('/api/hide',{key:a.key,hide:kind==='hide'});
    toast(kind==='hide'?'Archived':'Restored');
    if(kind==='hide')closeDetail(); return refresh();
  }
  if(kind==='attach')return attachProject(a);
  if(kind==='stop'){
    const r=await api('/api/stop',{id:a.id});
    toast(r.ok?'Stopped':'Could not stop: '+r.err,!r.ok); return refresh();
  }
  if(kind==='remove'){
    const ok=await confirmBox('Delete session',
      `"${a.name||a.key}"\n\nThe background session is deleted. The conversation history stays in ~/.claude/projects.`+
      (a.worktreeBranch?`\n\nIts worktree (${a.worktreeBranch}) is only deleted if it has no unmerged changes.`:''));
    if(!ok)return;
    const r=await api('/api/remove',{id:a.id,session_id:a.sessionId});
    if(r.ok){toast('Deleted');closeDetail()}
    else toast('Could not delete: '+(r.err||''),true);
    return refresh();
  }
}

function attachProject(a){
  if(!META.projects.length)return toast('No projects: add them with the gear in the composer',true);
  const d=dialog(`<h3>Open a project</h3><p>The conversation stays the same, but from now on it can read and change
    the project you choose. The session is resumed.</p>
    <select id="at-p">${META.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.id)}</option>`).join('')}</select>
    <textarea id="at-t" rows="2" placeholder="What to do there (optional)"></textarea>
    <div class="acts"><button class="btn ghost" id="at-c">Cancel</button>
    <button class="btn primary" id="at-go">Open</button></div>`);
  $('#at-c').onclick=()=>d.close();
  $('#at-go').onclick=async()=>{
    const pid=$('#at-p').value, text=$('#at-t').value; d.close(); toast(`Opening ${pid}…`);
    const r=await api('/api/attach-project',{id:a.id,session_id:a.sessionId,project_id:pid,text}).catch(e=>({ok:false,err:e.message}));
    toast(r.ok?`It can now touch ${pid}`:'Error: '+(r.err||r.out||''),!r.ok);
    await refresh();
    if(r.ok&&r.id){const n=AGENTS.find(x=>x.id===r.id); if(n)select(n.key)}
  };
}

async function purge(){
  const items=AGENTS.filter(a=>a.group==='archive'&&a.kind==='background');
  const ok=await confirmBox('Empty archive',
    `${items.length} background ${items.length===1?'session':'sessions'} will be deleted:\n\n`+
    items.map(a=>'- '+(a.name||a.key)).join('\n'),'Delete all');
  if(!ok)return;
  let fail=0;
  for(const a of items){
    const r=await api('/api/remove',{id:a.id,session_id:a.sessionId}).catch(()=>({ok:false}));
    if(!r.ok)fail++;
  }
  if(CUR&&items.some(a=>a.key===CUR.key))closeDetail();
  toast(fail?`${fail} could not be deleted`:'Archive empty',!!fail); refresh();
}

/* ---------------- composer ---------------- */
async function submit(e){
  e&&e.preventDefault();
  const q=$('#q');
  if(uploading('q'))return toast('Wait for the images to finish uploading');
  const imgs=ATT.q.filter(x=>x.path).map(x=>x.path);
  const text=q.value.trim()||(imgs.length?'Look at this image.':''); if(!text)return;
  const W=t=>withImages('q',t);  // the task carries the images at the end
  const pid=$('#q-proj').value, model=$('#q-model').value;
  const opt=m=>({model:m,mode:$('#q-mode').value||undefined,effort:$('#q-effort').value||undefined,
    worktree:$('#q-wt').getAttribute('aria-pressed')==='true',profile:$('#q-profile').value||undefined,...whenOf()});
  if(opt().trigger==='at'&&!opt().at)return toast('Pick a date and time',true);
  // if you pick "When" by hand that rules; otherwise, the when the router understands
  const routed=(r,m)=>{const o=opt(m);
    if(!o.trigger&&r.when&&r.when!=='now')Object.assign(o,{trigger:r.when,at:r.at_ms,repeat:r.repeat});
    if(r.worktree)o.worktree=true;
    return o};
  const btn=$('#q-send'); btn.disabled=true;
  try{
    if(pid){ // project picked by hand: the router is only needed if you talk about when
      const p=projOf(pid);
      if(opt().trigger||!TIME_RE.test(text)){
        if(await launch(p,W(text),opt(model||META.defaults.model))){q.value='';autosize(q);clearAtt('q')}
        return;
      }
      toast('Thinking…');
      const r=await api('/api/route',{text,project_id:pid,images:imgs});
      if(await launch(p,W(r.task||text),routed(r,model||META.defaults.model))){q.value='';autosize(q);clearAtt('q')}
      return;
    }
    toast('Thinking…');
    const r=await api('/api/route',{text,images:imgs});
    if(r.intent==='action'){
      const res=await api('/api/action',{action_id:r.action_id});
      const ac=META.actions.find(x=>x.id===r.action_id);
      toast(res.ok?`${ac?ac.label:'Action'}: ${res.state?'on':'off'}`:'Action failed',!res.ok);
      q.value='';autosize(q);clearAtt('q');return;
    }
    if(r.intent==='question'){
      $('#toast').classList.remove('show');
      const d=dialog(`<h3>${esc(text)}</h3><div class="answer">${md(r.answer||'—')}</div>
        <textarea id="ask-more" rows="2" placeholder="Keep asking… (saved as a conversation)" enterkeyhint="send"></textarea>
        <div class="acts"><button class="btn ghost" id="ask-close">Close</button>
        <button class="btn primary" id="ask-go">Continue</button></div>`,'wide');
      $('#ask-close').onclick=()=>d.close();
      const more=$('#ask-more'), go=async()=>{
        const t=more.value.trim(); if(!t)return more.focus();
        d.close(); toast('Opening the conversation…');
        const o=opt(model||META.defaults.model);
        const res=await api('/api/ask/continue',{question:text,answer:r.answer,text:t,
          model:o.model,mode:o.mode,effort:o.effort,profile:o.profile}).catch(()=>({ok:false}));
        toast(res.ok?'Continues as a conversation':'Error: '+(res.err||res.out||'could not open'),!res.ok);
        await refresh();
        if(res.ok){const a=AGENTS.find(x=>x.id===res.id); if(a)select(a.key)}
      };
      more.oninput=()=>autosize(more);
      more.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();go()}};
      $('#ask-go').onclick=go;
      enhance(d.querySelector('.answer'));
      q.value='';autosize(q);clearAtt('q');return;
    }
    const p=projOf(r.project_id);
    if(p&&r.confidence==='high'){
      if(await launch(p,W(r.task||text),routed(r,model||r.model||META.defaults.model))){q.value='';autosize(q);clearAtt('q')}
    }else{
      $('#toast').classList.remove('show');
      pickProject(W(r.task||text),routed(r,model||r.model||META.defaults.model),r.project_id);
    }
  }catch(err){toast('Error: '+err.message,true)}
  finally{btn.disabled=false}
}
function pickProject(task,o,guess){
  const o0=o;
  const opts=META.projects.map(p=>`<option value="${esc(p.id)}"${p.id===guess?' selected':''}>${esc(p.id)}</option>`).join('')+freeOpt(guess);
  const d=dialog(`<h3>Which project?</h3><p>I'm not sure where to launch it.${o.trigger
      ?`\nIt will be saved to the backlog: ${when({...o,queue_pos:'',status:''}).replace(/^Queue$/,'in the queue')}.`:''}</p>
    <select id="pk-p">${opts}</select><textarea id="pk-t">${esc(task)}</textarea>
    <select id="pk-m">${selOpts('models',o.model,null)}</select>
    <select id="pk-mode">${selOpts('modes',o.mode||META.defaults.mode)}</select>
    <select id="pk-e">${selOpts('efforts',o.effort)}</select>
    <div class="acts"><button class="btn ghost" id="pk-c">Cancel</button>
    <button class="btn primary" id="pk-go">Launch</button></div>`);
  applyProfile(o.profile,{mode:$('#pk-mode')},false);
  $('#pk-c').onclick=()=>d.close();
  $('#pk-go').onclick=async()=>{
    const p=projOf($('#pk-p').value);
    const t=$('#pk-t').value.trim(); d.close();
    const o={...o0,model:$('#pk-m').value,mode:$('#pk-mode').value,effort:$('#pk-e').value||undefined};
    if(await launch(p,t,o)){$('#q').value='';autosize($('#q'));clearAtt('q')}
  };
}
async function launch(p,task,o){
  if(!p||!task)return false;
  if(o.trigger)return enqueue(p,task,o);
  const pn=p.label||p.id;
  toast(p.path?`Launching in ${pn}…`:'Launching without a project…');
  const r=await api('/api/launch',{path:p.path,task,...o,name:`${pn}: ${task.slice(0,40)}`});
  toast(r.ok?`Launched ${p.path?'in '+pn:'without a project'} · ${label('models',o.model)}`:'Error: '+(r.err||r.out||''),!r.ok);
  await refresh();
  if(r.ok){const a=AGENTS.find(x=>x.id===r.id); if(a)select(a.key)}
  return r.ok;
}

// time words in what you type (Spanish and English: user input, not code): with a
// hand-picked project, only then is the router asked
const TIME_RE=/\b(hoy|mañana|pasado|esta (tarde|noche)|lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|cada|todos los|entre semana|a las? \d|\d{1,2}[:h]\d{2}|en \d+ (min|hora)|dentro de|cola|hueco|más tarde|mas tarde|luego|apúnta|apunta|guárda|guarda|worktree|rama aparte|aislad|today|tomorrow|tonight|this (afternoon|evening|morning)|monday|tuesday|wednesday|thursday|friday|saturday|sunday|every|daily|weekdays|weekly|at \d|\d{1,2} ?(am|pm)|in \d+ ?(min|hour|h\b)|within|queue|later|slot|save it|isolated)/i;
// what the composer says about when to launch ({} = now)
function whenOf(){
  const w=$('#q-when').value; if(w==='now')return{};
  if(w!=='at')return{trigger:w};
  const v=$('#q-at').value;
  return{trigger:'at',at:v?new Date(v).getTime():null,repeat:$('#q-repeat').value||null};
}
async function enqueue(p,task,o){
  const r=await api('/api/backlog/add',{project_id:p.id,task,...o});
  if(!r.ok){toast('Error: '+r.err,true);return false}
  toast(o.trigger==='queue'?`Queued for ${pname(p.id)}`:o.trigger==='at'?`Scheduled: ${when(r.item)}`:'Saved to To do');
  await refresh(); return true;
}
function manageProjects(){
  const rows=META.projects.length?META.projects.map(p=>`
    <li data-id="${esc(p.id)}">
      <span class="pm-info"><div class="pm-id">${esc(p.id)}</div>
        <div class="pm-path">${esc(p.path)}</div></span>
      <button class="btn ghost icon pm-del" data-del="${esc(p.id)}" title="Remove ${esc(p.id)}"
        aria-label="Remove ${esc(p.id)}">${ICON('trash')}</button>
    </li>`).join(''):'<li class="pm-empty">No projects.</li>';
  const d=dialog(`<h3>Projects</h3>
    <p>Only the projects in this list appear. Add a folder by its path or
       remove it with the trash can (nothing is deleted from disk).</p>
    <ul class="pm-list">${rows}</ul>
    <div class="pm-add">
      <input id="pm-path" type="text" placeholder="Path, e.g. ~/own/my-project"
        autocapitalize="off" autocorrect="off" spellcheck="false">
      <button class="btn primary" id="pm-add-btn" type="button">Add</button>
    </div>
    <div class="acts"><button class="btn primary" data-close>Close</button></div>`);
  d.querySelector('[data-close]').onclick=()=>d.close();
  d.querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{
    const id=b.dataset.del;
    if(!await confirmBox('Remove project',`Remove "${id}" from the list.`,'Remove'))return;
    const r=await api('/api/project-remove',{id}).catch(()=>({ok:false}));
    if(r.ok){toast(`"${id}" removed`);await loadMeta();manageProjects();}
    else toast(r.err||'could not remove',true);
  });
  const addPath=d.querySelector('#pm-path');
  const doAdd=async()=>{
    const path=addPath.value.trim(); if(!path)return;
    const r=await api('/api/project-add',{path}).catch(()=>({ok:false}));
    if(r.ok){toast(`"${r.project.id}" added`);await loadMeta();manageProjects();}
    else toast(r.err||'could not add',true);
  };
  d.querySelector('#pm-add-btn').onclick=doAdd;
  addPath.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();doAdd()}};
}

/* ---------------- attached images ---------------- */
// They are uploaded to state/uploads and the message carries them as ![image](path): the agent
// opens them with Read and the conversation shows them.
const ATT={q:[],r:[]};
async function prepImage(file){
  // phone photos: downscaled (less weight and fewer tokens); small screenshots as they are
  const bmp=await createImageBitmap(file).catch(()=>null); if(!bmp)return file;
  const k=Math.min(1,2000/Math.max(bmp.width,bmp.height));
  if(k===1&&file.size<2e6&&/^image\/(png|jpeg|webp|gif)$/.test(file.type))return file;
  const c=document.createElement('canvas'); c.width=Math.round(bmp.width*k); c.height=Math.round(bmp.height*k);
  c.getContext('2d').drawImage(bmp,0,0,c.width,c.height);
  return await new Promise(r=>c.toBlob(r,'image/jpeg',.86));
}
async function addImages(box,files){
  for(const f of files){
    if(!f.type.startsWith('image/'))continue;
    const blob=await prepImage(f), item={url:URL.createObjectURL(blob),path:null};
    ATT[box].push(item); renderAtt(box);
    const r=await fetch('/api/upload',{method:'POST',body:blob,
      headers:{'X-Gatito-Token':tok(),'Content-Type':blob.type}}).then(r=>r.json()).catch(()=>({ok:false,err:'offline'}));
    if(r.ok)item.path=r.path;
    else{ATT[box]=ATT[box].filter(x=>x!==item);toast('Could not upload the image: '+(r.err||''),true)}
    renderAtt(box);
  }
}
function renderAtt(box){
  const el=$('#'+box+'-att'); if(!el)return;
  el.hidden=!ATT[box].length;
  el.innerHTML=ATT[box].map((x,k)=>`<span class="att-i${x.path?'':' up'}"><img src="${x.url}" alt="Attached image">
    <button type="button" data-k="${k}" aria-label="Remove image">${ICON('x')}</button></span>`).join('');
  el.querySelectorAll('[data-k]').forEach(b=>b.onclick=()=>{URL.revokeObjectURL(ATT[box][+b.dataset.k].url);ATT[box].splice(+b.dataset.k,1);renderAtt(box)});
}
function clearAtt(box){ATT[box].forEach(x=>URL.revokeObjectURL(x.url));ATT[box]=[];renderAtt(box)}
function uploading(box){return ATT[box].some(x=>!x.path)}
function withImages(box,text){
  const imgs=ATT[box].filter(x=>x.path).map(x=>`![image](${x.path})`);
  return imgs.length?(text||'Look at this image.')+'\n\n'+imgs.join('\n'):text;
}
// paste (Ctrl+V), drop, or the image button
function wireAttach(box,area,input,btn){
  btn.onclick=()=>input.click();
  input.onchange=()=>{addImages(box,[...input.files]);input.value=''};
  const imgsOf=list=>[...(list||[])].filter(f=>f.type.startsWith('image/'));
  area.addEventListener('paste',e=>{const fs=imgsOf(e.clipboardData?.files);if(fs.length){e.preventDefault();addImages(box,fs)}});
  area.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();area.classList.add('drop')}});
  area.addEventListener('dragleave',e=>{if(!area.contains(e.relatedTarget))area.classList.remove('drop')});
  area.addEventListener('drop',e=>{area.classList.remove('drop');const fs=imgsOf(e.dataTransfer.files);if(fs.length){e.preventDefault();addImages(box,fs)}});
}

/* ---------------- history ---------------- */
// All your Claude Code conversations, including closed terminal ones.
// It lives in its own block (#hist): the 5 s refresh doesn't touch it.
let HIST={items:[],total:0,q:'',limit:40,t:null};
function histItem(s){
  return {...s,key:'h:'+s.sid,kind:'history',group:'history',ui:'history',sessionId:s.sid,name:s.title}
}
async function loadHist(){
  const r=await api(`/api/history?q=${encodeURIComponent(HIST.q)}&limit=${HIST.limit}`).catch(()=>null); if(!r)return;
  HIST.items=r.items.map(histItem); HIST.total=r.total;
  $('#hist-n').textContent=r.total||'';
  $('#hist-list').innerHTML=(HIST.items.length?HIST.items.map(row).join('')
      :`<div class="empty">${HIST.q?'Nothing matches that search.':'No earlier conversations.'}</div>`)
    +(r.total>HIST.items.length?`<button class="btn ghost more" id="hist-more" type="button">Show more (${r.total-HIST.items.length} left)</button>`:'');
  $('#hist-list').querySelectorAll('.row[data-key]').forEach(b=>b.onclick=()=>select(b.dataset.key));
  const m=$('#hist-more'); if(m)m.onclick=()=>{HIST.limit+=40;loadHist()};
}
function initHist(){
  $('#hist').addEventListener('toggle',()=>{if($('#hist').open)loadHist()});
  $('#hist-q').oninput=e=>{clearTimeout(HIST.t);HIST.t=setTimeout(()=>{HIST.q=e.target.value;HIST.limit=40;loadHist()},250)};
  api('/api/history?limit=0').then(r=>$('#hist-n').textContent=r.total||'').catch(()=>{});
}

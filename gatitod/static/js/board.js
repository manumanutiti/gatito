/* "Backlog" view: kanban board. Tasks wait in To do, Queued or
   Scheduled, move to Running when launched and end up in Done.
   Dragging a card between columns changes when it launches.
   The side sheet for creating/editing tasks also lives here (Week uses it). */

const COLS=[
  {id:'manual', t:'To do', hint:'You launch them whenever you want'},
  {id:'queue', t:'Queued', hint:()=>`They go out on their own, ${META.config?.max_parallel??2} at a time, in order`},
  {id:'at', t:'Scheduled', hint:'They go out at their time. <a href="#/week">See in the week</a>'},
  {id:'running', t:'Running', hint:'Drop here to launch now'},
  {id:'done', t:'Done', hint:'Launched in the last 7 days', nodrop:true},
];
const WHEN_HINT={manual:'when you say',queue:'as soon as there is room',at:'at a set time'};
let BOARD={filter:stored('gatito-bfilter')||'',drag:null,sig:''};

const live=a=>a&&(a.ui==='working'||a.ui==='blocked');
const rankOf=i=>i.rank??i.created;
const lastRun=i=>(i.runs||[]).at(-1);

function colOf(i){
  if(i.status==='launching')return'running';
  if(i.status==='launched')return live(agentOf(i))?'running':'done';
  return i.trigger;  // pending and failed ones stay where they were
}

function initBoard(){
  $('#v-backlog').innerHTML=`<header class="vh"><h1>Backlog</h1>
    <span class="sub" id="bk-sub"></span>
    <div class="vh-tools">
      <select class="sel" id="bk-filter" title="Filter by project"></select>
      <button class="btn primary" id="bk-new">${ICON('plus')}New task</button></div></header>
    <div class="board" id="board"></div>`;
  $('#bk-sub').textContent=matchMedia('(hover:hover)').matches
    ?'Drag a card to change when it launches.':'Tap a card to edit or move it.';
  $('#bk-new').onclick=()=>openSheet(null,{trigger:'manual'});
  $('#bk-filter').onchange=e=>{BOARD.filter=e.target.value;store('gatito-bfilter',BOARD.filter||null);renderBoard(true)};
}
function renderBoardFilter(){
  const f=$('#bk-filter'); if(!f)return;
  f.hidden=!META.projects.length;
  f.innerHTML='<option value="">All projects</option>'+META.projects.map(p=>
    `<option value="${esc(p.id)}"${p.id===BOARD.filter?' selected':''}>${esc(p.id)}</option>`).join('');
}

function cardHtml(i,col){
  const a=agentOf(i), r=lastRun(i);
  let status='';
  if(col==='running')status=a&&a.ui==='blocked'
    ?'<div class="card-s waiting"><span class="st waiting"></span>Waiting for you</div>'
    :'<div class="card-s working"><span class="st working"></span>Working</div>';
  else if(i.status==='failed')status=`<div class="card-s failed">Could not launch: ${esc(i.err||'unknown error')}</div>`;
  const whenTxt=col==='at'?`<span class="card-w">${ICON(i.repeat?'repeat':'clock')}${esc(when(i))}</span>`
    :col==='done'&&r?`<span class="card-w">${ICON('check')}${esc(ago(r.ts))}</span>`:'';
  const drag=col!=='running';  // what is running doesn't move
  return `<article class="card${col==='done'?' done':''}" tabindex="0" data-id="${esc(i.id)}" data-col="${col}"
      draggable="${drag}" style="--pc:${projColor(i.project_id)}">
    ${col==='queue'&&i.queue_pos?`<span class="pos">#${i.queue_pos}</span>`:''}
    <div class="card-t">${esc(firstLine(i.task))}</div>
    <div class="card-m"><span class="pj">${pdot(i.project_id)}${esc(i.project_id)}</span>
      <span>${esc(label('models',i.model))}</span>${profileTag(i.profile)}${i.worktree?`<span title="In a worktree">${ICON('branch')}</span>`:''}
      ${whenTxt}</div>${status}</article>`;
}

function renderBoard(force){
  const v=$('#v-backlog'); if(!v||v.hidden||BOARD.drag)return;
  const items=BACKLOG.filter(i=>!BOARD.filter||i.project_id===BOARD.filter);
  const sig=JSON.stringify([items,AGENTS.map(a=>[a.id,a.ui]),META.config]);
  if(!force&&sig===BOARD.sig)return;
  BOARD.sig=sig;
  const by=Object.fromEntries(COLS.map(c=>[c.id,[]]));
  for(const i of items){
    by[colOf(i)].push(i);
    // a repeating one stays scheduled, but its latest run is also running
    if(i.status==='pending'&&i.repeat&&live(agentOf(i)))by.running.push(i);
  }
  by.manual.sort((a,b)=>b.created-a.created);
  by.queue.sort((a,b)=>(a.queue_pos||1e9)-(b.queue_pos||1e9));
  by.at.sort((a,b)=>a.at-b.at);
  for(const c of ['running','done'])by[c].sort((a,b)=>(lastRun(b)?.ts||0)-(lastRun(a)?.ts||0));
  $('#board').innerHTML=COLS.map(c=>`<section class="col${c.nodrop?' nodrop':''}" data-col="${c.id}" aria-label="${c.t}">
    <div class="col-h"><div class="col-t">${c.t}<span class="n">${by[c.id].length||''}</span>
      ${c.id==='manual'?`<button class="btn ghost icon add" data-add title="New task" aria-label="New task">${ICON('plus')}</button>`:''}</div>
      <div class="col-hint">${typeof c.hint==='function'?c.hint():c.hint}</div></div>
    <div class="col-b">${by[c.id].map(i=>cardHtml(i,c.id)).join('')||
      `<div class="col-empty">${c.id==='manual'?'Nothing pending. Jot down here what you want to do later.':'Empty'}</div>`}</div>
  </section>`).join('');
  wireBoard();
}

function wireBoard(){
  const B=$('#board');
  B.querySelector('[data-add]').onclick=()=>openSheet(null,{trigger:'manual'});
  B.querySelectorAll('.card').forEach(el=>{
    const open=()=>{
      const i=BACKLOG.find(x=>x.id===el.dataset.id), a=i&&agentOf(i);
      // what was launched is viewed in its session; what is pending is edited
      if(a&&(el.dataset.col==='running'||el.dataset.col==='done')){go('sessions');select(a.key)}
      else openSheet(el.dataset.id);
    };
    el.onclick=open;
    el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}};
    el.ondragstart=e=>{
      BOARD.drag={id:el.dataset.id,from:el.dataset.col};
      e.dataTransfer.setData('text/plain',el.dataset.id); e.dataTransfer.effectAllowed='move';
      requestAnimationFrame(()=>el.classList.add('drag'));
    };
    el.ondragend=()=>{BOARD.drag=null;B.querySelectorAll('.over').forEach(c=>c.classList.remove('over'));
      B.querySelectorAll('.drop-mark').forEach(m=>m.remove());renderBoard(true)};
  });
  B.querySelectorAll('.col:not(.nodrop)').forEach(col=>{
    const body=col.querySelector('.col-b');
    col.ondragover=e=>{
      if(!BOARD.drag)return; e.preventDefault(); col.classList.add('over');
      if(col.dataset.col!=='queue')return;
      // order matters in the queue: mark where it will land
      let mark=body.querySelector('.drop-mark'); if(!mark){mark=document.createElement('div');mark.className='drop-mark'}
      const next=[...body.querySelectorAll('.card:not(.drag)')].find(c=>{const r=c.getBoundingClientRect();return e.clientY<r.top+r.height/2});
      next?body.insertBefore(mark,next):body.appendChild(mark);
    };
    col.ondragleave=e=>{if(!col.contains(e.relatedTarget)){col.classList.remove('over');body.querySelector('.drop-mark')?.remove()}};
    col.ondrop=e=>{
      e.preventDefault();
      const mark=body.querySelector('.drop-mark'), before=mark?.nextElementSibling?.dataset?.id;
      const id=BOARD.drag?.id; BOARD.drag=null;
      col.classList.remove('over'); mark?.remove();
      if(id)moveTo(id,col.dataset.col,before);
    };
  });
}

// rank between neighbours to place the card right before `beforeId` in the queue
function queueRank(id,beforeId){
  const q=BACKLOG.filter(i=>i.trigger==='queue'&&i.status==='pending'&&i.id!==id).sort((a,b)=>rankOf(a)-rankOf(b));
  const k=beforeId?q.findIndex(i=>i.id===beforeId):-1;
  if(k<0)return q.length?rankOf(q.at(-1))+1000:Date.now();
  return k===0?rankOf(q[0])-1000:(rankOf(q[k-1])+rankOf(q[k]))/2;
}

async function moveTo(id,to,beforeId){
  const i=BACKLOG.find(x=>x.id===id); if(!i)return;
  if(to==='running')return runNow(i);
  if(to==='at')return openSheet(id,{trigger:'at'});  // the time still has to be chosen
  if(i.trigger===to&&i.status==='pending'&&to!=='queue')return;
  const r=await api('/api/backlog/update',{id,trigger:to,...(to==='queue'?{rank:queueRank(id,beforeId)}:{})});
  toast(r.ok?(to==='queue'?'Queued':'Moved to To do'):'Error: '+r.err,!r.ok);
  await refresh();
}

async function runNow(i){
  // an already launched one is relaunched: it first moves to To do so it doesn't fire on its own
  if(i.status==='launched'||i.status==='failed'){
    if(i.status==='launched'&&!await confirmBox('Launch again',`"${firstLine(i.task)}" was already launched. Launch it again?`,'Launch',false))return;
    if(i.trigger!=='manual')await api('/api/backlog/update',{id:i.id,trigger:'manual'});
  }
  toast('Launching…');
  const r=await api('/api/backlog/run',{id:i.id});
  toast(r.ok?'Launched':'Could not launch: '+(r.err||r.out||''),!r.ok);
  await refresh(); return r.ok;
}

/* ---------------- side sheet: create and edit ---------------- */
function openSheet(id,preset={}){
  const i0=id?BACKLOG.find(x=>x.id===id):null; if(id&&!i0)return toast('That task no longer exists',true);
  const i={trigger:'manual',model:META.defaults.model,mode:META.defaults.mode,effort:null,worktree:false,
    profile:null,project_id:BOARD.filter||$('#q-proj')?.value||META.projects[0]?.id,task:'',...i0,...preset};
  if(i.trigger==='at'&&!i.at)i.at=nextHour();
  const isNew=!i0, gone=i0&&i0.status==='launched';
  const d=$('#sheet'); if(d.open)d.close();
  const runs=(i.runs||[]).slice().reverse().map(r=>{
    const a=r.agent_id&&AGENTS.find(x=>x.id===r.agent_id);
    return `<li>${new Date(r.ts).toLocaleString('en-GB',{weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}: ${r.ok
      ?(a?`<a data-open="${esc(a.key)}">view the session</a>`:'launched')
      :`<span class="bad">failed: ${esc(r.err||'')}</span>`}</li>`}).join('');
  d.innerHTML=`<div class="sh-h"><h2>${isNew?(i.trigger==='at'?'Schedule task':'New task'):esc(firstLine(i.task))}</h2>
      <button class="btn ghost icon" data-x aria-label="Close">${ICON('x')}</button></div>
    <div class="sh-b form">
      ${i0?.status==='failed'?`<div class="callout ask"><div class="lbl">Could not launch</div><div class="txt">${esc(i0.err||'')}</div></div>`:''}
      ${gone?'<div class="callout"><div class="txt">Already launched. If you save changes, it becomes pending again.</div></div>':''}
      ${META.loaded?'':`<div class="callout ask"><div class="lbl">No configuration</div><div class="txt">${
        'Could not load the gatito configuration. Check the connection or pair this device.'}</div></div>`}
      <label for="sh-task">What needs doing</label>
      <textarea id="sh-task" rows="5" placeholder="Describe it as you would ask an agent">${esc(i.task)}</textarea>
      <label>When it launches</label>
      <div class="when-seg" role="group" aria-label="When it launches">${['manual','queue','at'].map(w=>
        `<button type="button" data-w="${w}" aria-pressed="${i.trigger===w}">${WHEN_TXT[w]}<small>${WHEN_HINT[w]}</small></button>`).join('')}</div>
      <div class="grid sh-at">
        <div><label for="sh-at">Date and time</label><input type="datetime-local" id="sh-at" value="${localInput(i.at||nextHour())}"></div>
        <div><label for="sh-rep">Repeat</label><select id="sh-rep">${repeatOpts(i.repeat)}</select></div></div>
      <div class="grid">
        <div><label for="sh-profile">Profile</label><select id="sh-profile">${profileOpts(i.profile,'none','')}</select></div>
        <div><label for="sh-proj">Project</label><select id="sh-proj">${META.projects.map(p=>
          `<option value="${esc(p.id)}"${p.id===i.project_id?' selected':''}>${esc(p.id)}</option>`).join('')+freeOpt(i.project_id)}</select></div>
        <div><label for="sh-model">Model</label><select id="sh-model">${selOpts('models',i.model,null,'')}</select></div>
        <div><label for="sh-mode">Permissions</label><select id="sh-mode">${selOpts('modes',i.mode,null,'')}</select></div>
        <div><label for="sh-effort">Effort</label><select id="sh-effort">${selOpts('efforts',i.effort,'normal','')}</select></div></div>
      <label class="check"><input type="checkbox" id="sh-wt"${i.worktree?' checked':''}>
        Isolate in a worktree (repo copy on its own branch)</label>
      <label class="check"><input type="checkbox" id="sh-anon"${(i0?i.anon:anonOn())?' checked':''}>
        Anonymize: send it with placeholders instead of the real names</label>
      ${runs?`<label>Launches</label><ul class="runs">${runs}</ul>`:''}
    </div>
    <div class="sh-f">
      ${isNew?'':`<button class="btn ghost danger" data-del>${ICON('trash')}Delete</button>`}
      <span class="spacer"></span>
      ${isNew?'':`<button class="btn ghost" data-run>${ICON('play')}Launch now</button>`}
      <button class="btn primary" data-save${META.loaded?'':' disabled'}>${isNew?'Create task':'Save'}</button></div>`;
  let trig=i.trigger;
  const syncWhen=()=>{
    d.querySelectorAll('[data-w]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.w===trig));
    d.querySelector('.sh-at').hidden=trig!=='at';
  };
  d.querySelectorAll('[data-w]').forEach(b=>b.onclick=()=>{trig=b.dataset.w;syncWhen()});
  syncWhen();
  const sels={model:$('#sh-model'),mode:$('#sh-mode'),effort:$('#sh-effort'),wt:on=>$('#sh-wt').checked=on};
  applyProfile(i.profile,sels,false);
  $('#sh-profile').onchange=()=>applyProfile($('#sh-profile').value,sels);
  d.querySelector('[data-x]').onclick=()=>d.close();
  d.onclick=e=>{if(e.target===d)d.close()};  // click outside the sheet
  d.querySelectorAll('[data-open]').forEach(a=>a.onclick=()=>{d.close();go('sessions');select(a.dataset.open)});
  d.querySelector('[data-save]').onclick=async()=>{
    const at=new Date($('#sh-at').value).getTime();
    if(trig==='at'&&!(at>Date.now()))return toast('Pick a date and time that have not passed',true);
    const body={task:$('#sh-task').value,project_id:$('#sh-proj').value,model:$('#sh-model').value,
      mode:$('#sh-mode').value,effort:$('#sh-effort').value||null,worktree:$('#sh-wt').checked,
      profile:$('#sh-profile').value||null,anon:$('#sh-anon').checked,
      trigger:trig,at:trig==='at'?at:null,repeat:trig==='at'?($('#sh-rep').value||null):null};
    if(trig==='queue'&&(isNew||i0.trigger!=='queue'))body.rank=queueRank(i0?.id);
    const r=isNew?await api('/api/backlog/add',body):await api('/api/backlog/update',{id:i0.id,...body});
    if(!r.ok)return toast(r.err,true);
    d.close(); toast(isNew?(trig==='at'?`Scheduled: ${when(r.item)}`:'Task created'):'Saved'); refresh();
  };
  d.querySelector('[data-del]')?.addEventListener('click',async()=>{
    d.close();
    if(!await confirmBox('Delete task',`"${firstLine(i0.task)}"`))return;
    await api('/api/backlog/remove',{id:i0.id}); toast('Task deleted'); refresh();
  });
  d.querySelector('[data-run]')?.addEventListener('click',async()=>{if(await runNow(i0))d.close()});
  d.showModal();
  if(isNew)$('#sh-task').focus();
}

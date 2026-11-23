/* "Week" view: calendar of what is scheduled. Timed tasks are drawn on
   their day (repeating ones on every day they fall on) and those already launched
   stay marked at the time they went out. Click a slot to schedule
   something there; drag a task to change its time. On mobile, one day. */

const EV_MIN=28;  // height of an event (24px with --hh 52) in minutes, to spread overlaps
let WEEK={start:weekStart(Date.now()),day:(new Date().getDay()+6)%7,sig:'',scrolled:false,drag:null};

function weekStart(ms){const d=new Date(ms);d.setHours(0,0,0,0);d.setDate(d.getDate()-(d.getDay()+6)%7);return d.getTime()}
function addDays(ms,n){const d=new Date(ms);d.setDate(d.getDate()+n);return d.getTime()}
function dayStart(ms){const d=new Date(ms);d.setHours(0,0,0,0);return d.getTime()}
function nextOcc(t,rep){
  const d=new Date(t); d.setDate(d.getDate()+(rep==='weekly'?7:1));
  while(rep==='weekdays'&&(d.getDay()===0||d.getDay()===6))d.setDate(d.getDate()+1);
  return d.getTime();
}
const hh=()=>parseFloat(getComputedStyle($('#v-week')).getPropertyValue('--hh'))||52;
const narrow=()=>matchMedia('(max-width:760px)').matches;

function initWeek(){
  $('#v-week').innerHTML=`<header class="vh"><h1>Week</h1><span class="wk-range" id="wk-range"></span>
    <div class="vh-tools">
      <div class="seg"><button id="wk-prev" aria-label="Previous week">${ICON('left')}</button>
        <button id="wk-today">Today</button>
        <button id="wk-next" aria-label="Next week">${ICON('right')}</button></div>
      <button class="btn primary" id="wk-new">${ICON('plus')}Schedule</button></div></header>
    <div class="wk-strip" id="wk-strip"></div><div class="wk" id="wk"></div>`;
  const nav=n=>{WEEK.start=addDays(WEEK.start,7*n);WEEK.scrolled=false;renderWeek(true)};
  $('#wk-prev').onclick=()=>nav(-1);
  $('#wk-next').onclick=()=>nav(1);
  $('#wk-today').onclick=()=>{WEEK.start=weekStart(Date.now());WEEK.day=(new Date().getDay()+6)%7;WEEK.scrolled=false;renderWeek(true)};
  $('#wk-new').onclick=()=>openSheet(null,{trigger:'at'});
  let t; addEventListener('resize',()=>{clearTimeout(t);t=setTimeout(()=>renderWeek(true),150)});
  setInterval(placeNow,30000);
}

// what falls between from and to: upcoming runs and launches already done
function weekEvents(from,to){
  const ev=[];
  for(const i of BACKLOG){
    if(i.trigger==='at'&&i.status==='pending'&&i.at){
      for(let t=i.at,n=0;t<to&&n<400;n++){
        if(t>=from)ev.push({kind:'plan',t,i});
        if(!i.repeat)break; t=nextOcc(t,i.repeat);
      }
    }
    for(const r of i.runs||[])if(r.ts>=from&&r.ts<to)ev.push({kind:'ran',t:r.ts,i,r});
  }
  return ev.sort((a,b)=>a.t-b.t);
}

// spread overlapping ones into lanes so all are visible
function lanes(evs){
  let group=[],end=0;
  const flush=()=>{const n=Math.max(...group.map(e=>e.lane))+1;group.forEach(e=>e.lanes=n);group=[]};
  for(const e of evs){
    if(group.length&&e.t>=end)flush();
    const used=new Set(group.filter(g=>g.t+EV_MIN*60000>e.t).map(g=>g.lane));
    e.lane=0; while(used.has(e.lane))e.lane++;
    group.push(e); end=Math.max(end,e.t+EV_MIN*60000);
  }
  if(group.length)flush();
  return evs;
}

function evHtml(e,day){
  // coinciding ones stack below (they are short pills: they read better than split in width)
  const top=(e.t-day)/3600000*hh()+e.lane*26;
  const style=`top:${top}px;--pc:${projColor(e.i.project_id)}`;
  const name=esc(firstLine(e.i.task));
  if(e.kind==='ran')return `<button class="ev ran${e.r.ok?'':' bad'}" data-ran="${esc(e.i.id)}" data-agent="${esc(e.r.agent_id||'')}"
      style="${style}" title="${e.r.ok?'Launched':'Failed'}: ${name}">
    <span class="t">${ICON(e.r.ok?'check':'x')}${hm(e.t)}</span><span class="n">${name}</span></button>`;
  return `<button class="ev" draggable="true" data-plan="${esc(e.i.id)}" style="${style}"
      title="${name}. ${esc(e.i.project_id)}${e.i.repeat?', '+REPEAT_TXT[e.i.repeat].toLowerCase():''}">
    <span class="t">${hm(e.t)}${e.i.repeat?ICON('repeat'):''}</span><span class="n">${name}</span></button>`;
}

function renderWeek(force){
  const v=$('#v-week'); if(!v||v.hidden||WEEK.drag)return;
  const days=[...Array(7)].map((_,k)=>addDays(WEEK.start,k));
  const shown=narrow()?[days[WEEK.day]]:days;
  const from=shown[0], to=addDays(shown.at(-1),1);
  const evs=weekEvents(from,to);
  const sig=JSON.stringify([shown,evs.map(e=>[e.kind,e.t,e.i.id,e.i.task,e.i.project_id,e.r?.ok]),AGENTS.length]);
  if(!force&&sig===WEEK.sig)return;
  WEEK.sig=sig;

  const fmt=(ms,o)=>new Date(ms).toLocaleDateString('en-GB',o);
  const end=days[6];
  $('#wk-range').textContent=new Date(WEEK.start).getMonth()===new Date(end).getMonth()
    ?`${fmt(WEEK.start,{day:'numeric'})} – ${fmt(end,{day:'numeric',month:'long'})}`
    :`${fmt(WEEK.start,{day:'numeric',month:'short'})} – ${fmt(end,{day:'numeric',month:'short'})}`;
  const today=dayStart(Date.now());
  $('#wk-strip').innerHTML=days.map((d,k)=>`<button data-k="${k}"${k===WEEK.day?' aria-current="date"':''}
    class="${d===today?'today':''}">${fmt(d,{weekday:'short'})}<b>${new Date(d).getDate()}</b></button>`).join('');
  $('#wk-strip').querySelectorAll('button').forEach(b=>b.onclick=()=>{WEEK.day=+b.dataset.k;WEEK.scrolled=false;renderWeek(true)});

  const sc=$('#wk .wk-scroll'), keep=sc?sc.scrollTop:null;
  $('#wk').style.setProperty('--nd',shown.length);
  $('#wk').innerHTML=`<div class="wk-days"><div></div>${shown.map(d=>`<div class="wk-day${d===today?' today':''}${d<today?' past':''}">
      ${fmt(d,{weekday:'short'})}<b>${new Date(d).getDate()}</b></div>`).join('')}</div>
    <div class="wk-scroll"><div class="wk-grid">
      <div class="wk-hours">${[...Array(23)].map((_,h)=>`<span style="top:${(h+1)*hh()}px">${String(h+1).padStart(2,'0')}:00</span>`).join('')}</div>
      ${shown.map(d=>{
        const de=lanes(evs.filter(e=>e.t>=d&&e.t<addDays(d,1)));
        return `<div class="wk-col${d===today?' today':''}" data-day="${d}"><div class="wk-ghost"></div>${de.map(e=>evHtml(e,d)).join('')}</div>`}).join('')}
    </div></div>`;
  const s=$('#wk .wk-scroll');
  if(keep!=null&&WEEK.scrolled)s.scrollTop=keep;
  else{  // on open: from the earliest of now and what is scheduled (or 7)
    const inWeek=Date.now()>=from&&Date.now()<to;
    const hours=evs.filter(e=>e.t>=Date.now()-3600000).map(e=>new Date(e.t).getHours()+new Date(e.t).getMinutes()/60);
    if(inWeek)hours.push(new Date().getHours());
    s.scrollTop=Math.max(0,((hours.length?Math.min(...hours):7.5)-.5)*hh()); WEEK.scrolled=true;
  }
  placeNow(); wireWeek();
}

function placeNow(){
  const grid=$('#wk .wk-grid'); if(!grid)return;
  grid.querySelectorAll('.now,.now-t').forEach(n=>n.remove());
  const col=grid.querySelector(`.wk-col[data-day="${dayStart(Date.now())}"]`); if(!col)return;
  const top=(Date.now()-dayStart(Date.now()))/3600000*hh();
  col.insertAdjacentHTML('beforeend',`<div class="now" style="top:${top}px" aria-hidden="true">
    <svg viewBox="0 0 18 14"><path d="M1 14 3 1l5 5h2l5-5 2 13z"/></svg></div>`);
  grid.querySelector('.wk-hours').insertAdjacentHTML('beforeend',`<span class="now-t" style="top:${top}px">${hm(Date.now())}</span>`);
}

// minute (rounded to `step`) the pointer falls on inside a column
function slotAt(col,clientY,step){
  const y=clientY-col.getBoundingClientRect().top;
  const min=Math.max(0,Math.min(1440-step,Math.floor(y/hh()*60/step)*step));
  return +col.dataset.day+min*60000;
}

function wireWeek(){
  const W=$('#wk');
  W.querySelectorAll('.wk-col').forEach(col=>{
    const ghost=col.querySelector('.wk-ghost');
    col.onmousemove=e=>{if(e.target!==col&&e.target!==ghost)return;
      ghost.style.top=(slotAt(col,e.clientY,30)-col.dataset.day)/3600000*hh()+'px'};
    col.onclick=e=>{
      if(e.target!==col&&e.target!==ghost)return;
      const t=slotAt(col,e.clientY,30);
      if(t<Date.now())return toast('That time has passed: pick a later slot',true);
      openSheet(null,{trigger:'at',at:t});
    };
    col.ondragover=e=>{if(WEEK.drag){e.preventDefault();col.classList.add('over')}};
    col.ondragleave=e=>{if(!col.contains(e.relatedTarget))col.classList.remove('over')};
    col.ondrop=async e=>{
      e.preventDefault(); col.classList.remove('over');
      const d=WEEK.drag; WEEK.drag=null; if(!d)return;
      const t=slotAt(col,e.clientY-d.dy,15);
      if(t<Date.now()){toast('That time has passed',true);return renderWeek(true)}
      const r=await api('/api/backlog/update',{id:d.id,trigger:'at',at:t});
      toast(r.ok?`Moved to ${new Date(t).toLocaleDateString('en-GB',{weekday:'long',day:'numeric'})}, ${hm(t)}`:'Error: '+r.err,!r.ok);
      await refresh(); renderWeek(true);
    };
  });
  W.querySelectorAll('.ev[data-plan]').forEach(el=>{
    el.onclick=()=>openSheet(el.dataset.plan);
    el.ondragstart=e=>{
      // dy: where you grabbed the event, so it lands where you see it
      WEEK.drag={id:el.dataset.plan,dy:e.clientY-el.getBoundingClientRect().top};
      e.dataTransfer.setData('text/plain',el.dataset.plan); e.dataTransfer.effectAllowed='move';
      requestAnimationFrame(()=>el.classList.add('drag'));
    };
    el.ondragend=()=>{if(WEEK.drag){WEEK.drag=null;renderWeek(true)}};
  });
  W.querySelectorAll('.ev[data-ran]').forEach(el=>el.onclick=()=>{
    const a=AGENTS.find(x=>x.id===el.dataset.agent);
    if(a){go('sessions');select(a.key)}else openSheet(el.dataset.ran);
  });
}

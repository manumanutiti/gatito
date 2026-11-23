/* "Profiles" view (#/profiles[/<id>]): the task profiles (profiles/*.md) inside out.
   What the agent does with each one, what it can and cannot touch, and what Claude Code
   really receives (effective prompt and rules, including the read-only and always-on ones).
   Read-only: a profile is edited in its file, and gatito re-reads it without restarting.
   Files that fail validation are listed too, with the reason: otherwise a badly written
   profile would vanish from the selector without anyone knowing why. */

let PF={listing:[],root:'',id:null,card:null,sig:''};

function pfHash(id){return id?`#/profiles/${encodeURIComponent(id)}`:'#/profiles'}
function pfMode(m){return m?label('modes',m):'whichever you pick'}

function initPf(){
  $('#v-pf').innerHTML=`<header class="vh"><h1>Profiles</h1><span class="sub" id="pf-sub"></span>
    <div class="vh-tools"><input class="art-q" id="pf-q" type="search" placeholder="Filter profiles…" aria-label="Filter profiles"></div></header>
    <div class="nb-body">
      <aside class="nb-side pf-side" id="pf-side"><div class="nb-tree" id="pf-list"></div></aside>
      <section class="nb-main" id="pf-main"></section>
    </div>`;
  $('#pf-q').oninput=()=>renderPfList();
}

async function renderPf(force){
  if(VIEW!=='pf'&&!force)return;
  try{const r=await api('/api/profiles');
    const sig=JSON.stringify(r.profiles);
    if(sig===PF.sig&&!force)return;
    PF.sig=sig; PF.listing=r.profiles; PF.root=r.root;
  }catch(e){return}
  const n=PF.listing.filter(p=>p.valid).length, bad=PF.listing.length-n;
  $('#pf-sub').textContent=`${n} profile${n===1?'':'s'}${bad?` · ${bad} with errors`:''}`;
  renderPfList();
  if(!PF.id)renderPfHome();
}

function pfDot(p){return`<i class="nb-dot ${!p.valid?'e-mal':p.read_only?'e-review':'e-done'}"></i>`}
function renderPfList(){
  const f=($('#pf-q')?.value||'').trim().toLowerCase();
  const l=PF.listing.filter(p=>!f||[p.id,p.title,p.description].join(' ').toLowerCase().includes(f));
  $('#pf-list').innerHTML=l.map(p=>`<a class="nb-row pf-row${p.id===PF.id?' on':''}" href="${pfHash(p.id)}">
      ${pfDot(p)}<span class="pf-rt"><b>${esc(p.title)}</b>
      <span>${p.valid?esc(p.description||''):`<span class="pf-bad">not used: ${esc(p.warnings[0]||'')}</span>`}</span></span></a>`).join('')
    ||`<p class="nb-empty">${PF.listing.length?'Nothing matches that filter.':'No profiles: add one in profiles/.'}</p>`;
}

function pfChips(p){
  const c=[];
  c.push(p.read_only?'<span class="nb-chip pf-ro">Read-only</span>':'<span class="nb-chip pf-rw">Can write</span>');
  if(p.model)c.push(`<span class="nb-chip" title="Model">${esc(label('models',p.model))}</span>`);
  c.push(`<span class="nb-chip" title="Permission mode">permissions: ${esc(pfMode(p.mode))}</span>`);
  if(p.effort)c.push(`<span class="nb-chip" title="Effort">effort: ${esc(p.effort)}</span>`);
  if(p.worktree)c.push(`<span class="nb-chip" title="Launches in an isolated worktree by default">${ICON('branch')}worktree</span>`);
  for(const nb of p.notebooks||[])c.push(`<a class="nb-chip tag" href="#/notebooks/${encodeURIComponent(nb)}" title="Starts by reading this notebook">${ICON('book')}${esc(nb)}</a>`);
  return c.join('');
}

function renderPfHome(){
  const m=$('#pf-main'); if(!m)return;
  $('#v-pf').classList.remove('reading');
  const ok=PF.listing.filter(p=>p.valid);
  m.innerHTML=`<article class="nb-doc">
    <h1 class="nb-h">Task profiles</h1>
    <p class="nb-lead">A profile decides how an agent works and, above all, what it can touch. You pick it in the
      composer ("Profile: …"); its model, permission and effort values can be changed by hand,
      except in a read-only one, which always runs in "Don't ask".</p>
    ${ok.length?`<div class="nb-table"><table class="pf-table"><thead><tr><th>Profile</th><th>Touches</th><th>Model</th><th>Permissions</th><th>Notebooks</th></tr></thead><tbody>
      ${ok.map(p=>`<tr><td><a href="${pfHash(p.id)}"><b>${esc(p.title)}</b></a><div class="pf-desc">${esc(p.description||'')}</div></td>
        <td>${p.read_only?'<span class="nb-chip pf-ro">read</span>':'<span class="nb-chip pf-rw">write</span>'}</td>
        <td>${esc(p.model?label('models',p.model):'—')}</td><td>${esc(pfMode(p.mode))}</td>
        <td>${(p.notebooks||[]).map(esc).join(', ')||'—'}</td></tr>`).join('')}</tbody></table></div>`:''}
    <p class="nb-hint">They live in <code>${esc(PF.root)}</code>, one per <code>.md</code> file: metadata on top and,
      below it, the text added to the agent's instructions. Edit the file and gatito re-reads it without restarting.</p>
  </article>`;
}

async function openPf(id){
  PF.id=id; renderPfList();
  $('#v-pf').classList.add('reading');
  const m=$('#pf-main');
  if(!PF.card||PF.card.id!==id)m.innerHTML='<div class="art-empty">Loading…</div>';
  const r=await api('/api/profile?id='+encodeURIComponent(id)).catch(()=>({ok:false}));
  if(PF.id!==id)return;
  if(!r.ok){m.innerHTML=`<div class="art-empty">${esc(r.err||'Could not load the profile.')}</div>`;return}
  PF.card=r; renderPfCard();
}
function closePf(){PF.id=null;PF.card=null;renderPfList();renderPfHome()}

function pfRules(l,empty){
  return l&&l.length?`<ul class="pf-rules">${l.map(x=>`<li><code>${esc(x)}</code></li>`).join('')}</ul>`:`<p class="nb-empty">${empty}</p>`;
}
function renderPfCard(){
  const r=PF.card, p=r.profile, ef=r.effective, m=$('#pf-main');
  const bar=`<div class="nb-bar"><a class="btn ghost icon nb-up pf-up" href="#/profiles" aria-label="Back">${ICON('back')}</a>
      <div class="nb-crumb"><a href="#/profiles">Profiles</a> · ${esc(r.file)}</div><span class="spacer"></span>
      ${p?`<button class="btn primary" id="pf-use" type="button">${ICON('chat')}Use in a session</button>`:''}</div>`;
  const warnings=r.warnings.length?`<div class="nb-warn pf-warn"><b>${p?'Part of the file was ignored':'This profile is not used'}</b>
      <ul>${r.warnings.map(a=>`<li>${esc(a)}</li>`).join('')}</ul></div>`:'';
  const file=`<details class="pf-det"><summary>File <code>${esc(r.relpath)}</code></summary>
      <pre class="pf-pre">${esc(r.text)}</pre>
      <p class="nb-hint">Edit it there (in the gatito repo); it is re-read on next use, no restart needed.</p></details>`;
  if(!p){m.innerHTML=`<article class="nb-doc">${bar}<h1 class="nb-h">${esc(r.id)}</h1>${warnings}${file}</article>`;return}
  const extra=ef.allow.length-p.allow.length, nbs=ef.notebooks;
  m.innerHTML=`<article class="nb-doc">${bar}
    <h1 class="nb-h">${esc(p.title)}</h1>
    <div class="nb-meta">${pfChips(p)}</div>
    ${p.description?`<p class="nb-lead">${esc(p.description)}</p>`:''}
    ${warnings}
    <div class="nb-cols pf-cols">
      <section class="nb-panel"><div class="nb-sec">Can</div>
        ${p.read_only?`<p class="pf-p">Only read commands (git, kubectl, helm, terraform plan…: ${extra} allowlist rules) and
          writing its output to notebooks, artifacts and diagrams. Everything else is denied without asking.</p>`
          :`<p class="pf-p">Whatever the "${esc(pfMode(p.mode))}" mode allows, inside the session folder${p.worktree?' (by default, in an isolated worktree)':''}.</p>`}
        ${p.allow.length?`<div class="pf-sub">In addition, this profile allows</div>${pfRules(p.allow)}`:''}
        ${nbs.length?`<div class="pf-sub">Starts by reading</div><p class="pf-p">${nbs.map(nb=>`<a href="#/notebooks/${encodeURIComponent(nb)}">notebook "${esc(nb)}"</a>`).join(', ')}</p>`:''}
      </section>
      <section class="nb-panel"><div class="nb-sec">Cannot</div>
        ${p.deny.length?`<div class="pf-sub">This profile denies</div>${pfRules(p.deny)}`:''}
        <div class="pf-sub">No gatito agent (always)</div>${pfRules(ef.always)}
      </section>
    </div>
    <h2 class="pf-h2">Profile instructions</h2>
    <div class="nb-md pf-md">${p.body?nbMd(p.body,{id:'',dir:'',ro:true}):'<p class="nb-empty">No text: it only changes permissions and values.</p>'}</div>
    <h2 class="pf-h2">What Claude Code receives</h2>
    <details class="pf-det"><summary>Allowed rules (${ef.allow.length})</summary>${pfRules(ef.allow,'None besides those of the mode.')}</details>
    <details class="pf-det"><summary>Denied rules (${ef.deny.length+ef.always.length})</summary>${pfRules([...ef.always,...ef.deny])}</details>
    <details class="pf-det"><summary>Text added to the agent's instructions</summary><pre class="pf-pre">${esc(ef.prompt)}</pre></details>
    ${file}
  </article>`;
  wireNbMd($('.pf-md'));
  $('#pf-use').onclick=()=>useProfile(p.id);
}

// "Use in a session": the composer with the chosen profile (and its values), ready to type
function useProfile(id){
  go('sessions');
  if(CUR&&typeof closeDetail==='function')closeDetail();
  const pf=$('#q-profile'); pf.value=id; pf.dispatchEvent(new Event('change'));
  q.focus();
}

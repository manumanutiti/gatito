/* Notifications (Web Push): register the service worker, turn them on/off on this
   device and choose which ones arrive. The dialog guides you through whatever is
   missing: using https, installing the gatito certificate, granting permission… */

const PUSH_KINDS=[
  ['waiting','An agent is waiting for you','It needs your reply or a permission.'],
  ['done','An agent finished','With the result, if it gives one.'],
  ['failed','A task could not be launched','From the backlog or the week.'],
  ['launched','A scheduled task starts','Every time one from the week starts.'],
];
let SWREG=null;

function b64bytes(s){const b=atob((s+'='.repeat((4-s.length%4)%4)).replace(/-/g,'+').replace(/_/g,'/'));
  return Uint8Array.from(b,c=>c.charCodeAt(0))}
const isLocal=()=>['localhost','127.0.0.1'].includes(location.hostname);

async function swRegister(){
  if(!('serviceWorker' in navigator)||!isSecureContext)return null;
  try{SWREG=await navigator.serviceWorker.register('/sw.js');return SWREG}
  catch(e){SWREG=null;return {error:e}}
}
async function pushState(){
  if(!isSecureContext)return{s:'insecure'};
  if(!('serviceWorker' in navigator))return{s:'unsupported'};
  const reg=await swRegister();
  if(!reg||reg.error)return{s:'cert',err:reg?.error?.message};
  if(!('PushManager' in window))return{s:'unsupported'};
  if(Notification.permission==='denied')return{s:'denied'};
  const sub=await reg.pushManager.getSubscription();
  return{s:sub?'on':'off',reg,sub};
}
function deviceLabel(){
  const ua=navigator.userAgent;
  const os=/Android/.test(ua)?'Android':/iPhone|iPad/.test(ua)?'iPhone':/Linux/.test(ua)?'Linux':/Mac/.test(ua)?'Mac':/Windows/.test(ua)?'Windows':'';
  const br=/Brave/.test(ua)||navigator.brave?'Brave':/Firefox/.test(ua)?'Firefox':/Edg/.test(ua)?'Edge':/Chrome/.test(ua)?'Chrome':/Safari/.test(ua)?'Safari':'browser';
  return `${br} on ${os||'this machine'}`;
}
async function markBell(){
  const st=await pushState().catch(()=>({s:'?'}));
  $('#rail-bell').setAttribute('aria-pressed',st.s==='on');
  $('#rail-bell').title=st.s==='on'?'Notifications are on for this device':'Turn on notifications';
}

async function openNotify(){
  const st=await pushState();
  let body='';
  if(st.s==='insecure')body=`<p>Notifications need a secure connection. Open gatito at its https address:</p>
    <p><a class="lnk" href="${esc(META.lan_url)}">${esc(META.lan_url)}</a></p>
    <p>The first time you will have to install the gatito certificate: I'll explain when you get there.</p>`;
  else if(st.s==='cert')body=`<p>This browser doesn't trust gatito yet. Install its certificate once:</p>
    <p><a class="btn primary" href="/ca.crt" download>${ICON('check')}Download certificate</a></p>
    <ol class="steps">
      <li><b>Android:</b> Settings, Security and privacy, More security settings, Encryption and credentials,
        Install a certificate, <i>CA certificate</i>. Pick <i>gatito-ca.crt</i>.</li>
      <li><b>iPhone:</b> open the downloaded file, go to Settings, General, VPN and Device Management and
        install it. Then, in General, About, Certificate Trust Settings, turn on
        <i>Gatito CA</i>.</li>
      <li>Close and reopen the browser, open gatito again and tap Notifications.</li></ol>
    <p class="fine">The certificate only lets your phone recognize this PC; it gives access to nothing.</p>`;
  else if(st.s==='unsupported')body=`<p>This browser doesn't support notifications like this. On iPhone, add gatito to the
    home screen (Share, Add to Home Screen), open it from that icon and come back here.</p>`;
  else if(st.s==='denied')body=`<p>You have blocked gatito notifications in this browser. Allow them in the
    site settings (the lock next to the address) and try again.</p>`;
  else if(st.s==='off')body=`<p>Get a notification on ${esc(deviceLabel())} when an agent needs you or
    finishes, even if gatito is closed.</p>
    ${navigator.brave?`<p class="fine">Brave ships with the service that delivers notifications turned off. Before enabling them,
      turn on <b>Use Google services for push messaging</b> in Brave's privacy settings
      (on the PC: <i>brave://settings/privacy</i>). Notifications are encrypted: Google can't read them.</p>`:''}
    <p><button class="btn primary" data-on>${ICON('bell')}Turn on notifications here</button></p>
    <p class="fine" id="nt-err"></p>`;
  else{
    const cur=await api('/api/push/get',{endpoint:st.sub.endpoint}).catch(()=>({}));
    const prefs=cur.prefs||{};
    body=`<p>Notifications are on for ${esc(deviceLabel())}. Choose which ones you want:</p>
      <div class="kinds">${PUSH_KINDS.map(([k,t,d])=>`<label class="check"><input type="checkbox" data-k="${k}"
        ${prefs[k]??(k!=='launched')?'checked':''}><span><b>${t}</b><small>${d}</small></span></label>`).join('')}</div>
      <p class="row-btns"><button class="btn" data-test>Send a test</button>
        <button class="btn ghost danger" data-off>Turn off here</button></p>`;
  }
  const d=dialog(`<h3>Notifications</h3>${body}<div class="acts"><button class="btn ghost" data-x>Close</button></div>`,'notify');
  d.querySelector('[data-x]').onclick=()=>d.close();
  d.querySelector('[data-on]')?.addEventListener('click',async e=>{
    e.target.disabled=true;
    try{
      if(await Notification.requestPermission()!=='granted')throw new Error('No permission to notify.');
      const {key}=await api('/api/push/key');
      const sub=await st.reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64bytes(key)});
      const r=await api('/api/push/subscribe',{subscription:sub.toJSON(),label:deviceLabel()});
      if(!r.ok)throw new Error(r.err||'gatito did not accept the subscription');
      toast('Notifications on'); d.close(); markBell(); openNotify();
    }catch(err){
      e.target.disabled=false;
      // Brave doesn't use Google's push service unless you turn it on
      $('#nt-err').innerHTML=/push service|AbortError|registration/i.test(err.message+err.name)
        ?'The browser could not register with its notification service. In Brave, turn on "Use Google services for push messaging" in <i>brave://settings/privacy</i> and try again.'
        :esc(err.message);
    }
  });
  d.querySelectorAll('[data-k]').forEach(c=>c.onchange=async()=>{
    const prefs=Object.fromEntries([...d.querySelectorAll('[data-k]')].map(x=>[x.dataset.k,x.checked]));
    const r=await api('/api/push/subscribe',{subscription:st.sub.toJSON(),prefs,label:deviceLabel()});
    toast(r.ok?'Saved':'Could not save',!r.ok);
  });
  d.querySelector('[data-test]')?.addEventListener('click',async()=>{
    const r=await api('/api/push/test',{endpoint:st.sub.endpoint});
    toast(r.sent?'Test sent':'It did not reach the notification service'+(r.err?': '+r.err:''),!r.sent);
  });
  d.querySelector('[data-off]')?.addEventListener('click',async()=>{
    await api('/api/push/unsubscribe',{endpoint:st.sub.endpoint}); await st.sub.unsubscribe();
    toast('Notifications turned off here'); d.close(); markBell();
  });
}

// when a notification is tapped with gatito open, the service worker tells us where to go
navigator.serviceWorker?.addEventListener('message',e=>{if(e.data?.open!=null)location.hash=e.data.open||'#/'});

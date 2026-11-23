/* gatito service worker: receives notifications (Web Push, encrypted) and, when they are tapped,
   opens the session or task in the web app. Served at /sw.js to control the whole site. */
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));

self.addEventListener('push',e=>{
  let m={}; try{m=e.data.json()}catch(_){m={title:'Gatito',body:e.data?e.data.text():''}}
  // a permission can only be denied from the notification: to allow it you must open gatito and see it
  e.waitUntil(self.registration.showNotification(m.title||'Gatito',{
    body:m.body||'',tag:m.tag||m.kind,renotify:true,data:{url:m.url||'/',perm:m.perm||null},
    actions:m.perm?[{action:'deny',title:'Deny'}]:[],
    icon:'/icon-192.png',badge:'/badge-96.png'}));
});

self.addEventListener('notificationclick',e=>{
  e.notification.close();
  const d=e.notification.data||{};
  if(e.action==='deny'&&d.perm){
    e.waitUntil(fetch('/api/perm/decide',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({id:d.perm,behavior:'deny'})})
      .then(r=>r.json()).catch(()=>({ok:false}))
      .then(r=>self.registration.showNotification('Gatito',{tag:'perm-res',
        body:r.ok?'Denied.':'Could not deny: '+(r.err||'offline'),
        icon:'/icon-192.png',badge:'/badge-96.png'})));
    return;
  }
  const url=new URL(d.url||'/',self.location.origin);
  e.waitUntil((async()=>{
    // if gatito is already open, use that tab; otherwise open it
    const open=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const c=open.find(c=>new URL(c.url).origin===url.origin);
    if(c){await c.focus();c.postMessage({open:url.hash});return}
    await self.clients.openWindow(url.href);
  })());
});

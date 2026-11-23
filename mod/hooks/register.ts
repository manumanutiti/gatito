import type { Register } from 'claude-code'

// "gatito" mod: messenger between this Claude Code session and gatitod (~/gatito/gatitod/modlink.py).
// It decides nothing on its own: if gatitod doesn't answer, Claude carries on exactly as without the mod.

let sock = ''
let sid = ''

async function call($: any, method: string, path: string, body?: object) {
  const res = await $.http.fetch(`http://gatito${path}`, {
    method,
    socketPath: sock,
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  })
  if (!res.ok) throw new Error(`gatito ${res.status}`)
  return JSON.parse(res.text || '{}')
}

function tell($: any, body: object) {
  return call($, 'POST', '/mod/event', { sid, ...body }).catch(() => undefined)
}

async function hello($: any) {
  sid = await $.session.id()
  const v = await $.session.version().catch(() => undefined)
  await tell($, { ev: 'start', cwd: await $.session.cwd(), version: v?.version })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    sock = (await $.env.get('GATITO_SOCK')) || `${await $.env.get('HOME')}/gatito/state/gatito.sock`
    await hello($)
    // the inbox: what you type in gatito for this session; it also tells gatito the session is still alive
    $.clock.every(3000, async () => {
      try {
        const { texts } = await call($, 'GET', `/mod/inbox?sid=${sid}`)
        for (const text of texts || []) await $.prompt.submit({ text, asUser: true })
      } catch {
        // gatitod is off: nothing to deliver
      }
    })
    return r
  })

  on('turn.start', async ($, e, next) => {
    if (!e.agentId) await tell($, { ev: 'turn' })
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) await tell($, { ev: 'idle', reason: e.reason })
    return next(e)
  })

  // A question with options: gatito shows it as buttons. Whoever answers first wins;
  // if gatito answers, its answer goes to Claude and the terminal dialog closes.
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const questions = (e as any).questions
    let id: string
    try {
      ;({ id } = await call($, 'POST', '/mod/perm', { sid, kind: 'ask', tool: 'AskUserQuestion', input: { questions } }))
    } catch {
      return next(e)
    }
    let done = false
    const dialog = next(e).then(r => {
      done = true
      return r
    })
    dialog.catch(() => undefined) // if gatito answers, the dialog closes and its promise fails: doesn't matter
    const remote = (async () => {
      while (!done) {
        const r = await call($, 'GET', `/mod/perm?id=${id}`)
        if (r.status === 'answered') return r.answers as Record<string, string>
        if (r.status !== 'pending') return null
      }
      return null
    })().catch(() => null)
    const first = await Promise.race([dialog.then(r => ({ r })), remote.then(answers => ({ answers }))])
    // returning while the dialog is still open closes it: gatito's answer is the one that counts
    if ('answers' in first && first.answers) return { result: { questions, answers: first.answers } } as any
    call($, 'POST', '/mod/perm/end', { id, why: 'terminal' }).catch(() => undefined)
    return 'r' in first ? first.r : dialog
  }).catch(($, e, next) => (next.called ? { deny: 'gatito: the question failed; ask it again' } : next(e)))

  // Claude was about to ask for permission: the dialog shows in the terminal and, at the same
  // time, gatito offers it on the web and phone. Whoever answers first wins; if nobody does, the dialog stays.
  on('classic.PermissionRequest', async ($, e, next) => {
    // questions and plan approval are yours in the terminal, not a permission
    if (e.tool_name === 'AskUserQuestion' || e.tool_name === 'ExitPlanMode') return next(e)
    let id: string
    try {
      ;({ id } = await call($, 'POST', '/mod/perm', {
        sid,
        tool: e.tool_name,
        input: e.tool_input,
        mode: e.permission_mode,
        agent: e.agent_type,
        suggestions: e.permission_suggestions,
      }))
    } catch {
      return next(e)
    }
    let why = 'timeout'
    try {
      // each poll waits up to 20 s in gatito ($.http.fetch cuts off at 30)
      while (!next.signal.aborted) {
        const r = await call($, 'GET', `/mod/perm?id=${id}`)
        if (r.status === 'allow' || r.status === 'deny') return { ...(await next(e)), decision: r.decision }
        if (r.status !== 'pending') return next(e)
      }
      why = 'terminal'
    } catch {
      why = next.signal.aborted ? 'terminal' : 'error'
    }
    call($, 'POST', '/mod/perm/end', { id, why }).catch(() => undefined)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    await tell($, { ev: 'end', reason: e.reason })
    const r = await next(e)
    // after /clear the session continues with another id
    if (e.reason === 'clear') await hello($).catch(() => undefined)
    return r
  })
}

import { useEffect, useState, useCallback } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || ''
const COGNITO_DOMAIN = import.meta.env.VITE_COGNITO_DOMAIN || ''
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID || ''
const REDIRECT_URI = import.meta.env.VITE_REDIRECT_URI || window.location.origin

const TK = { id: 'ia_id_token', access: 'ia_access_token', refresh: 'ia_refresh_token', pkce: 'ia_pkce_verifier' }

const store = {
  get: (k) => sessionStorage.getItem(k),
  set: (k, v) => sessionStorage.setItem(k, v),
  clearTokens: () => [TK.id, TK.access, TK.refresh].forEach((k) => sessionStorage.removeItem(k)),
}

function b64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
async function makePkce() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)))
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return { verifier, challenge: b64url(digest) }
}
function decodeJwt(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(decodeURIComponent(escape(atob(payload))))
  } catch {
    return {}
  }
}
function groupsFromIdToken() {
  const id = store.get(TK.id)
  if (!id) return []
  const g = decodeJwt(id)['cognito:groups']
  return Array.isArray(g) ? g : g ? [g] : []
}

async function login() {
  const { verifier, challenge } = await makePkce()
  store.set(TK.pkce, verifier)
  const params = new URLSearchParams({
    response_type: 'code', client_id: CLIENT_ID, redirect_uri: REDIRECT_URI,
    scope: 'openid email profile', identity_provider: 'Google',
    code_challenge: challenge, code_challenge_method: 'S256',
  })
  window.location.assign(`${COGNITO_DOMAIN}/oauth2/authorize?${params.toString()}`)
}
function logout() {
  store.clearTokens()
  const params = new URLSearchParams({ client_id: CLIENT_ID, logout_uri: REDIRECT_URI })
  window.location.assign(`${COGNITO_DOMAIN}/logout?${params.toString()}`)
}
async function exchangeCodeForTokens(code) {
  const body = new URLSearchParams({
    grant_type: 'authorization_code', client_id: CLIENT_ID, code,
    redirect_uri: REDIRECT_URI, code_verifier: store.get(TK.pkce) || '',
  })
  const res = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body,
  })
  if (!res.ok) throw new Error('Token exchange failed')
  const t = await res.json()
  if (t.id_token) store.set(TK.id, t.id_token)
  if (t.access_token) store.set(TK.access, t.access_token)
  if (t.refresh_token) store.set(TK.refresh, t.refresh_token)
}
async function refreshTokens() {
  const rt = store.get(TK.refresh)
  if (!rt) return false
  const body = new URLSearchParams({ grant_type: 'refresh_token', client_id: CLIENT_ID, refresh_token: rt })
  const res = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body,
  })
  if (!res.ok) return false
  const t = await res.json()
  if (t.id_token) store.set(TK.id, t.id_token)
  if (t.access_token) store.set(TK.access, t.access_token)
  return true
}
async function apiFetch(path, options = {}) {
  const doFetch = () =>
    fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${store.get(TK.id) || ''}`,
        ...(options.headers || {}),
      },
    })
  let res = await doFetch()
  if (res.status === 401 && (await refreshTokens())) res = await doFetch()
  return res
}
async function gql(query, variables) {
  const res = await apiFetch('/graphql', { method: 'POST', body: JSON.stringify({ query, variables }) })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || data.errors?.length) throw new Error(data.errors?.[0]?.message || `Request failed (${res.status})`)
  return data.data
}

const CHAT_QUERY = `query ChatQuery($prompt: String!) { chatQuery(prompt: $prompt) { summary intent rows } }`
const SMART_QUERY = `query Smart($prompt:String,$ticker:String,$source:String,$closesOnly:Boolean,$range:String){ smartQuery(prompt:$prompt,ticker:$ticker,source:$source,closesOnly:$closesOnly,range:$range){ summary intent parsed rows } }`
const RECENT_QUERY = `query Recent($range: String!) { recentRecommendations(range: $range) { id message_id ticker action source email_date sentiment confidence email_subject price_target stop_loss_price instrument_type option_symbol } }`
const FEEDBACK_MUT = `mutation Feedback($messageId:String!,$ticker:String!,$reason:String,$note:String,$modelAction:String,$source:String,$emailSubject:String){ submitFeedback(messageId:$messageId,ticker:$ticker,reason:$reason,note:$note,modelAction:$modelAction,source:$source,emailSubject:$emailSubject){ ok message error } }`

const PROMPT_STATE = `query { promptState { current_version current_body pending { reasoning changes diff based_on } history { version note reasoning created_at } } }`
const PROMPT_SUGGEST = `mutation { suggestPrompt { ok error pending { reasoning changes diff based_on } } }`
const PROMPT_APPROVE = `mutation { approvePrompt { ok error current_version } }`
const PROMPT_DISCARD = `mutation { discardPrompt { ok } }`
const PROMPT_ROLLBACK = `mutation Rollback($version: Int!) { rollbackPrompt(version: $version) { ok error current_version } }`

function actionClass(action) {
  const a = (action || '').toUpperCase()
  if (['BUY', 'POSITIVE'].includes(a)) return 'badge-buy'
  if (['SELL', 'STOP_LOSS', 'CLOSE', 'NEGATIVE'].includes(a)) return 'badge-sell'
  return 'badge-neutral'
}

export default function App() {
  const [authState, setAuthState] = useState('loading')
  const [profile, setProfile] = useState(null)
  const [active, setActive] = useState(false)

  useEffect(() => {
    (async () => {
      const params = new URLSearchParams(window.location.search)
      if (params.get('error')) { window.history.replaceState({}, '', REDIRECT_URI); setAuthState('anon'); return }
      if (params.get('code')) {
        try { await exchangeCodeForTokens(params.get('code')) } catch { /* noop */ }
        window.history.replaceState({}, '', REDIRECT_URI)
      }
      const id = store.get(TK.id)
      if (id) {
        const claims = decodeJwt(id)
        setProfile({ email: claims.email, name: claims.name })
        setActive(groupsFromIdToken().includes('active'))
        setAuthState('authed')
      } else {
        setAuthState('anon')
      }
    })()
  }, [])

  const onRedeemed = useCallback(async () => {
    await refreshTokens()
    setActive(groupsFromIdToken().includes('active'))
  }, [])

  if (authState === 'loading') {
    return <div className="container container-chat"><div className="card card-chat"><p className="intro">Loading…</p></div></div>
  }
  if (authState === 'anon') {
    return (
      <div className="container container-chat"><div className="card card-chat">
        <img src="/Inbox-Ag.png" alt="Inbox Aggregator" className="logo" />
        <h1>Inbox Aggregator</h1>
        <p className="tagline">Stock alert notifications</p>
        <div className="auth-landing">
          <p className="intro">Sign in with the Google account you were invited with.</p>
          <button type="button" className="btn-primary" onClick={login}>Sign in with Google</button>
        </div>
      </div></div>
    )
  }
  if (!active) {
    return (
      <div className="container container-chat"><div className="card card-chat">
        <img src="/Inbox-Ag.png" alt="Inbox Aggregator" className="logo" />
        <h1>Inbox Aggregator</h1>
        <Redeem profile={profile} onRedeemed={onRedeemed} onSignOut={logout} />
      </div></div>
    )
  }
  return <Shell profile={profile} />
}

function Redeem({ profile, onRedeemed, onSignOut }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e) {
    e.preventDefault()
    if (!password.trim()) return setError('Enter the invitation password.')
    setBusy(true); setError('')
    try {
      const res = await apiFetch('/redeem', { method: 'POST', body: JSON.stringify({ password }) })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.error || 'Could not redeem. Check the password and try again.'); return }
      await onRedeemed()
    } catch { setError('Network error. Please try again.') } finally { setBusy(false) }
  }
  return (
    <form onSubmit={submit} className="form">
      <p className="intro">Signed in as <strong>{profile?.email || 'your account'}</strong>. Enter the invitation password to activate your account.</p>
      <div className="field">
        <label htmlFor="invpw">Invitation Password</label>
        <input id="invpw" type="password" value={password} autoFocus onChange={(e) => setPassword(e.target.value)} />
        {error && <span className="error">{error}</span>}
      </div>
      <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Activating…' : 'Activate account'}</button>
      <button type="button" className="btn-link" onClick={onSignOut}>Sign out</button>
    </form>
  )
}

function Shell({ profile }) {
  const [view, setView] = useState('home')
  const [menuOpen, setMenuOpen] = useState(false)
  const initial = (profile?.email || '?').charAt(0).toUpperCase()
  return (
    <div className="app">
      <header className="masthead">
        <button type="button" className="brand" onClick={() => { setView('home'); setMenuOpen(false) }}>
          <img src="/Inbox-Ag.png" alt="" className="brand-logo" />
          <span className="brand-name">Inbox Aggregator</span>
        </button>
        <div className="user-area">
          <button type="button" className="user-pill" onClick={() => setMenuOpen((o) => !o)} aria-haspopup="true" aria-expanded={menuOpen}>
            <span className="avatar">{initial}</span>
            <span className="user-email">{profile?.email}</span>
            <span aria-hidden="true">▾</span>
          </button>
          {menuOpen && (
            <div className="user-menu" role="menu">
              <button type="button" className="menu-item" onClick={() => { setView('settings'); setMenuOpen(false) }}>Notification settings</button>
              <button type="button" className="menu-item" onClick={() => { setView('tuning'); setMenuOpen(false) }}>Prompt tuning</button>
              <button type="button" className="menu-item" onClick={logout}>Sign out</button>
            </div>
          )}
        </div>
      </header>
      <main className="app-body">
        {view === 'settings' ? (
          <section className="panel">
            <button type="button" className="btn-link back" onClick={() => setView('home')}>← Back to recommendations</button>
            <h2 className="panel-title">Notification settings</h2>
            <Channels />
          </section>
        ) : view === 'tuning' ? (
          <section className="panel">
            <button type="button" className="btn-link back" onClick={() => setView('home')}>← Back to recommendations</button>
            <h2 className="panel-title">Prompt tuning</h2>
            <PromptTuning />
          </section>
        ) : (
          <>
            <Feed />
            <QueryPanel />
          </>
        )}
      </main>
    </div>
  )
}

const RANGES = [{ key: 'today', label: 'Today' }, { key: 'week', label: 'This week' }, { key: 'month', label: 'This month' }]
const REASONS = [
  { code: 'wrong_action', label: 'Wrong action' },
  { code: 'wrong_ticker', label: 'Wrong ticker' },
  { code: 'not_a_rec', label: 'Not a rec' },
  { code: 'wrong_source', label: 'Wrong source' },
]

function Feed() {
  const [range, setRange] = useState('today')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (r) => {
    setLoading(true); setError('')
    try {
      const data = await gql(RECENT_QUERY, { range: r })
      setRows(data.recentRecommendations || [])
    } catch (e) { setError(e.message); setRows([]) } finally { setLoading(false) }
  }, [])

  useEffect(() => { load(range) }, [load, range])

  return (
    <section className="panel">
      <div className="feed-head">
        <div className="view-toggle" role="tablist">
          {RANGES.map((r) => (
            <button key={r.key} type="button" className={`toggle-btn ${range === r.key ? 'active' : ''}`} onClick={() => setRange(r.key)}>{r.label}</button>
          ))}
        </div>
        <span className="feed-count">{loading ? '…' : `${rows.length} recommendation${rows.length === 1 ? '' : 's'}`}</span>
      </div>
      {error && <div className="submit-error">{error}</div>}
      {loading ? (
        <p className="intro">Loading recommendations…</p>
      ) : rows.length === 0 ? (
        <p className="chat-empty">No recommendations in this period.</p>
      ) : (
        <div className="feed-list">{rows.map((r) => <FeedCard key={r.id} rec={r} />)}</div>
      )}
    </section>
  )
}

function FeedCard({ rec }) {
  const [flagging, setFlagging] = useState(false)
  const [done, setDone] = useState(false)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!reason && !note.trim()) { setError('Pick a reason or add a note.'); return }
    setBusy(true); setError('')
    try {
      const data = await gql(FEEDBACK_MUT, {
        messageId: rec.message_id, ticker: rec.ticker, reason, note: note.trim(),
        modelAction: rec.action, source: rec.source, emailSubject: rec.email_subject,
      })
      if (data.submitFeedback?.ok) { setDone(true); setFlagging(false) }
      else setError(data.submitFeedback?.error || 'Could not save feedback.')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className={`feed-card ${flagging ? 'flagging' : ''}`}>
      <div className="feed-card-head">
        <span className="fc-ticker">{rec.ticker}</span>
        <span className={`badge ${actionClass(rec.action)}`}>{(rec.action || '').replace('_', ' ')}</span>
        <span className="fc-meta">{rec.source || 'Unknown'} · {rec.email_date}</span>
        {done ? (
          <span className="fc-flagged"><span aria-hidden="true">✓</span> Flagged</span>
        ) : (
          <button type="button" className="flag-btn" aria-label="Flag as incorrect" onClick={() => setFlagging((f) => !f)}>⚐</button>
        )}
      </div>
      {rec.sentiment && <p className="fc-sentiment">"{rec.sentiment}"</p>}
      {(rec.price_target || rec.stop_loss_price || rec.option_symbol) && (
        <div className="fc-tags">
          {rec.price_target && <span className="fc-tag">Target ${rec.price_target}</span>}
          {rec.stop_loss_price && <span className="fc-tag">Stop ${rec.stop_loss_price}</span>}
          {rec.option_symbol && <span className="fc-tag">{rec.option_symbol}</span>}
        </div>
      )}
      {flagging && (
        <div className="feedback-form">
          <p className="fb-label">What's wrong with this recommendation?</p>
          <div className="chips">
            {REASONS.map((r) => (
              <button key={r.code} type="button" className={`chip ${reason === r.code ? 'chip-on' : ''}`} onClick={() => setReason(reason === r.code ? '' : r.code)}>{r.label}</button>
            ))}
          </div>
          <textarea className="fb-note" rows={2} placeholder="Optional: what should it have been?" value={note} onChange={(e) => setNote(e.target.value)} />
          {error && <div className="submit-error">{error}</div>}
          <div className="fb-actions">
            <button type="button" className="btn-small" disabled={busy} onClick={submit}>{busy ? 'Saving…' : 'Submit feedback'}</button>
            <button type="button" className="btn-link" onClick={() => setFlagging(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}

function PromptTuning() {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showCurrent, setShowCurrent] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { const d = await gql(PROMPT_STATE); setState(d.promptState) }
    catch (e) { setError(e.message) } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  async function run(query, vars, okMsg) {
    setBusy(true); setError(''); setNotice('')
    try {
      const d = await gql(query, vars)
      const res = d.suggestPrompt || d.approvePrompt || d.discardPrompt || d.rollbackPrompt
      if (res && res.ok === false) { setError(res.error || 'Action failed.'); return }
      if (okMsg) setNotice(okMsg)
      await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  if (loading) return <p className="intro">Loading prompt…</p>
  if (!state) return <div className="submit-error">{error || 'Could not load prompt state.'}</div>
  const pending = state.pending
  return (
    <div className="tuning">
      {error && <div className="submit-error">{error}</div>}
      {notice && <div className="notice">{notice}</div>}
      <div className="tune-row">
        <span>Active version <strong>v{state.current_version}</strong></span>
        <button type="button" className="btn-link" onClick={() => setShowCurrent((v) => !v)}>{showCurrent ? 'Hide' : 'View'} current prompt</button>
      </div>
      {showCurrent && <pre className="prompt-pre">{state.current_body}</pre>}

      {!pending ? (
        <div className="tune-suggest">
          <p className="intro">Draft a prompt improvement from your flagged recommendations.</p>
          <button type="button" className="btn-primary" disabled={busy} onClick={() => run(PROMPT_SUGGEST, null, '')}>{busy ? 'Drafting…' : 'Generate suggestion from feedback'}</button>
        </div>
      ) : (
        <div className="pending">
          <h3 className="panel-title">Proposed change · based on {pending.based_on} flag{pending.based_on === 1 ? '' : 's'}</h3>
          {pending.reasoning && <p className="fc-sentiment">{pending.reasoning}</p>}
          {pending.changes && pending.changes.length > 0 && (
            <ul className="change-list">{pending.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
          )}
          <DiffView diff={pending.diff} />
          <div className="fb-actions">
            <button type="button" className="btn-primary" disabled={busy} onClick={() => run(PROMPT_APPROVE, null, 'Approved — the new version is live.')}>{busy ? 'Working…' : 'Approve & deploy'}</button>
            <button type="button" className="btn-link danger" disabled={busy} onClick={() => run(PROMPT_DISCARD, null, 'Suggestion discarded.')}>Discard</button>
          </div>
        </div>
      )}

      {state.history && state.history.length > 0 && (
        <div className="history">
          <h3 className="panel-title">Version history</h3>
          <ul className="channel-list">
            {state.history.map((h) => (
              <li key={h.version} className="channel-row">
                <div className="channel-main">
                  <span className="channel-type">v{h.version}</span>
                  <span className="channel-value">{h.reasoning || h.note || '—'}</span>
                  <button type="button" className="btn-link" disabled={busy || h.version === state.current_version} onClick={() => run(PROMPT_ROLLBACK, { version: h.version }, `Rolled back to v${h.version}.`)}>{h.version === state.current_version ? 'Active' : 'Roll back'}</button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function DiffView({ diff }) {
  if (!diff) return <p className="chat-empty">No line-level differences.</p>
  return (
    <pre className="diff">
      {diff.split('\n').map((ln, i) => {
        let cls = 'diff-ctx'
        if (ln.startsWith('+') && !ln.startsWith('+++')) cls = 'diff-add'
        else if (ln.startsWith('-') && !ln.startsWith('---')) cls = 'diff-del'
        else if (ln.startsWith('@@')) cls = 'diff-hunk'
        return <div key={i} className={cls}>{ln || ' '}</div>
      })}
    </pre>
  )
}

function QueryPanel() {
  const [prompt, setPrompt] = useState('')
  const [ticker, setTicker] = useState('')
  const [source, setSource] = useState('')
  const [closesOnly, setClosesOnly] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  async function submit(e) {
    e.preventDefault()
    if (!prompt.trim() && !ticker.trim() && !source.trim()) return setError('Enter a question or a filter.')
    setError(''); setLoading(true)
    try {
      const data = await gql(SMART_QUERY, { prompt: prompt.trim(), ticker: ticker.trim(), source: source.trim(), closesOnly })
      setResult(data.smartQuery || null)
    } catch (err) { setResult(null); setError(err.message) } finally { setLoading(false) }
  }
  return (
    <section className="panel query-panel">
      <h2 className="panel-title">Ask about a ticker or source</h2>
      <form onSubmit={submit} className="chat-form">
        <div className="query-filters">
          <input className="qf" type="text" placeholder="Ticker" value={ticker} onChange={(e) => setTicker(e.target.value)} />
          <input className="qf" type="text" placeholder="Source" value={source} onChange={(e) => setSource(e.target.value)} />
          <label className="qf-toggle"><input type="checkbox" checked={closesOnly} onChange={(e) => setClosesOnly(e.target.checked)} /> Closes only</label>
        </div>
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} placeholder={'e.g. "what did InvestorPlace say about NVDA?" or "stop-losses this week"'} />
        {error && <div className="submit-error">{error}</div>}
        <button type="submit" className="btn-primary" disabled={loading}>{loading ? 'Querying…' : 'Ask'}</button>
      </form>
      {result && (
        <div className="chat-result">
          <p className="chat-summary">{result.summary || 'Query completed.'}</p>
          {result.parsed && (result.parsed.ticker || result.parsed.source || result.parsed.action || result.parsed.closes_only || result.parsed.range) && (
            <div className="parsed-chips">
              {result.parsed.ticker && <span className="pchip">{result.parsed.ticker}</span>}
              {result.parsed.action && <span className="pchip">{result.parsed.action}</span>}
              {result.parsed.source && <span className="pchip">{result.parsed.source}</span>}
              {result.parsed.closes_only && <span className="pchip">closes only</span>}
              {result.parsed.range && <span className="pchip">{result.parsed.range}</span>}
            </div>
          )}
          <QueryRows rows={result.rows || []} intent={result.intent} />
        </div>
      )}
    </section>
  )
}

function QueryRows({ rows, intent }) {
  if (!rows || rows.length === 0) return <p className="chat-empty">No matching rows found.</p>
  const isClose = intent === 'closeEvents'
  return (
    <div className="chat-table-wrap">
      <table className="chat-table">
        <thead>
          <tr>
            <th>Ticker</th><th>Source</th>
            {isClose
              ? <><th>Close</th><th>Close Date</th><th>First Rec</th><th>Confidence</th><th>Sentiment</th></>
              : <><th>Action</th><th>Date</th><th>Confidence</th><th>Sentiment</th><th>Target</th><th>Stop</th></>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={`${row.ticker || 'row'}-${idx}`}>
              <td>{row.ticker || String(row.PK || '').replace('TICKER#', '') || '-'}</td>
              <td>{row.source || '-'}</td>
              {isClose
                ? <><td>{row.close_action || row.action || '-'}</td><td>{row.close_date || '-'}</td><td>{row.first_rec_date || '-'}</td><td>{row.confidence || '-'}</td><td>{row.sentiment || '-'}</td></>
                : <><td>{row.action || '-'}</td><td>{row.email_date || '-'}</td><td>{row.confidence || '-'}</td><td>{row.sentiment || '-'}</td><td>{row.price_target || '-'}</td><td>{row.stop_loss_price || '-'}</td></>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const E164 = /^\+[1-9]\d{7,14}$/

function Channels() {
  const [channels, setChannels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [type, setType] = useState('PUSHOVER')
  const [value, setValue] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [codes, setCodes] = useState({})

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await apiFetch('/channels', { method: 'GET' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Failed to load channels')
      setChannels(data.channels || [])
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  async function add(e) {
    e.preventDefault(); setNotice(''); setError('')
    const v = value.trim()
    if (type === 'SMS' && !E164.test(v)) return setError('Phone must be E.164, e.g. +12125551234')
    if (type === 'PUSHOVER' && v.length < 5) return setError('Enter a valid Pushover user key.')
    setBusy(true)
    try {
      const res = await apiFetch('/channels', { method: 'POST', body: JSON.stringify({ action: 'add', type, value: v }) })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Could not add channel')
      setNotice(data.message || 'Channel added.'); setValue(''); await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function verify(ch) {
    const code = (codes[ch.value] || '').trim()
    if (!code) return setError('Enter the verification code.')
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await apiFetch('/channels', { method: 'POST', body: JSON.stringify({ action: 'verify', type: ch.type, value: ch.value, code }) })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Verification failed')
      setNotice(data.message || 'Channel verified.'); await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function remove(ch) {
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await apiFetch('/channels', { method: 'DELETE', body: JSON.stringify({ type: ch.type, value: ch.value }) })
      if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(data.error || 'Could not remove channel') }
      await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="channels-panel">
      <p className="intro">Where should alerts be delivered? Add one or more phones and Pushover keys.</p>
      {loading ? <p className="intro">Loading channels…</p>
        : channels.length === 0 ? <p className="chat-empty">No channels yet — add one below.</p>
          : (
            <ul className="channel-list">
              {channels.map((ch) => (
                <li key={`${ch.type}#${ch.value}`} className="channel-row">
                  <div className="channel-main">
                    <span className="channel-type">{ch.type === 'SMS' ? 'SMS' : 'Pushover'}</span>
                    <span className="channel-value">{ch.value}</span>
                    <span className={`badge ${ch.status === 'ACTIVE' ? 'badge-active' : 'badge-pending'}`}>{ch.status === 'ACTIVE' ? 'Active' : 'Pending'}</span>
                  </div>
                  {ch.status !== 'ACTIVE' && (
                    <div className="channel-verify">
                      <input type="text" inputMode="numeric" placeholder="6-digit code" value={codes[ch.value] || ''} onChange={(e) => setCodes({ ...codes, [ch.value]: e.target.value })} />
                      <button type="button" className="btn-small" disabled={busy} onClick={() => verify(ch)}>Verify</button>
                    </div>
                  )}
                  <button type="button" className="btn-link danger" disabled={busy} onClick={() => remove(ch)}>Remove</button>
                </li>
              ))}
            </ul>
          )}
      <div className="divider" />
      <form onSubmit={add} className="form add-channel">
        <div className="field">
          <label htmlFor="ch-type">Channel type</label>
          <select id="ch-type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="PUSHOVER">Pushover</option>
            <option value="SMS">SMS</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="ch-value">{type === 'SMS' ? 'Phone (E.164)' : 'Pushover user key'}</label>
          <input id="ch-value" type="text" value={value} placeholder={type === 'SMS' ? '+12125551234' : 'uXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'} onChange={(e) => setValue(e.target.value)} />
          {type === 'PUSHOVER' && <span className="hint">Found in your <a href="https://pushover.net/settings" target="_blank" rel="noopener noreferrer">Pushover settings</a>.</span>}
          {type === 'SMS' && <span className="hint">SMS verification requires an SNS origination number; until one is set it stays pending.</span>}
        </div>
        {error && <div className="submit-error">{error}</div>}
        {notice && <div className="notice">{notice}</div>}
        <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Working…' : 'Add channel'}</button>
      </form>
    </div>
  )
}

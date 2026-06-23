import { useEffect, useState, useCallback } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || ''
const COGNITO_DOMAIN = import.meta.env.VITE_COGNITO_DOMAIN || ''
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID || ''
const REDIRECT_URI = import.meta.env.VITE_REDIRECT_URI || window.location.origin

const TK = { id: 'ia_id_token', access: 'ia_access_token', refresh: 'ia_refresh_token', pkce: 'ia_pkce_verifier' }

// ── token storage ────────────────────────────────────────────────────────────
const store = {
  get: (k) => sessionStorage.getItem(k),
  set: (k, v) => sessionStorage.setItem(k, v),
  clearTokens: () => [TK.id, TK.access, TK.refresh].forEach((k) => sessionStorage.removeItem(k)),
}

// ── small helpers ──────────────────────────────────────────────────────────────
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
  const claims = decodeJwt(id)
  const g = claims['cognito:groups']
  return Array.isArray(g) ? g : g ? [g] : []
}

// ── OAuth (Cognito Hosted UI, authorization-code + PKCE) ───────────────────────
async function login() {
  const { verifier, challenge } = await makePkce()
  store.set(TK.pkce, verifier)
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    scope: 'openid email profile',
    identity_provider: 'Google',
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })
  window.location.assign(`${COGNITO_DOMAIN}/oauth2/authorize?${params.toString()}`)
}

function logout() {
  store.clearTokens()
  const params = new URLSearchParams({ client_id: CLIENT_ID, logout_uri: REDIRECT_URI })
  window.location.assign(`${COGNITO_DOMAIN}/logout?${params.toString()}`)
}

async function exchangeCodeForTokens(code) {
  const verifier = store.get(TK.pkce) || ''
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: CLIENT_ID,
    code,
    redirect_uri: REDIRECT_URI,
    code_verifier: verifier,
  })
  const res = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
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
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) return false
  const t = await res.json()
  if (t.id_token) store.set(TK.id, t.id_token)
  if (t.access_token) store.set(TK.access, t.access_token)
  return true
}

// authenticated fetch against the API; retries once after a token refresh on 401
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
  if (res.status === 401 && (await refreshTokens())) {
    res = await doFetch()
  }
  return res
}

// ── recommendations query (now behind auth) ───────────────────────────────────
const CHAT_QUERY = `
  query ChatQuery($prompt: String!) {
    chatQuery(prompt: $prompt) { summary intent rows }
  }
`

export default function App() {
  const [authState, setAuthState] = useState('loading') // loading | anon | authed
  const [profile, setProfile] = useState(null)
  const [active, setActive] = useState(false)

  // bootstrap: handle OAuth callback or restore an existing session
  useEffect(() => {
    (async () => {
      const params = new URLSearchParams(window.location.search)
      if (params.get('error')) {
        window.history.replaceState({}, '', REDIRECT_URI)
        setAuthState('anon')
        return
      }
      if (params.get('code')) {
        try {
          await exchangeCodeForTokens(params.get('code'))
        } catch {
          /* fall through to anon below */
        }
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
    // pull a fresh token so the new "active" group claim is present
    await refreshTokens()
    setActive(groupsFromIdToken().includes('active'))
  }, [])

  return (
    <div className="container container-chat">
      <div className="card card-chat">
        <img src="/Inbox-Ag.png" alt="Inbox Aggregator" className="logo" />
        <h1>Inbox Aggregator</h1>
        <p className="tagline">Stock alert notifications</p>

        {authState === 'loading' && <p className="intro">Loading…</p>}
        {authState === 'anon' && <Landing />}
        {authState === 'authed' && !active && (
          <Redeem profile={profile} onRedeemed={onRedeemed} onSignOut={logout} />
        )}
        {authState === 'authed' && active && <Dashboard profile={profile} onSignOut={logout} />}
      </div>
    </div>
  )
}

// ── views ───────────────────────────────────────────────────────────────────
function Landing() {
  return (
    <div className="auth-landing">
      <p className="intro">Sign in with the Google account you were invited with.</p>
      <button type="button" className="btn-primary" onClick={login}>Sign in with Google</button>
    </div>
  )
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
      if (!res.ok) {
        setError(data.error || 'Could not redeem. Check the password and try again.')
        return
      }
      await onRedeemed()
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="form">
      <p className="intro">
        Signed in as <strong>{profile?.email || 'your account'}</strong>. Enter the invitation
        password to activate your account.
      </p>
      <div className="field">
        <label htmlFor="invpw">Invitation Password</label>
        <input id="invpw" type="password" value={password} autoFocus
          onChange={(e) => setPassword(e.target.value)} />
        {error && <span className="error">{error}</span>}
      </div>
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? 'Activating…' : 'Activate account'}
      </button>
      <button type="button" className="btn-link" onClick={onSignOut}>Sign out</button>
    </form>
  )
}

function Dashboard({ profile, onSignOut }) {
  const [tab, setTab] = useState('channels')
  return (
    <>
      <div className="view-toggle" role="tablist">
        <button type="button" className={`toggle-btn ${tab === 'channels' ? 'active' : ''}`}
          onClick={() => setTab('channels')}>Notifications</button>
        <button type="button" className={`toggle-btn ${tab === 'query' ? 'active' : ''}`}
          onClick={() => setTab('query')}>Query</button>
      </div>
      <div className="account-bar">
        <span className="account-email">{profile?.email}</span>
        <button type="button" className="btn-link" onClick={onSignOut}>Sign out</button>
      </div>
      {tab === 'channels' ? <Channels /> : <QueryPanel />}
    </>
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
  const [codes, setCodes] = useState({}) // sk -> code input

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await apiFetch('/channels', { method: 'GET' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Failed to load channels')
      setChannels(data.channels || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function add(e) {
    e.preventDefault()
    setNotice(''); setError('')
    const v = value.trim()
    if (type === 'SMS' && !E164.test(v)) return setError('Phone must be E.164, e.g. +12125551234')
    if (type === 'PUSHOVER' && v.length < 5) return setError('Enter a valid Pushover user key.')
    setBusy(true)
    try {
      const res = await apiFetch('/channels', {
        method: 'POST',
        body: JSON.stringify({ action: 'add', type, value: v }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Could not add channel')
      setNotice(data.message || 'Channel added.')
      setValue('')
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function verify(ch) {
    const code = (codes[ch.value] || '').trim()
    if (!code) return setError('Enter the verification code.')
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await apiFetch('/channels', {
        method: 'POST',
        body: JSON.stringify({ action: 'verify', type: ch.type, value: ch.value, code }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Verification failed')
      setNotice(data.message || 'Channel verified.')
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(ch) {
    setBusy(true); setError(''); setNotice('')
    try {
      const res = await apiFetch('/channels', {
        method: 'DELETE',
        body: JSON.stringify({ type: ch.type, value: ch.value }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Could not remove channel')
      }
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="channels-panel">
      <p className="intro">Where should alerts be delivered? Add one or more phones and Pushover keys.</p>

      {loading ? (
        <p className="intro">Loading channels…</p>
      ) : channels.length === 0 ? (
        <p className="chat-empty">No channels yet — add one below.</p>
      ) : (
        <ul className="channel-list">
          {channels.map((ch) => (
            <li key={`${ch.type}#${ch.value}`} className="channel-row">
              <div className="channel-main">
                <span className="channel-type">{ch.type === 'SMS' ? 'SMS' : 'Pushover'}</span>
                <span className="channel-value">{ch.value}</span>
                <span className={`badge ${ch.status === 'ACTIVE' ? 'badge-active' : 'badge-pending'}`}>
                  {ch.status === 'ACTIVE' ? 'Active' : 'Pending'}
                </span>
              </div>
              {ch.status !== 'ACTIVE' && (
                <div className="channel-verify">
                  <input
                    type="text" inputMode="numeric" placeholder="6-digit code"
                    value={codes[ch.value] || ''}
                    onChange={(e) => setCodes({ ...codes, [ch.value]: e.target.value })}
                  />
                  <button type="button" className="btn-small" disabled={busy} onClick={() => verify(ch)}>
                    Verify
                  </button>
                </div>
              )}
              <button type="button" className="btn-link danger" disabled={busy} onClick={() => remove(ch)}>
                Remove
              </button>
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
          <input id="ch-value" type="text" value={value}
            placeholder={type === 'SMS' ? '+12125551234' : 'uXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'}
            onChange={(e) => setValue(e.target.value)} />
          {type === 'PUSHOVER' && (
            <span className="hint">
              Found in your{' '}
              <a href="https://pushover.net/settings" target="_blank" rel="noopener noreferrer">Pushover settings</a>.
            </span>
          )}
          {type === 'SMS' && (
            <span className="hint">SMS verification requires an SNS origination number; until one is set it stays pending.</span>
          )}
        </div>
        {error && <div className="submit-error">{error}</div>}
        {notice && <div className="notice">{notice}</div>}
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? 'Working…' : 'Add channel'}
        </button>
      </form>
    </div>
  )
}

function QueryPanel() {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  async function submit(e) {
    e.preventDefault()
    if (!prompt.trim()) return setError('Enter a question.')
    setError(''); setLoading(true)
    try {
      const res = await apiFetch('/graphql', {
        method: 'POST',
        body: JSON.stringify({ query: CHAT_QUERY, variables: { prompt: prompt.trim() } }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.errors?.length) {
        setResult(null)
        setError(data.errors?.[0]?.message || 'Query failed.')
        return
      }
      setResult(data.data?.chatQuery || null)
    } catch {
      setResult(null)
      setError('Network error while querying.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="chat-panel">
      <p className="intro">Ask things like: "recommendations for TSLA" or "when did Brownstone close MSTR?"</p>
      <form onSubmit={submit} className="chat-form">
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3}
          placeholder="Ask about recommendations or close events..." />
        {error && <div className="submit-error">{error}</div>}
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Querying…' : 'Ask'}
        </button>
      </form>
      {result && (
        <div className="chat-result">
          <h3>Result</h3>
          <p className="chat-summary">{result.summary || 'Query completed.'}</p>
          <QueryRows rows={result.rows || []} intent={result.intent} />
        </div>
      )}
    </div>
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

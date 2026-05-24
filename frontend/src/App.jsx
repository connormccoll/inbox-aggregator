import { useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || ''

export default function App() {
  const [step, setStep] = useState('password') // 'password' | 'form' | 'success'
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [form, setForm] = useState({
    name: '',
    phone: '',
    pushoverUserKey: '',
    email: '',
  })
  const [smsOptIn, setSmsOptIn] = useState(false)
  const [termsAccepted, setTermsAccepted] = useState(false)
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  function handlePasswordSubmit(e) {
    e.preventDefault()
    if (!password.trim()) {
      setPasswordError('Please enter the invitation password.')
      return
    }
    setPasswordError('')
    setStep('form')
  }

  function validate() {
    const errs = {}
    if (!form.name.trim()) errs.name = 'Name is required.'
    if (!form.phone.trim()) errs.phone = 'Phone number is required.'
    else if (!/^\+[1-9]\d{7,14}$/.test(form.phone.trim()))
      errs.phone = 'Use E.164 format, e.g. +12125551234'
    if (!smsOptIn) errs.smsOptIn = 'SMS opt-in consent is required.'
    if (!termsAccepted) errs.terms = 'You must agree to the terms.'
    return errs
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length) {
      setErrors(errs)
      return
    }
    setErrors({})
    setSubmitting(true)
    setSubmitError('')
    try {
      const res = await fetch(`${API_URL}/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, password }),
      })
      const data = await res.json()
      if (!res.ok) {
        if (res.status === 403) {
          setStep('password')
          setPasswordError('Incorrect invitation password.')
        } else {
          setSubmitError(data.error || 'Something went wrong. Please try again.')
        }
      } else {
        setStep('success')
      }
    } catch {
      setSubmitError('Network error. Please check your connection and try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="container">
      <div className="card">
        <img src="/Inbox-Ag.png" alt="Inbox Aggregator" className="logo" />
        <h1>Inbox Aggregator</h1>
        <p className="tagline">Stock alert notifications</p>

        {step === 'password' && (
          <form onSubmit={handlePasswordSubmit} className="form">
            <p className="intro">Enter your invitation password to continue.</p>
            <div className="field">
              <label htmlFor="password">Invitation Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoFocus
              />
              {passwordError && <span className="error">{passwordError}</span>}
            </div>
            <button type="submit" className="btn-primary">Continue</button>
          </form>
        )}

        {step === 'form' && (
          <form onSubmit={handleSubmit} className="form">
            <p className="intro">Fill out the form below to receive stock alert notifications.</p>

            <div className="field">
              <label htmlFor="name">Full Name <span className="required">*</span></label>
              <input
                id="name"
                type="text"
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
              />
              {errors.name && <span className="error">{errors.name}</span>}
            </div>

            <div className="field">
              <label htmlFor="phone">Phone Number <span className="required">*</span></label>
              <input
                id="phone"
                type="tel"
                placeholder="+12125551234"
                value={form.phone}
                onChange={e => setForm({ ...form, phone: e.target.value })}
              />
              <span className="hint">Include country code in E.164 format (e.g. +12125551234)</span>
              {errors.phone && <span className="error">{errors.phone}</span>}
            </div>

            <div className="field">
              <label htmlFor="pushoverUserKey">Pushover User Key</label>
              <input
                id="pushoverUserKey"
                type="text"
                placeholder="uXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
                value={form.pushoverUserKey}
                onChange={e => setForm({ ...form, pushoverUserKey: e.target.value })}
              />
              <span className="hint">
                Found in{' '}
                <a href="https://pushover.net/settings" target="_blank" rel="noopener noreferrer">
                  Pushover Settings
                </a>{' '}
                — required for push notifications.
              </span>
            </div>

            <div className="field">
              <label htmlFor="email">Email Address</label>
              <input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={form.email}
                onChange={e => setForm({ ...form, email: e.target.value })}
              />
              <span className="hint">Optional. Reserved for future email digest notifications.</span>
            </div>

            <div className="divider" />

            <div className="checkbox-field">
              <input
                id="smsOptIn"
                type="checkbox"
                checked={smsOptIn}
                onChange={e => setSmsOptIn(e.target.checked)}
              />
              <label htmlFor="smsOptIn">
                I consent to receive recurring automated SMS text message alerts from Inbox
                Aggregator regarding investment recommendations. Message frequency varies.
                Message and data rates may apply. Reply <strong>STOP</strong> to unsubscribe
                at any time. Reply <strong>HELP</strong> for help.
              </label>
            </div>
            {errors.smsOptIn && <span className="error checkbox-error">{errors.smsOptIn}</span>}

            <div className="checkbox-field">
              <input
                id="terms"
                type="checkbox"
                checked={termsAccepted}
                onChange={e => setTermsAccepted(e.target.checked)}
              />
              <label htmlFor="terms">
                I have read and agree to the{' '}
                <a
                  href="#terms-text"
                  onClick={e => {
                    e.preventDefault()
                    document.getElementById('terms-text').scrollIntoView({ behavior: 'smooth' })
                  }}
                >
                  Terms of Use
                </a>{' '}
                below. I understand that alerts are for informational purposes only and do not
                constitute financial advice.
              </label>
            </div>
            {errors.terms && <span className="error checkbox-error">{errors.terms}</span>}

            {submitError && <div className="submit-error">{submitError}</div>}

            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? 'Subscribing…' : 'Subscribe'}
            </button>

            <section id="terms-text" className="terms-section">
              <h3>Terms of Use</h3>
              <p>
                Inbox Aggregator is a private, invite-only notification service that delivers
                automated investment alert summaries via SMS and push notification. By subscribing
                you acknowledge:
              </p>
              <ul>
                <li>
                  Alerts are for <strong>informational purposes only</strong> and do not constitute
                  financial, investment, or legal advice.
                </li>
                <li>
                  You are solely responsible for your investment decisions. Past performance is not
                  indicative of future results.
                </li>
                <li>
                  Your personal information (name, phone number, email, Pushover key) is collected
                  solely to deliver notifications and will not be sold or shared with third parties.
                </li>
                <li>
                  You may unsubscribe at any time by replying <strong>STOP</strong> to any SMS
                  message or by contacting the service administrator.
                </li>
                <li>
                  This service is intended for personal use by invited participants only.
                </li>
                <li>
                  Message and data rates from your mobile carrier may apply to SMS messages received.
                </li>
              </ul>
              <p>
                <strong>Privacy:</strong> We collect and store the minimum personal data necessary
                to deliver the service. Data is stored securely in AWS and is not accessible to
                unauthorized parties.
              </p>
            </section>
          </form>
        )}

        {step === 'success' && (
          <div className="success">
            <div className="success-icon">✓</div>
            <h2>You&apos;re subscribed!</h2>
            <p>
              You&apos;ll receive stock alert notifications via SMS
              {form.pushoverUserKey ? ' and Pushover' : ''}.
            </p>
            <p className="small">
              To unsubscribe, reply <strong>STOP</strong> to any SMS message.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

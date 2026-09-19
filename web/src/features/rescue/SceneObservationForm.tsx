import { useState } from 'react'
import { useRescueStore } from '../../store/rescueStore'
import type { ObservationInput } from '../../types/api'

type FormState = {
  address: string
  landmark: string
  whatHappened: string
  responsive: string
  breathing: string
  hazardsPresent: string
  hazardsDescription: string
}

const initialState: FormState = {
  address: '', landmark: '', whatHappened: '', responsive: '', breathing: '', hazardsPresent: '', hazardsDescription: '',
}

export function SceneObservationForm() {
  const saveSceneObservations = useRescueStore((state) => state.saveSceneObservations)
  const [form, setForm] = useState(initialState)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const rows: Array<[string, string | boolean]> = []
    if (form.address.trim()) rows.push(['location.address', form.address.trim()])
    if (form.landmark.trim()) rows.push(['location.landmark', form.landmark.trim()])
    if (form.whatHappened.trim()) rows.push(['circumstances.whatHappened', form.whatHappened.trim()])
    if (form.responsive) rows.push(['patient.responsive', form.responsive === 'true' ? true : form.responsive === 'false' ? false : 'unknown'])
    if (form.breathing) rows.push(['patient.breathing', form.breathing === 'true' ? true : form.breathing === 'false' ? false : 'unknown'])
    if (form.hazardsPresent) rows.push(['hazards.present', form.hazardsPresent === 'true' ? true : form.hazardsPresent === 'false' ? false : 'unknown'])
    if (form.hazardsDescription.trim()) rows.push(['hazards.description', form.hazardsDescription.trim()])
    if (!rows.length) { setMessage('請至少填寫一項現場資料。'); return }

    const observedAt = new Date().toISOString()
    const observations: ObservationInput[] = rows.map(([key, value]) => ({
      observationId: crypto.randomUUID(), key, value, source: 'manual_report', observedAt,
      confirmation: 'user_confirmed', evidenceEventIds: [],
    }))
    setSaving(true)
    try {
      await saveSceneObservations(observations)
      setForm(initialState)
      setMessage('現場資料已確認並同步。')
    } catch {
      setMessage('同步失敗，請稍後再試。')
    } finally {
      setSaving(false)
    }
  }

  const update = (key: keyof FormState) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((current) => ({ ...current, [key]: event.target.value }))

  return (
    <form className="scene-form" onSubmit={submit}>
      <label>地址<input value={form.address} onChange={update('address')} /></label>
      <label>地標<input value={form.landmark} onChange={update('landmark')} /></label>
      <label className="form-wide">發生經過<input value={form.whatHappened} onChange={update('whatHappened')} /></label>
      <label>患者有反應<select value={form.responsive} onChange={update('responsive')}><option value="">未填</option><option value="true">是</option><option value="false">否</option><option value="unknown">不確定</option></select></label>
      <label>患者有呼吸<select value={form.breathing} onChange={update('breathing')}><option value="">未填</option><option value="true">是</option><option value="false">否</option><option value="unknown">不確定</option></select></label>
      <label>現場有危險<select value={form.hazardsPresent} onChange={update('hazardsPresent')}><option value="">未填</option><option value="true">是</option><option value="false">否</option><option value="unknown">不確定</option></select></label>
      <label>危險說明<input value={form.hazardsDescription} onChange={update('hazardsDescription')} /></label>
      <button className="primary-action form-wide" type="submit" disabled={saving}>{saving ? '同步中…' : '確認現場資料'}</button>
      {message && <p className="form-message form-wide" role="status">{message}</p>}
    </form>
  )
}

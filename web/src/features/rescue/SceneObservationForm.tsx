import { useState } from 'react'
import { LocateFixed } from 'lucide-react'
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

type Coordinates = { latitude: number; longitude: number; accuracy: number }

export function SceneObservationForm() {
  const saveSceneObservations = useRescueStore((state) => state.saveSceneObservations)
  const [form, setForm] = useState(initialState)
  const [coordinates, setCoordinates] = useState<Coordinates | null>(null)
  const [locating, setLocating] = useState(false)
  const [locationMessage, setLocationMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const locate = () => {
    if (!navigator.geolocation) {
      setLocationMessage('此瀏覽器不支援定位，請改用支援定位的手機或瀏覽器。')
      return
    }

    setLocating(true)
    setLocationMessage('正在取得目前位置…')
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setCoordinates({
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracy: coords.accuracy,
        })
        setLocationMessage(`已取得位置，誤差約 ${Math.round(coords.accuracy)} 公尺。請按「確認現場資料」完成同步。`)
        setLocating(false)
      },
      (error) => {
        const text = error.code === error.PERMISSION_DENIED
          ? '定位權限未開啟，請允許位置存取後重試。'
          : '目前無法取得位置，請確認裝置定位與網路後重試。'
        setLocationMessage(text)
        setLocating(false)
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 30_000 },
    )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const rows: Array<[string, ObservationInput['value']]> = []
    if (coordinates) rows.push(['location.coordinates', {
      latitude: coordinates.latitude,
      longitude: coordinates.longitude,
    }], ['location.accuracyMeters', Math.round(coordinates.accuracy)])
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
      setMessage(coordinates
        ? '現場資料與座標已同步，現在可以建立並指派 AED 取件任務。'
        : '現場資料已確認並同步；指派 AED 前仍需取得目前位置。')
    } catch {
      setMessage('同步失敗，請稍後再試。')
    } finally {
      setSaving(false)
    }
  }

  const update = (key: keyof FormState) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((current) => ({ ...current, [key]: event.target.value }))

  return (
    <form className="scene-form" onSubmit={submit}>
      <div className="location-capture form-wide">
        <div>
          <strong>現場位置</strong>
          <span>{coordinates
            ? `${coordinates.latitude.toFixed(6)}, ${coordinates.longitude.toFixed(6)}`
            : '尚未取得座標，無法搜尋附近 AED'}</span>
        </div>
        <button type="button" onClick={locate} disabled={locating}>
          <LocateFixed size={19} aria-hidden="true" />
          {locating ? '定位中…' : coordinates ? '重新定位' : '取得目前位置'}
        </button>
        {locationMessage && <p role="status">{locationMessage}</p>}
      </div>
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

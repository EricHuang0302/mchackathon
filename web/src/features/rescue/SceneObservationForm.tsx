import { useState } from 'react'
import { LocateFixed } from 'lucide-react'
import { useRescueStore } from '../../store/rescueStore'
import type { ObservationInput } from '../../types/api'
import { observationLabels, sectionLabels, type ObservationKey } from './snapshotFields'
import {
  parseFieldValue,
  SCENE_FORM_FIELDS,
  SECTION_ORDER,
  type FieldControl,
  type SceneFormField,
} from './sceneFormFields'

type FormState = Partial<Record<ObservationKey, string>>

type Coordinates = { latitude: number; longitude: number; accuracy: number }

const TRISTATE = [
  { value: 'true', label: '是' },
  { value: 'false', label: '否' },
  { value: 'unknown', label: '不確定' },
]

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: SceneFormField
  value: string
  onChange: (next: string) => void
}) {
  const control: FieldControl = field.control
  if (control.kind === 'tristate' || control.kind === 'choice') {
    const options = control.kind === 'tristate' ? TRISTATE : control.options
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">未填</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    )
  }
  if (control.kind === 'number') {
    return (
      <input
        type="number"
        inputMode="numeric"
        min={control.min}
        max={control.max}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }
  if (control.kind === 'datetime') {
    return <input type="datetime-local" value={value} onChange={(event) => onChange(event.target.value)} />
  }
  return <input value={value} onChange={(event) => onChange(event.target.value)} />
}

export function SceneObservationForm() {
  const saveSceneObservations = useRescueStore((state) => state.saveSceneObservations)
  const [form, setForm] = useState<FormState>({})
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
    const rows: Array<[ObservationKey, ObservationInput['value']]> = []
    if (coordinates) {
      rows.push(
        ['location.coordinates', { latitude: coordinates.latitude, longitude: coordinates.longitude }],
        ['location.accuracyMeters', Math.round(coordinates.accuracy)],
      )
    }
    for (const field of SCENE_FORM_FIELDS) {
      const parsed = parseFieldValue(field.control, form[field.key] ?? '')
      if (parsed !== undefined) rows.push([field.key, parsed])
    }
    if (!rows.length) { setMessage('請至少填寫一項現場資料。'); return }

    const observedAt = new Date().toISOString()
    const observations: ObservationInput[] = rows.map(([key, value]) => ({
      observationId: crypto.randomUUID(), key, value, source: 'manual_report', observedAt,
      confirmation: 'user_confirmed', evidenceEventIds: [],
    }))
    setSaving(true)
    try {
      await saveSceneObservations(observations)
      setForm({})
      setMessage(coordinates
        ? `已同步 ${rows.length} 項現場資料與座標，現在可以建立並指派 AED 取件任務。`
        : `已同步 ${rows.length} 項現場資料；指派 AED 前仍需取得目前位置。`)
    } catch {
      setMessage('同步失敗，請稍後再試。')
    } finally {
      setSaving(false)
    }
  }

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

      {SECTION_ORDER.map((section) => {
        const fields = SCENE_FORM_FIELDS.filter((field) => field.section === section)
        if (!fields.length) return null
        return (
          <fieldset key={section} className="form-wide form-section">
            <legend>{sectionLabels[section]}</legend>
            <div className="form-section-grid">
              {fields.map((field) => (
                <label
                  key={field.key}
                  className={field.control.kind === 'text' && field.control.wide ? 'form-wide' : undefined}
                >
                  {observationLabels[field.key]}
                  <FieldInput
                    field={field}
                    value={form[field.key] ?? ''}
                    onChange={(next) => setForm((current) => ({ ...current, [field.key]: next }))}
                  />
                </label>
              ))}
            </div>
          </fieldset>
        )
      })}

      <button className="primary-action form-wide" type="submit" disabled={saving}>{saving ? '同步中…' : '確認現場資料'}</button>
      {message && <p className="form-message form-wide" role="status">{message}</p>}
    </form>
  )
}

import type { SceneSnapshotResponse } from '../../types/api'
import { formatObservationValue, observationLabels, sectionLabels, type ObservationKey } from './snapshotFields'

export function CanonicalSnapshotCard({ snapshot }: { snapshot: SceneSnapshotResponse | null }) {
  if (!snapshot) return <p className="snapshot-empty">正在讀取現場快照…</p>

  return (
    <div className="canonical-snapshot">
      {Object.entries(snapshot.sections).map(([section, fields]) => (
        <section key={section} className="snapshot-section">
          <h3>{sectionLabels[section as keyof typeof sectionLabels]}</h3>
          {fields.map((field) => (
            <div key={field.key} className="snapshot-field">
              <div>
                <strong>{observationLabels[field.key as ObservationKey] ?? field.key}</strong>
                <span>{formatObservationValue(field.value)}</span>
              </div>
              <small className={field.freshness === 'stale' ? 'is-stale' : undefined}>
                {field.provenance.source} · {field.provenance.confirmation} · {field.provenance.observedAt ? new Date(field.provenance.observedAt).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' }) : '未觀察'} · {field.freshness}
              </small>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}

import type { SceneSnapshotResponse, SnapshotField, SnapshotSectionName } from '../../types/api'
import { formatObservationValue, observationLabels, sectionLabels, type ObservationKey } from './snapshotFields'

// A null value means the field was never observed. Those rows carry no
// information for the reader, so whole-section noise is dropped. An explicit
// 'unknown' is a reported observation and stays visible.
const observedFields = (fields: SnapshotField[]) => fields.filter((field) => field.value !== null)

export function CanonicalSnapshotCard({ snapshot }: { snapshot: SceneSnapshotResponse | null }) {
  if (!snapshot) return <p className="snapshot-empty">正在讀取現場快照…</p>

  const sections = (Object.entries(snapshot.sections) as Array<[SnapshotSectionName, SnapshotField[]]>)
    .map(([section, fields]) => [section, observedFields(fields)] as const)
    .filter(([, fields]) => fields.length > 0)

  if (sections.length === 0) return <p className="snapshot-empty">尚未確認任何現場資料。</p>

  return (
    <div className="canonical-snapshot">
      {sections.map(([section, fields]) => (
        <section key={section} className="snapshot-section">
          <h3>{sectionLabels[section]}</h3>
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

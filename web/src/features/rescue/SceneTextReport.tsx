import { useState } from 'react'
import { Send } from 'lucide-react'

import { useRescueStore } from '../../store/rescueStore'
import type { SceneReportEntry } from '../../types/rescue'

const MAX_LENGTH = 600

const EXAMPLES = [
  '有人倒地，沒有反應，我在成大資訊系館。',
  '患者沒有呼吸，我已經開始壓胸。',
]

const OBSERVATION_LABELS: Record<string, string> = {
  responsive: '有反應',
  breathing_normal: '呼吸正常',
  'location.address': '地點',
  'circumstances.whatHappened': '發生什麼事',
}

const describeValue = (value: boolean | string) =>
  value === true ? '是' : value === false ? '否' : value === 'unknown' ? '不確定' : value

const describeObservation = (item: { key: string; value: boolean | string }) =>
  `${OBSERVATION_LABELS[item.key] ?? item.key}：${describeValue(item.value)}`

function ReportEntry({ entry }: { entry: SceneReportEntry }) {
  const time = new Date(entry.sentAt).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  return (
    <li className={`scene-report-entry scene-report-${entry.status}`}>
      <p className="scene-report-said"><span>你說</span>{entry.text}</p>
      <p className="scene-report-time">{time}</p>
      {entry.status === 'pending' && <p className="scene-report-reply">正在送給 Gemini 解讀…</p>}
      {entry.status === 'failed' && <p className="scene-report-reply scene-report-error" role="alert">{entry.error ?? '這次沒有送出成功，可以再試一次。'}</p>}
      {entry.status === 'answered' && (
        entry.observations?.length || entry.steps?.length ? (
          <div className="scene-report-reply">
            {entry.observations?.length ? (
              <>
                <span>Gemini 擷取到（尚未確認）</span>
                <ul>{entry.observations.map((item) => <li key={item.key}>{describeObservation(item)}</li>)}</ul>
              </>
            ) : null}
            {entry.steps?.length ? (
              <>
                <span>建議的協調步驟</span>
                <ul>{entry.steps.map((step) => <li key={step}>{step}</li>)}</ul>
              </>
            ) : null}
          </div>
        ) : <p className="scene-report-reply">這段描述沒有可擷取的資訊，可以說得更具體一點。</p>
      )}
    </li>
  )
}

/**
 * Typed scene reporting. Speech is the least reliable link at a real scene, so
 * this reaches the same bounded extraction without a microphone. Everything it
 * produces is an unconfirmed proposal that the user still reviews above.
 */
export function SceneTextReport() {
  const submitSceneReport = useRescueStore((state) => state.submitSceneReport)
  const reports = useRescueStore((state) => state.sceneReports)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)

  const trimmed = text.trim()
  const send = async () => {
    if (!trimmed || sending) return
    setSending(true)
    setText('')
    try {
      await submitSceneReport(trimmed)
    } catch {
      // The entry itself carries the failure; the composer stays usable.
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="scene-report" aria-labelledby="scene-report-title">
      <div className="scene-report-heading">
        <strong id="scene-report-title">用打字描述現場</strong>
        <span>不需要麥克風，結果和語音走同一套規則</span>
      </div>

      <ol className="scene-report-log" aria-label="現場描述紀錄" aria-live="polite">
        {reports.length === 0
          ? <li className="scene-report-empty">還沒有送出任何描述。送出後，Gemini 擷取的結果會顯示在這裡，待確認的項目會出現在本頁上方的「語音理解待確認」卡片。</li>
          : reports.map((entry) => <ReportEntry key={entry.id} entry={entry} />)}
      </ol>

      <label className="scene-report-field">
        <span className="visually-hidden">現場描述</span>
        <textarea
          value={text}
          maxLength={MAX_LENGTH}
          rows={3}
          placeholder="例如：有人倒地，沒有反應，我在成大資訊系館。"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void send()
          }}
        />
      </label>

      {reports.length === 0 && (
        <div className="scene-report-examples">
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="scene-report-example" onClick={() => setText(example)}>
              {example}
            </button>
          ))}
        </div>
      )}

      <div className="scene-report-actions">
        <small>{trimmed.length}/{MAX_LENGTH}</small>
        <button type="button" className="primary-action" disabled={!trimmed || sending} onClick={() => void send()}>
          <Send size={19} aria-hidden="true" />{sending ? '送出中…' : '送出描述'}
        </button>
      </div>
    </section>
  )
}

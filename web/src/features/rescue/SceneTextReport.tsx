import { useEffect, useRef, useState } from 'react'
import { Loader2, Mic, Send, Square } from 'lucide-react'

import { ApiClientError, userMessageForApiError } from '../../lib/connection/apiClient'
import { MAX_CLIP_SECONDS, VoiceClipRecorder } from '../../lib/media/voiceClip'
import { useRescueStore } from '../../store/rescueStore'
import type { SceneReportEntry } from '../../types/rescue'

const MAX_LENGTH = 600

type VoiceState = 'idle' | 'recording' | 'transcribing'

const recorderErrorMessage = (error: unknown) => {
  if (error instanceof DOMException && error.name === 'NotAllowedError') {
    return '麥克風權限未開啟；仍可直接打字描述。'
  }
  if (error instanceof ApiClientError) return userMessageForApiError(error)
  return error instanceof Error && error.message ? error.message : '這次沒有辨識成功，可以再錄一次或直接打字。'
}

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
 * Scene reporting by voice or by typing. Speaking records a clip that is
 * transcribed into the box, so the rescuer reads the words back and corrects
 * anything misheard before sending. Everything the extraction returns is an
 * unconfirmed proposal the user still reviews above.
 */
export function SceneTextReport() {
  const submitSceneReport = useRescueStore((state) => state.submitSceneReport)
  const transcribeSceneClip = useRescueStore((state) => state.transcribeSceneClip)
  const reports = useRescueStore((state) => state.sceneReports)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [voiceState, setVoiceState] = useState<VoiceState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [voiceMessage, setVoiceMessage] = useState<string | null>(null)
  const recorderRef = useRef<VoiceClipRecorder | null>(null)

  useEffect(() => () => recorderRef.current?.cancel(), [])

  const finishRecording = async () => {
    const recorder = recorderRef.current
    if (!recorder?.recording) return
    const clip = recorder.stop()
    recorderRef.current = null
    if (!clip) {
      setVoiceState('idle')
      setVoiceMessage('沒有錄到聲音，請再試一次。')
      return
    }
    setVoiceState('transcribing')
    try {
      const result = await transcribeSceneClip({ audioBase64: clip.audioBase64, mimeType: clip.mimeType })
      const transcript = result.transcript.trim()
      if (!transcript) {
        setVoiceMessage('沒有辨識出內容，請再錄一次或直接打字。')
      } else {
        // The transcript lands in the box, not in a report: the user reads it,
        // corrects anything misheard, and decides whether to send it.
        setText((current) => current.trim() ? `${current.trim()} ${transcript}` : transcript)
        setVoiceMessage('已轉成文字，請確認內容後再送出。')
      }
    } catch (error) {
      setVoiceMessage(recorderErrorMessage(error))
    } finally {
      setVoiceState('idle')
    }
  }

  const startRecording = async () => {
    setVoiceMessage(null)
    setElapsed(0)
    const recorder = new VoiceClipRecorder({
      onProgress: (seconds) => setElapsed(seconds),
      onLimitReached: () => { void finishRecording() },
    })
    recorderRef.current = recorder
    try {
      await recorder.start()
      setVoiceState('recording')
    } catch (error) {
      recorderRef.current = null
      setVoiceState('idle')
      setVoiceMessage(recorderErrorMessage(error))
    }
  }

  const trimmed = text.trim()
  const busy = voiceState !== 'idle'
  const send = async () => {
    if (!trimmed || sending || busy) return
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
        <strong id="scene-report-title">描述現場</strong>
        <span>用說的會先轉成文字給你確認，確認後才送出</span>
      </div>

      <ol className="scene-report-log" aria-label="現場描述紀錄" aria-live="polite">
        {reports.length === 0
          ? <li className="scene-report-empty">還沒有送出任何描述。你可以直接打字，或按「用說的」錄一段話轉成文字。送出後，Gemini 擷取的結果會顯示在這裡，待確認的項目會出現在本頁上方的「現場資訊待確認」卡片。</li>
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

      {voiceMessage && <p className="scene-report-voice-message" role="status">{voiceMessage}</p>}

      <div className="scene-report-actions">
        <small>{trimmed.length}/{MAX_LENGTH}</small>
        {voiceState === 'recording' ? (
          <button type="button" className="danger-action scene-report-record" onClick={() => void finishRecording()}>
            <Square size={18} aria-hidden="true" fill="currentColor" />
            停止錄音 {Math.floor(elapsed)}/{MAX_CLIP_SECONDS}s
          </button>
        ) : (
          <button type="button" className="secondary-action scene-report-record" disabled={busy || sending} onClick={() => void startRecording()}>
            {voiceState === 'transcribing'
              ? <><Loader2 size={18} aria-hidden="true" className="voice-spinner" />辨識中…</>
              : <><Mic size={18} aria-hidden="true" />用說的</>}
          </button>
        )}
        <button type="button" className="primary-action" disabled={!trimmed || sending || busy} onClick={() => void send()}>
          <Send size={19} aria-hidden="true" />{sending ? '送出中…' : '送出描述'}
        </button>
      </div>
    </section>
  )
}

import { useEffect, useRef, useState } from 'react'
import { Camera, CheckCircle2, RefreshCw } from 'lucide-react'

import { CameraCapture } from '../../lib/media/camera'
import { ApiClientError, userMessageForApiError } from '../../lib/connection/apiClient'
import { useRescueStore } from '../../store/rescueStore'
import type {
  CameraObservationKey,
  CameraObservationProposal,
  SceneImageAnalysisResponse,
} from '../../types/api'

type ProposalValue = CameraObservationProposal['value']
type ReviewValues = Record<CameraObservationKey, ProposalValue>
type Phase = 'idle' | 'starting' | 'ready' | 'analyzing' | 'review' | 'saving' | 'done' | 'error'

const LABELS: Record<CameraObservationKey, string> = {
  'hazards.traffic': '車流風險',
  'hazards.fire': '火源或煙霧',
  'hazards.standingWater': '積水',
  'hazards.crowd': '人群阻礙',
  'patient.bleeding': '出血程度',
}

const RISK_OPTIONS = [
  { value: 'true', label: '有風險' },
  { value: 'false', label: '未見風險' },
  { value: 'unknown', label: '不確定／畫面外' },
] as const

const BLEEDING_OPTIONS = [
  { value: 'none', label: '沒有出血' },
  { value: 'minor', label: '輕微' },
  { value: 'severe', label: '嚴重' },
  { value: 'life_threatening', label: '危及生命' },
  { value: 'unknown', label: '不確定' },
] as const

const confidenceLabel = (confidence: CameraObservationProposal['confidence']) => ({
  high: '辨識信心高', medium: '辨識信心中', low: '辨識信心低', unknown: '辨識信心不明',
})[confidence]

const proposalValues = (analysis: SceneImageAnalysisResponse): ReviewValues => Object.fromEntries(
  analysis.proposals.map((proposal) => [proposal.key, proposal.value]),
) as ReviewValues

const selectValue = (value: ProposalValue) => typeof value === 'boolean' ? String(value) : value
const parseSelectedValue = (key: CameraObservationKey, value: string): ProposalValue =>
  key === 'patient.bleeding' ? value as ProposalValue : value === 'true' ? true : value === 'false' ? false : 'unknown'

const cameraErrorMessage = (error: unknown) => {
  if (error instanceof DOMException && error.name === 'NotAllowedError') {
    return '相機權限未開啟；仍可使用下方表單手動回報。'
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return '救援模式已變更，這張相片已丟棄，請重新拍攝。'
  }
  if (error instanceof ApiClientError) return userMessageForApiError(error)
  return error instanceof Error && error.message
    ? error.message
    : '目前無法分析相片；仍可使用下方表單手動回報。'
}

export function SceneCameraAnalysis() {
  const modeRevision = useRescueStore((state) => state.integration.modeRevision ?? 0)
  const analyzeSceneImage = useRescueStore((state) => state.analyzeSceneImage)
  const confirmCameraProposals = useRescueStore((state) => state.confirmCameraProposals)
  const cameraRef = useRef<CameraCapture | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const previewUrlRef = useRef<string | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [analysis, setAnalysis] = useState<SceneImageAnalysisResponse | null>(null)
  const [values, setValues] = useState<ReviewValues | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const releasePreview = () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    previewUrlRef.current = null
    setPreviewUrl(null)
  }

  useEffect(() => () => {
    cameraRef.current?.stop()
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
  }, [])

  const startCamera = async () => {
    cameraRef.current?.stop()
    releasePreview()
    setAnalysis(null)
    setValues(null)
    setMessage(null)
    setPhase('starting')
    const camera = new CameraCapture()
    cameraRef.current = camera
    try {
      await camera.start({ width: { ideal: 1280 }, height: { ideal: 960 } })
      setPhase('ready')
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
      if (!videoRef.current) throw new Error('相機預覽尚未準備完成。')
      await camera.attach(videoRef.current)
    } catch (error) {
      camera.stop()
      setMessage(cameraErrorMessage(error))
      setPhase('error')
    }
  }

  const capture = async () => {
    if (!cameraRef.current || !videoRef.current) return
    setMessage(null)
    try {
      const frame = await cameraRef.current.capture(videoRef.current, {
        modeRevision,
        currentModeRevision: () => useRescueStore.getState().integration.modeRevision ?? 0,
        maxDimension: 1_024,
        mimeType: 'image/jpeg',
        quality: 0.72,
      })
      cameraRef.current.stop()
      const url = URL.createObjectURL(frame.blob)
      previewUrlRef.current = url
      setPreviewUrl(url)
      setPhase('analyzing')
      const result = await analyzeSceneImage(frame)
      setAnalysis(result)
      setValues(proposalValues(result))
      setPhase('review')
    } catch (error) {
      cameraRef.current?.stop()
      setMessage(cameraErrorMessage(error))
      setPhase('error')
    }
  }

  const confirm = async () => {
    if (!analysis || !values) return
    setPhase('saving')
    setMessage(null)
    try {
      await confirmCameraProposals(analysis.proposals, values)
      releasePreview()
      setAnalysis(null)
      setValues(null)
      setMessage('已保存人工確認結果；原始相片未保留。')
      setPhase('done')
    } catch (error) {
      setMessage(cameraErrorMessage(error))
      setPhase('review')
    }
  }

  const cameraActive = phase === 'starting' || phase === 'ready'

  return (
    <section className="scene-camera" aria-labelledby="scene-camera-title">
      <div className="scene-camera-heading">
        <div>
          <strong id="scene-camera-title">相機輔助判讀</strong>
          <span>單張拍攝，不開啟即時影像串流</span>
        </div>
        {phase === 'done' && <CheckCircle2 size={22} aria-hidden="true" />}
      </div>

      <p className="scene-camera-note">AI 只提出車流、火源、積水、人群與出血程度建議；畫面外仍視為不確定，保存前必須由你確認。</p>

      <video ref={videoRef} className="scene-camera-preview" hidden={!cameraActive} aria-label="相機預覽" />
      {previewUrl && <img className="scene-camera-preview" src={previewUrl} alt="待確認的現場相片" />}

      {(phase === 'idle' || phase === 'done' || phase === 'error') && (
        <button type="button" className="secondary-action" onClick={() => void startCamera()}>
          <Camera size={20} aria-hidden="true" />{phase === 'idle' ? '拍攝現場相片' : '重新拍攝'}
        </button>
      )}
      {phase === 'starting' && <p className="scene-camera-status" role="status">正在開啟相機…</p>}
      {phase === 'ready' && <button type="button" className="primary-action" onClick={() => void capture()}><Camera size={20} aria-hidden="true" />拍下並分析</button>}
      {phase === 'analyzing' && <p className="scene-camera-status" role="status">正在分析單張相片…</p>}

      {analysis && values && (phase === 'review' || phase === 'saving') && (
        <div className="camera-review">
          <p className="camera-review-alert">以下是未確認建議。請逐項核對後再保存。</p>
          {analysis.proposals.map((proposal) => {
            const options = proposal.key === 'patient.bleeding' ? BLEEDING_OPTIONS : RISK_OPTIONS
            return (
              <label key={proposal.observationId}>
                <span><strong>{LABELS[proposal.key]}</strong><small>{confidenceLabel(proposal.confidence)}</small></span>
                <select
                  value={selectValue(values[proposal.key])}
                  disabled={phase === 'saving'}
                  onChange={(event) => setValues((current) => current && ({
                    ...current,
                    [proposal.key]: parseSelectedValue(proposal.key, event.target.value),
                  }))}
                >
                  {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
            )
          })}
          {analysis.warnings.map((warning) => <p className="scene-camera-warning" key={warning}>{warning}</p>)}
          <div className="camera-review-actions">
            <button type="button" className="secondary-action" disabled={phase === 'saving'} onClick={() => void startCamera()}><RefreshCw size={18} />重拍</button>
            <button type="button" className="primary-action" disabled={phase === 'saving'} onClick={() => void confirm()}>{phase === 'saving' ? '保存中…' : '確認並保存'}</button>
          </div>
        </div>
      )}
      {message && <p className="scene-camera-message" role="status">{message}</p>}
    </section>
  )
}

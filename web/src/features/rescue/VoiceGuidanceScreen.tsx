import { useEffect } from 'react'
import { Loader2, Mic, MicOff, Phone } from 'lucide-react'
import { CprVisualMetronome } from '../../components/CprVisualMetronome'
import { Timeline } from '../../components/Timeline'
import { EMERGENCY_DIAL_HREF } from '../../config/emergencyDial'
import { useRescueStore } from '../../store/rescueStore'
import { ObservationProposalCard } from './ObservationProposalCard'
import { SceneCameraAnalysis } from './SceneCameraAnalysis'
import { SceneTextReport } from './SceneTextReport'
import { AgentTaskPlanCard } from './AgentTaskPlanCard'

export function VoiceGuidanceScreen({ demoMode = false }: { demoMode?: boolean }) {
  const redial = useRescueStore((state) => state.redial)
  const dialAttempted = useRescueStore((state) => state.dialAttempted)
  const confirmCallConnected = useRescueStore((state) => state.confirmCallConnected)
  const reportCallFailed = useRescueStore((state) => state.reportCallFailed)
  const beginHandover = useRescueStore((state) => state.beginHandover)
  const proposal = useRescueStore((state) => state.observationProposal)
  const agentPlan = useRescueStore((state) => state.agentPlan)
  const agentToolResults = useRescueStore((state) => state.agentToolResults)
  const lastProposal = useRescueStore((state) => state.lastObservationProposal)
  const guidance = useRescueStore((state) => state.guidance)
  const guidanceError = useRescueStore((state) => state.guidanceError)
  const voiceStopped = useRescueStore((state) => state.voiceStopped)
  const voicePhase = useRescueStore((state) => state.voicePhase)
  const confirmObservation = useRescueStore((state) => state.confirmObservation)
  const evaluateGuidance = useRescueStore((state) => state.evaluateGuidance)
  const repeatGuidance = useRescueStore((state) => state.repeatGuidance)
  const stopGuidance = useRescueStore((state) => state.stopGuidance)
  const startGuidanceVoice = useRescueStore((state) => state.startGuidanceVoice)
  const correctObservation = useRescueStore((state) => state.correctObservation)
  const instruction = guidance?.decision.instruction
  const reviewWarning = guidance?.reviewStatus === 'unreviewed_demo'
    ? '未審查示範規則，不可取代 119 派遣員指示。'
    : guidance?.reviewStatus === 'in_review'
      ? '此規則正在審查中，不可取代 119 派遣員指示。'
      : guidance?.clinicalReviewRequired
        ? '此規則仍需臨床審查，不可取代 119 派遣員指示。'
        : null
  const metronomeActive = !voiceStopped && guidance?.decision.actions.some((action) => action.kind === 'metronome_start')

  useEffect(() => {
    if (!guidance && !guidanceError) void evaluateGuidance()
  }, [evaluateGuidance, guidance, guidanceError])

  return (
    <section className="screen" aria-labelledby="guidance-title">
      <div>
        <p className="eyebrow">目前急救指引</p>
        <h1 className="screen-title" id="guidance-title">{instruction?.text ?? (guidanceError ? '目前沒有可顯示的規則指引' : '正在取得規則模板…')}</h1>
        <p className="screen-subtitle">若現場狀況改變，請立即重新撥打 119，並依派遣員指示操作。</p>
      </div>

      {reviewWarning && <div className="review-warning" role="status">{reviewWarning}</div>}
      {guidanceError && <div className="stale-warning" role="alert">{guidanceError}</div>}
      {proposal && <ObservationProposalCard key={proposal.observationId} proposal={proposal} onConfirm={confirmObservation} />}
      <AgentTaskPlanCard plan={agentPlan} tools={agentToolResults} />

      {metronomeActive && <CprVisualMetronome />}

      <div className={`voice-state voice-state-${voicePhase}`} role="status">
        {voicePhase === 'on' && <><Mic size={19} aria-hidden="true" />正在收音，可以直接說話</>}
        {voicePhase === 'starting' && <><Loader2 size={19} aria-hidden="true" className="voice-spinner" />正在啟動語音，最多需要幾秒…</>}
        {voicePhase === 'off' && <><MicOff size={19} aria-hidden="true" />尚未收音。按「開始語音」後才會把聲音送出。</>}
      </div>

      <div className="guidance-controls" aria-label="語音指引控制">
        <button className="secondary-action" type="button" onClick={() => void repeatGuidance()}>重複</button>
        {voicePhase === 'off'
          ? <button className="primary-action" type="button" onClick={startGuidanceVoice}><Mic size={19} aria-hidden="true" />開始語音</button>
          : <button className="secondary-action" type="button" onClick={stopGuidance}><MicOff size={19} aria-hidden="true" />停止語音</button>}
        <button className="secondary-action" type="button" onClick={correctObservation} disabled={!lastProposal}>修正</button>
      </div>

      <div className="card">
        <h2 className="card-title">現場描述</h2>
        <SceneTextReport />
      </div>

      <div className="card">
        <h2 className="card-title">現場影像</h2>
        <SceneCameraAnalysis />
      </div>

      <div className="card">
        <h2 className="card-title">處置紀錄</h2>
        <Timeline limit={4} compact />
      </div>

      <div className="action-stack">
        {dialAttempted ? (
          <>
            <button className="primary-action" type="button" onClick={confirmCallConnected}>已接通派遣員</button>
            <button className="secondary-action" type="button" onClick={reportCallFailed}>無法接通，繼續語音指引</button>
          </>
        ) : demoMode ? (
          <button className="secondary-action" type="button" onClick={redial}><Phone size={21} />模擬重新撥打 119</button>
        ) : (
          <a className="secondary-action" href={EMERGENCY_DIAL_HREF} onClick={redial}><Phone size={21} />重新撥打 119</a>
        )}
        <button className="primary-action" type="button" onClick={beginHandover}>救護人員已到場</button>
      </div>
    </section>
  )
}

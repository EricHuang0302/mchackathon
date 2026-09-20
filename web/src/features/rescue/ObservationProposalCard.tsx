import { useState } from 'react'

import type { LiveObservationProposal } from '../../types/api'

const LABELS: Record<LiveObservationProposal['key'], string> = {
  responsive: '患者有反應嗎？',
  breathing_normal: '患者有正常呼吸嗎？',
  'location.address': '事發地點正確嗎？',
  'circumstances.whatHappened': '事發經過正確嗎？',
}

const valueLabel = (value: LiveObservationProposal['value']) => value === true ? '是' : value === false ? '否' : '不確定'

export function ObservationProposalCard({
  proposal,
  onConfirm,
}: {
  proposal: LiveObservationProposal
  onConfirm: (value: boolean | string) => Promise<void>
}) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isText = proposal.key === 'location.address' || proposal.key === 'circumstances.whatHappened'
  const [text, setText] = useState(typeof proposal.value === 'string' && proposal.value !== 'unknown' ? proposal.value : '')

  const confirm = async (value: boolean | string) => {
    setSaving(true)
    setError(null)
    try {
      await onConfirm(value)
    } catch {
      setError('確認失敗，請再試一次。')
      setSaving(false)
    }
  }

  return <section className="card proposal-card" aria-labelledby="proposal-title">
    <p className="eyebrow">語音理解待確認</p>
    <h2 className="card-title" id="proposal-title">{LABELS[proposal.key]}</h2>
    {isText ? <>
      <label className="proposal-text"><span>Gemini 擷取內容</span><input value={text} maxLength={200} onChange={(event) => setText(event.target.value)} /></label>
      <div className="proposal-actions proposal-actions--two">
        <button type="button" disabled={saving || !text.trim()} onClick={() => void confirm(text.trim())}>確認內容</button>
        <button type="button" disabled={saving} onClick={() => void confirm('unknown')}>不確定</button>
      </div>
    </> : <>
      <p>模型辨識：<strong>{valueLabel(proposal.value)}</strong>。請以你現場確認的狀況回答。</p>
      <div className="proposal-actions">
        <button type="button" disabled={saving} onClick={() => void confirm(true)}>是</button>
        <button type="button" disabled={saving} onClick={() => void confirm(false)}>否</button>
        <button type="button" disabled={saving} onClick={() => void confirm('unknown')}>不確定</button>
      </div>
    </>}
    {error && <p className="share-error" role="alert">{error}</p>}
  </section>
}

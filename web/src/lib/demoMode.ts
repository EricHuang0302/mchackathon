export const isDemoMode = () =>
  typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('demo') === '1'

export const DEMO_WARNING = '模擬事件・未經臨床審查'

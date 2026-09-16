import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type UiScale = 100 | 125 | 150

interface UiPreferencesValue {
  uiScale: UiScale
  highContrast: boolean
  setUiScale: (scale: UiScale) => void
  setHighContrast: (enabled: boolean) => void
}

const UiPreferencesContext = createContext<UiPreferencesValue | null>(null)

function readScale(): UiScale {
  const value = window.localStorage.getItem('sprite-studio-ui-scale')
  return value === '125' || value === '150' ? Number(value) as UiScale : 100
}

export function UiPreferencesProvider({ children }: { children: ReactNode }) {
  const [uiScale, setUiScale] = useState<UiScale>(readScale)
  const [highContrast, setHighContrast] = useState(() => window.localStorage.getItem('sprite-studio-high-contrast') === 'true')

  useEffect(() => {
    document.documentElement.dataset.uiScale = String(uiScale)
    document.documentElement.style.setProperty('--ui-scale', String(uiScale / 100))
    window.localStorage.setItem('sprite-studio-ui-scale', String(uiScale))
  }, [uiScale])

  useEffect(() => {
    document.documentElement.dataset.contrast = highContrast ? 'high' : 'normal'
    window.localStorage.setItem('sprite-studio-high-contrast', String(highContrast))
  }, [highContrast])

  const value = useMemo<UiPreferencesValue>(() => ({ uiScale, highContrast, setUiScale, setHighContrast }), [highContrast, uiScale])
  return <UiPreferencesContext.Provider value={value}>{children}</UiPreferencesContext.Provider>
}

export function useUiPreferences(): UiPreferencesValue {
  const value = useContext(UiPreferencesContext)
  if (!value) throw new Error('useUiPreferences must be used inside UiPreferencesProvider')
  return value
}

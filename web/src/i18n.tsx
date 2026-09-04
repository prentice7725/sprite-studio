import { createContext, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export type Locale = 'en' | 'ko'
type MessageKey = 'project' | 'static' | 'workspace' | 'jobs' | 'createAsset' | 'buildStatic' | 'backgroundJobs' | 'activeAsset' | 'selectAsset' | 'language'

const messages: Record<Locale, Record<MessageKey, string>> = {
  en: { project: 'Project', static: 'Static', workspace: 'Workspace', jobs: 'Jobs', createAsset: 'Create an asset', buildStatic: 'Build a static asset', backgroundJobs: 'Background jobs', activeAsset: 'Active asset', selectAsset: 'Select an asset', language: '한국어' },
  ko: { project: '프로젝트', static: '스태틱', workspace: '워크스페이스', jobs: '작업', createAsset: '에셋 만들기', buildStatic: '스태틱 에셋 만들기', backgroundJobs: '백그라운드 작업', activeAsset: '활성 에셋', selectAsset: '에셋 선택', language: 'English' },
}

interface I18nValue { locale: Locale; t: (key: MessageKey) => string; toggleLocale: () => void }
const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => window.localStorage.getItem('sprite-studio-locale') === 'ko' ? 'ko' : 'en')
  const value = useMemo<I18nValue>(() => ({ locale, t: (key) => messages[locale][key], toggleLocale: () => setLocale((current) => { const next = current === 'en' ? 'ko' : 'en'; window.localStorage.setItem('sprite-studio-locale', next); return next }) }), [locale])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside I18nProvider')
  return value
}

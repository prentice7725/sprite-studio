import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './ux-overrides.css'
import { I18nProvider } from './i18n'
import { UiPreferencesProvider } from './uiPreferences'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider><UiPreferencesProvider><App /></UiPreferencesProvider></I18nProvider>
  </StrictMode>,
)

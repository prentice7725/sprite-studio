import { useI18n } from '../../i18n'
import { useUiPreferences, type UiScale } from '../../uiPreferences'

const scaleOptions: UiScale[] = [100, 125, 150]

export default function DisplaySettings() {
  const { t } = useI18n()
  const { uiScale, highContrast, setUiScale, setHighContrast } = useUiPreferences()
  return <details className="display-settings">
    <summary className="tool-button text-button">{t('display')}</summary>
    <div className="display-menu" role="group" aria-label={t('display')}>
      <label htmlFor="ui-scale">{t('uiScale')}<select id="ui-scale" value={uiScale} onChange={(event) => setUiScale(Number(event.target.value) as UiScale)}>{scaleOptions.map((scale) => <option key={scale} value={scale}>{scale}%</option>)}</select></label>
      <label className="check-row" htmlFor="high-contrast"><input id="high-contrast" type="checkbox" checked={highContrast} onChange={(event) => setHighContrast(event.target.checked)} />{t('highContrast')}<span className="check-detail">{highContrast ? t('on') : t('off')}</span></label>
    </div>
  </details>
}

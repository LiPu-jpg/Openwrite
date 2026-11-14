/**
 * Once-per-version-update announcement & open-source support modal for OpenWrite.
 *
 * Displays once in the browser after each OpenWrite version upgrade (tracked in
 * `localStorage` under `openwrite.seenReleaseVersion`) and can also be opened on
 * demand from 「设置 → OpenWrite → 环境」.
 *
 * Features exclusively OpenWrite (`https://github.com/LiPu-jpg/Openwrite`) and
 * privacy-safe feedback links (never novel titles, manuscripts, settings, local
 * paths, or API keys).
 */

import { COMPANION_PLUGINS } from './companions.tsx'
import { en, zh, type StudioPanelKey } from './locales.ts'
import css from './ReleaseAnnouncement.module.css'

/** Canonical GitHub repository URL for OpenWrite. */
export const OPENWRITE_REPO_URL = 'https://github.com/LiPu-jpg/Openwrite'

/** localStorage key recording the last acknowledged OpenWrite release version. */
export const SEEN_RELEASE_VERSION_KEY = 'openwrite.seenReleaseVersion'

/** Attribute marking the mounted release announcement scrim in `document.body`. */
export const RELEASE_MODAL_MARKER = 'data-openwrite-release-modal'

export interface ReleaseAnnouncementOptions {
  t?: (key: StudioPanelKey) => string
  version?: string
  issueUrl?: string
  onClose?: () => void
  allowWebdriver?: boolean
}

/**
 * Resolve the current OpenWrite release version stamped at build time.
 */
export function resolveOpenWriteVersion(): string {
  if (typeof __OPENWRITE_VERSION__ === 'string' && __OPENWRITE_VERSION__.trim() !== '') {
    return __OPENWRITE_VERSION__.trim()
  }
  if (typeof __OPENWRITE_PRESET_ID__ === 'string' && __OPENWRITE_PRESET_ID__.startsWith('openwrite-')) {
    return __OPENWRITE_PRESET_ID__.slice('openwrite-'.length).replaceAll('-', '.')
  }
  return '0.2.39'
}

/**
 * Check whether the user has already seen and dismissed the announcement for `version`.
 */
export function hasSeenReleaseAnnouncement(version: string = resolveOpenWriteVersion()): boolean {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return false
    return window.localStorage.getItem(SEEN_RELEASE_VERSION_KEY) === version
  } catch {
    return false
  }
}

/**
 * Record that the user has seen the announcement for `version`.
 */
export function markReleaseAnnouncementSeen(version: string = resolveOpenWriteVersion()): void {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return
    window.localStorage.setItem(SEEN_RELEASE_VERSION_KEY, version)
  } catch {
    // Storage may be disabled in restricted/private contexts; dismissal still closes the modal.
  }
}

/**
 * Build a default privacy-safe GitHub issue URL containing only the OpenWrite version.
 */
export function buildDefaultReleaseIssueUrl(version: string = resolveOpenWriteVersion()): string {
  const title = '[Bug]: '
  const body = [
    '### 问题描述 / Issue Description',
    '',
    '（请在此简要描述您遇到的问题，无需提供小说正文或设定 / Describe the issue briefly without sharing novel content）',
    '',
    '### 脱敏环境诊断 / Sanitized Diagnostics',
    '',
    '```text',
    `OpenWrite Version: v${version}`,
    '```',
  ].join('\n')
  const params = new URLSearchParams({ title, body })
  return `${OPENWRITE_REPO_URL}/issues/new?${params.toString()}`
}

function defaultTranslator(): (key: StudioPanelKey) => string {
  const lang = typeof document !== 'undefined' ? (document.documentElement.lang || 'zh') : 'zh'
  const dict = lang.toLowerCase().startsWith('en') ? en : zh
  return (key: StudioPanelKey) => dict[key] ?? zh[key] ?? key
}

/**
 * Render and mount the OpenWrite release announcement modal onto `document.body`.
 * Closing or clicking any action marks `version` as seen in `localStorage`.
 */
export function showReleaseAnnouncementModal(options: ReleaseAnnouncementOptions = {}): HTMLElement | null {
  if (typeof document === 'undefined' || !document.body) return null
  const version = options.version ?? resolveOpenWriteVersion()
  const translate = (key: StudioPanelKey): string => {
    const candidate = options.t?.(key)
    if (candidate !== undefined && candidate !== '' && candidate !== key && !candidate.startsWith('studio-panel.')) {
      return candidate
    }
    return defaultTranslator()(key)
  }
  const issueUrl = options.issueUrl ?? buildDefaultReleaseIssueUrl(version)

  document.querySelector(`[${RELEASE_MODAL_MARKER}]`)?.remove()

  const scrim = document.createElement('div')
  scrim.className = css.scrim ?? 'openwrite-release-scrim'
  scrim.setAttribute(RELEASE_MODAL_MARKER, version)

  const modal = document.createElement('div')
  modal.className = css.modal ?? 'openwrite-release-modal'
  modal.setAttribute('role', 'alertdialog')
  modal.setAttribute('aria-modal', 'true')
  modal.setAttribute('aria-label', translate('settings.releaseModal.title'))

  const close = () => {
    markReleaseAnnouncementSeen(version)
    document.removeEventListener('keydown', onKeyDown)
    scrim.remove()
    options.onClose?.()
  }

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') close()
  }
  document.addEventListener('keydown', onKeyDown)
  scrim.addEventListener('click', event => {
    if (event.target === scrim) close()
  })

  // Header
  const header = document.createElement('header')
  header.className = css.header ?? 'openwrite-release-header'

  const badgeRow = document.createElement('div')
  badgeRow.className = css.badgeRow ?? 'openwrite-release-badge-row'

  const badge = document.createElement('span')
  badge.className = css.badge ?? 'openwrite-release-badge'
  badge.textContent = `OpenWrite v${version} · ${translate('settings.releaseModal.badge')}`
  badgeRow.appendChild(badge)

  const title = document.createElement('h2')
  title.className = css.title ?? 'openwrite-release-title'
  title.textContent = translate('settings.releaseModal.title')

  header.appendChild(badgeRow)
  header.appendChild(title)

  // Body
  const body = document.createElement('div')
  body.className = css.body ?? 'openwrite-release-body'

  const intro = document.createElement('p')
  intro.textContent = translate('settings.releaseModal.intro')
  body.appendChild(intro)

  // Project card (exclusively OpenWrite)
  const projectCard = document.createElement('div')
  projectCard.className = css.projectCard ?? 'openwrite-release-project-card'

  const projectHeader = document.createElement('div')
  projectHeader.className = css.projectHeader ?? 'openwrite-release-project-header'

  const projectLink = document.createElement('a')
  projectLink.className = css.projectLink ?? 'openwrite-release-project-link'
  projectLink.href = OPENWRITE_REPO_URL
  projectLink.target = '_blank'
  projectLink.rel = 'noreferrer'
  projectLink.textContent = 'OpenWrite'
  projectLink.addEventListener('click', () => markReleaseAnnouncementSeen(version))

  const projectRepo = document.createElement('span')
  projectRepo.className = css.projectRepo ?? 'openwrite-release-project-repo'
  projectRepo.textContent = 'LiPu-jpg/Openwrite'

  projectHeader.appendChild(projectLink)
  projectHeader.appendChild(projectRepo)

  const projectDesc = document.createElement('p')
  projectDesc.textContent = translate('settings.releaseModal.projectDesc')

  projectCard.appendChild(projectHeader)
  projectCard.appendChild(projectDesc)
  body.appendChild(projectCard)

  // What's new section
  const whatsNewTitle = document.createElement('h3')
  whatsNewTitle.className = css.sectionTitle ?? 'openwrite-release-section-title'
  whatsNewTitle.textContent = `${translate('settings.releaseModal.whatsNewTitle')} (v${version})`
  body.appendChild(whatsNewTitle)

  const list = document.createElement('ul')
  list.className = css.list ?? 'openwrite-release-list'
  for (const key of ['settings.releaseModal.item1', 'settings.releaseModal.item2', 'settings.releaseModal.item3'] as const) {
    const li = document.createElement('li')
    li.textContent = translate(key)
    list.appendChild(li)
  }
  body.appendChild(list)

  // Supported companion plugins section
  const isEnglish = translate('settings.tab.host') === 'Host'
  const companionsTitle = document.createElement('h3')
  companionsTitle.className = css.sectionTitle ?? 'openwrite-release-section-title'
  companionsTitle.textContent = translate('settings.releaseModal.companionsTitle')
  body.appendChild(companionsTitle)

  const companionsIntro = document.createElement('p')
  companionsIntro.className = css.companionsIntro ?? 'openwrite-release-companions-intro'
  companionsIntro.textContent = translate('settings.releaseModal.companionsHint')
  body.appendChild(companionsIntro)

  const companionGrid = document.createElement('div')
  companionGrid.className = css.companionGrid ?? 'openwrite-release-companion-grid'
  for (const plugin of COMPANION_PLUGINS) {
    const card = document.createElement('div')
    card.className = css.companionCard ?? 'openwrite-release-companion-card'

    const cardTop = document.createElement('div')
    cardTop.className = css.companionTop ?? 'openwrite-release-companion-top'

    const nameGroup = document.createElement('div')
    nameGroup.className = css.companionIdentity ?? 'openwrite-release-companion-identity'

    const nameEl = document.createElement('strong')
    nameEl.textContent = plugin.name

    const pkgEl = document.createElement('code')
    pkgEl.className = css.companionPkg ?? 'openwrite-release-companion-pkg'
    pkgEl.textContent = plugin.npmPackage

    nameGroup.appendChild(nameEl)
    nameGroup.appendChild(pkgEl)

    const link = document.createElement('a')
    link.className = css.companionLink ?? 'openwrite-release-companion-link'
    link.href = plugin.url
    link.target = '_blank'
    link.rel = 'noreferrer'
    link.textContent = translate('settings.releaseModal.starPlugin')
    link.addEventListener('click', () => markReleaseAnnouncementSeen(version))

    cardTop.appendChild(nameGroup)
    cardTop.appendChild(link)

    const desc = document.createElement('p')
    desc.className = css.companionDesc ?? 'openwrite-release-companion-desc'
    desc.textContent = isEnglish ? plugin.roleEn : plugin.roleZh

    card.appendChild(cardTop)
    card.appendChild(desc)
    companionGrid.appendChild(card)
  }
  body.appendChild(companionGrid)

  // Heartfelt note
  const heartfelt = document.createElement('div')
  heartfelt.className = css.heartfelt ?? 'openwrite-release-heartfelt'
  heartfelt.textContent = translate('settings.releaseModal.heartfelt')
  body.appendChild(heartfelt)

  // Footer
  const footer = document.createElement('footer')
  footer.className = css.footer ?? 'openwrite-release-footer'

  const starCta = document.createElement('a')
  starCta.className = css.starCta ?? 'openwrite-release-star-cta'
  starCta.href = OPENWRITE_REPO_URL
  starCta.target = '_blank'
  starCta.rel = 'noreferrer'
  starCta.textContent = translate('settings.releaseModal.starCta')
  starCta.addEventListener('click', () => close())

  const feedbackCta = document.createElement('a')
  feedbackCta.className = css.feedbackCta ?? 'openwrite-release-feedback-cta'
  feedbackCta.href = issueUrl
  feedbackCta.target = '_blank'
  feedbackCta.rel = 'noreferrer'
  feedbackCta.textContent = translate('settings.releaseModal.feedbackCta')
  feedbackCta.addEventListener('click', () => markReleaseAnnouncementSeen(version))

  const dismissBtn = document.createElement('button')
  dismissBtn.type = 'button'
  dismissBtn.className = css.dismissButton ?? 'openwrite-release-dismiss'
  dismissBtn.textContent = translate('settings.releaseModal.dismiss')
  dismissBtn.addEventListener('click', () => close())

  footer.appendChild(starCta)
  footer.appendChild(feedbackCta)
  footer.appendChild(dismissBtn)

  modal.appendChild(header)
  modal.appendChild(body)
  modal.appendChild(footer)
  scrim.appendChild(modal)
  document.body.appendChild(scrim)

  return scrim
}

/**
 * Show the OpenWrite release announcement modal automatically if and only if
 * the current release version has not been acknowledged in `localStorage`.
 */
export function maybeShowReleaseAnnouncement(options: ReleaseAnnouncementOptions = {}): HTMLElement | null {
  if (typeof window === 'undefined' || typeof document === 'undefined' || !document.body) return null
  const allowWebdriver = options.allowWebdriver === true
    || (window as typeof window & { __OPENWRITE_ALLOW_WEBDRIVER_POPUP__?: boolean }).__OPENWRITE_ALLOW_WEBDRIVER_POPUP__ === true
  if (window.navigator?.webdriver === true && !allowWebdriver) {
    return null
  }
  const version = options.version ?? resolveOpenWriteVersion()
  if (hasSeenReleaseAnnouncement(version)) return null
  return showReleaseAnnouncementModal({ ...options, version })
}

/**
 * The product design system.
 *
 * One import path for everything an application renders: primitives, brand,
 * the public marketing sections and the authentication frame. Applications
 * import from `@<slug>/ui` and never from a file inside it, so the internal
 * layout can change without touching a page.
 *
 * The package ships TypeScript sources rather than built output -- `main`
 * points at `src/index.ts` and each application lists this package in
 * `transpilePackages`. That is what lets a component here be a React Server
 * Component in one application and carry `'use client'` in another; a `tsc`
 * build would have to pick one, and directives do not survive the round trip
 * intact.
 *
 * Everything visual is drawn from `@<slug>/branding`. Nothing in this package
 * hardcodes a colour, a name or a link.
 */

export { cn } from './lib/cn'
export type { ClassValue } from './lib/cn'
export { appHref } from './lib/links'

export { LanguageSwitcher } from './i18n/language-switcher'
export { codeTag, rich, strongTag } from './i18n/rich'
export type { RichTags } from './i18n/rich'

export { Button, ButtonLink } from './primitives/button'
export type { ButtonSize, ButtonVariant } from './primitives/button'
export { Banner } from './primitives/banner'
export { Card } from './primitives/card'
export { Container } from './primitives/container'
export { Drawer } from './primitives/drawer'
export { SelectField, TextField } from './primitives/field'
export { SubmitButton } from './primitives/submit-button'
export { Icon } from './primitives/icon'
export { Section } from './primitives/section'
export { MAX_TOASTS, TOAST_MS, ToastProvider, useToast } from './primitives/toast'
export type { Toast, ToastTone } from './primitives/toast'

export { NotificationBell } from './notifications/notification-bell'
export { NotificationList } from './notifications/notification-list'
// The formatter for the `unread` label template. Public because the product's
// own notification centre is a client component that draws the same count.
export { withCount } from './notifications/types'
export type {
  NotificationItem,
  NotificationLabels,
  NotificationTone,
} from './notifications/types'

export { brandStyle } from './brand/brand-style'
export { BrandScope } from './brand/brand-scope'
export { KorasWordmark, ProductLogo } from './brand/product-logo'

export { AppFrame } from './marketing/app-frame'
export { CtaSection } from './marketing/cta-section'
export { FeatureCard, FeatureGrid } from './marketing/feature-grid'
export { HeroSection } from './marketing/hero-section'
export { HowItWorks } from './marketing/how-it-works'
export { OutcomeSection } from './marketing/outcome-section'
export { ProductPreview } from './marketing/product-preview'
export { ProductVisual } from './marketing/product-visual'
export { PricingSection } from './marketing/pricing-section'
export { PricingPlans, formatAmount } from './marketing/pricing-plans'
export type { PricingLabels } from './marketing/pricing-plans'
export { PublicFooter } from './marketing/public-footer'
export { PublicHeader } from './marketing/public-header'
export { TrustSection } from './marketing/trust-section'
export { ValueStrip } from './marketing/value-strip'

export { AccessDenied } from './shell/access-denied'
export { AuthenticatedProductShell } from './shell/product-shell'
export {
  SubscriptionClosed,
  SubscriptionNotice,
  subscriptionBlocks,
} from './shell/subscription-notice'
export type { ShellIdentity } from './shell/product-shell'
export { ProductHeader } from './shell/product-header'
export { ProductNavigation } from './shell/product-navigation'
export { ProductProfileMenu } from './shell/profile-menu'
export { WorkspaceBadge } from './shell/workspace-badge'
export { ThemeToggle, THEME_SCRIPT, THEME_STORAGE_KEY } from './shell/theme-toggle'
export type { ThemeChoice } from './shell/theme-toggle'

export { AuthBrandPanel, AuthLayout } from './auth/auth-layout'

export { AITrigger } from './ai/ai-trigger'
export { AIDrawer } from './ai/ai-drawer'
export { AIConversation } from './ai/ai-conversation'
export { AIMessage } from './ai/ai-message'
export { AIComposer } from './ai/ai-composer'
export { AISuggestedActions } from './ai/ai-suggested-actions'
export { AICitations } from './ai/ai-citations'
export { AIToolResult } from './ai/ai-tool-result'
export { AIActionApproval } from './ai/ai-action-approval'
export { AIUsageNotice } from './ai/ai-usage-notice'
export { AIError } from './ai/ai-error'
export type {
  AIActionItem,
  AICitationItem,
  AIConversationLabels,
  AIMessageItem,
} from './ai/types'
export { AuthCard } from './auth/auth-card'
export { InvitationOnlyCard, RequestAccessCard } from './auth/access-cards'

export { MetricCard, MetricGrid } from './reporting/metric-card'
export { ReportChart } from './reporting/report-chart'
export { ReportTable } from './reporting/report-table'
export { ReportFilters } from './reporting/report-filters'
export { ReportHeader } from './reporting/report-header'
export { ReportList } from './reporting/report-list'
export { ExportMenu } from './reporting/export-menu'
export { ExportList, ScheduleForm, ScheduleList } from './reporting/schedules'
export type { ExportData, ScheduleData } from './reporting/schedules'
export { ReportEmptyState, ReportErrorState, ReportLoadingState } from './reporting/report-states'
export { formatBucket, formatBytes, formatDuration, formatValue, trend } from './reporting/format'
export type {
  FilterViewData,
  MetricValueData,
  RangeData,
  ReportResultData,
  ReportSummaryData,
  ReportViewData,
  ReportingLabels,
  SeriesData,
  TableData,
  ValueFormat,
  ValueKind,
  ValueUnit,
  VisualizationKind,
} from './reporting/types'

// The settings a signed-in person's pages resolve against, loaded once in the
// dashboard layout and handed down. Never capability-gated: the shell reads
// them before it paints, in every product.
export { SettingsProvider, useSetting, useSettingValue, useSettings } from './settings/provider'
export { STANDARD_SETTING_KEYS } from './settings/types'
export { chooseValue, sameShape, settingValue } from './settings/value'
export { parseEffectiveSettings } from './settings/parse'
export { SettingsForm } from './settings/settings-form'
// `withValue` is public for the same reason `withCount` is: a label that
// needs a value in it must cross the server/client boundary as a string, so
// the component holding the value is the one that fills it.
export { describeValue, optionLabel, withValue } from './settings/fields'
export type {
  SettingField,
  SettingFieldOption,
  SettingGroup,
  SettingsFormLabels,
} from './settings/fields'
export type {
  EffectiveSettings,
  ResolvedSetting,
  SettingKey,
  SettingSource,
  SettingValue,
} from './settings/types'

// The product's table. Pages itself from the customer's own `grid.*` settings,
// and an explicit prop always wins over one.
export { KorasDataTable } from './data-table/data-table'
export type { DataTableColumn } from './data-table/data-table'
export type { DataTableLabels } from './data-table/types'
export {
  DEFAULT_PAGE_SIZE,
  DEFAULT_PAGE_SIZE_OPTIONS,
  MAX_PAGE_SIZE,
  MIN_PAGE_SIZE,
  clampPage,
  clampSize,
  paginate,
  sizeOptions,
} from './data-table/paging'
export type { Paging } from './data-table/paging'
// Pure, and exported for the same reason `paging` is: this package has no test
// runner, and the starter's suite executes these directly.
export {
  MAX_COLUMN_WIDTH,
  MIN_COLUMN_WIDTH,
  applyArrangement,
  clampWidth,
  parseArrangement,
  storageKey,
} from './data-table/columns'
export type { Arrangement } from './data-table/columns'

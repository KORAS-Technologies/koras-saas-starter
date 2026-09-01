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

export { Button, ButtonLink } from './primitives/button'
export type { ButtonSize, ButtonVariant } from './primitives/button'
export { Card } from './primitives/card'
export { Container } from './primitives/container'
export { SelectField, TextField } from './primitives/field'
export { Icon } from './primitives/icon'
export { Section } from './primitives/section'

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
export { PublicFooter } from './marketing/public-footer'
export { PublicHeader } from './marketing/public-header'
export { TrustSection } from './marketing/trust-section'
export { ValueStrip } from './marketing/value-strip'

export { AccessDenied } from './shell/access-denied'
export { AuthenticatedProductShell } from './shell/product-shell'
export type { ShellIdentity } from './shell/product-shell'
export { ProductHeader } from './shell/product-header'
export { ProductNavigation } from './shell/product-navigation'
export { ProductProfileMenu } from './shell/profile-menu'
export { WorkspaceBadge } from './shell/workspace-badge'
export { ThemeToggle, THEME_SCRIPT, THEME_STORAGE_KEY } from './shell/theme-toggle'
export type { ThemeChoice } from './shell/theme-toggle'

export { AuthBrandPanel, AuthLayout } from './auth/auth-layout'
export { AuthCard } from './auth/auth-card'
export { InvitationOnlyCard, RequestAccessCard } from './auth/access-cards'

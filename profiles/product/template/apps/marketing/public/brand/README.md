# Brand assets

Put this product's logo files here, then point `packages/branding/src/index.ts`
at them:

```ts
brand: mergeBranding(defaultBranding, {
  logoUrl: '/brand/logo.svg',
  logoDarkUrl: '/brand/logo-dark.svg', // optional; used on the hero and footer
  faviconUrl: '/brand/icon.svg',
})
```

Anything referenced from here must also exist in `apps/web/public/brand/`
if this product generates the web application — the two applications are deployed
separately and do not share a public directory.

This application has no session gate, so these files are served to anyone. The
web application does have one, and excludes `brand/` from its middleware matcher
for exactly this reason.

Leave this directory empty and nothing breaks: `ProductLogo` draws a neutral
mark in the product's primary colour beside the product name. See
`docs/PRODUCT_FRONTEND.md`.

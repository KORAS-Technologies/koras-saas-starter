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

Anything referenced from here must also exist in `apps/marketing/public/brand/`
if this product generates the marketing site — the two applications are deployed
separately and do not share a public directory.

`brand/` is excluded from the middleware matcher in `src/middleware.ts`, which
is what makes these files reachable without a session. Without that exclusion a
logo on the public homepage is answered with a redirect to `/login` and renders
as a broken image.

Leave this directory empty and nothing breaks: `ProductLogo` draws a neutral
mark in the product's primary colour beside the product name. See
`docs/PRODUCT_FRONTEND.md`.

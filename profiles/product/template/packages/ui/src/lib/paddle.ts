/**
 * The little this product knows about Paddle.js, in one place.
 *
 * Two surfaces load the provider's script: the checkout on the verify page
 * and the price preview on the pricing section. Both need the same script
 * address, the same environment rule and the same view of the global the
 * script installs -- and a global declared twice with two shapes is a type
 * error in whichever file is compiled second.
 *
 * What is deliberately not here: any call. This file describes the script; the
 * components decide what to ask it.
 */

export const PADDLE_JS = 'https://cdn.paddle.com/paddle/v2/paddle.js'

export type PaddleEnvironment = 'sandbox' | 'production'

/**
 * Which Paddle a client-side token belongs to.
 *
 * `production` only when said so. The default is the sandbox, so a product
 * deployed with a token and no environment setting opens a checkout that
 * takes no real money -- the wrong default here would be one that charges a
 * card from a test.
 */
export function paddleEnvironment(value: string | undefined): PaddleEnvironment {
  return value === 'production' ? 'production' : 'sandbox'
}

export interface PaddlePriceLine {
  price: { id: string }
  formattedTotals: { subtotal: string; total: string }
  formattedUnitTotals?: { subtotal: string; total: string }
}

export interface PaddleJs {
  Environment: { set(environment: PaddleEnvironment): void }
  Initialize(options: { token: string; eventCallback?: (event: { name?: string }) => void }): void
  Checkout: {
    open(options: {
      items: { priceId: string; quantity: number }[]
      customer?: { email?: string }
      customData?: Record<string, string>
      settings?: { displayMode?: 'overlay' | 'inline'; locale?: string }
    }): void
  }
  PricePreview(request: {
    items: { priceId: string; quantity: number }[]
    address?: { countryCode?: string }
  }): Promise<{ data: { details: { lineItems: PaddlePriceLine[] } } }>
}

declare global {
  interface Window {
    Paddle?: PaddleJs
  }
}

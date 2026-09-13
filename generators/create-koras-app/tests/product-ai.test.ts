import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

/**
 * The AI foundation, checked from the template text.
 *
 * It crosses more boundaries than any module before it -- four tables with
 * policies, a Python package, an API dependency and router, a permission
 * catalogue in two languages, a navigation entry, a gateway model list and
 * a page -- and each has a name the other side must agree on. These are the
 * agreements, asserted here because no single test suite sees both sides of
 * any of them: the RLS suite proves the policies say what they say, the
 * package tests prove the runtime, the router tests prove the surface, and
 * this proves the names match.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const STARTER = join(PRODUCT, '..', '..', '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function has(...segments: string[]): boolean {
  return existsSync(join(PRODUCT, ...segments))
}

// ── the tables ────────────────────────────────────────────────────────────────

describe('the tables', () => {
  const migration = read('supabase', 'migrations', '00006_ai.sql')
  const tables = ['ai_conversations', 'ai_messages', 'ai_actions', 'ai_usage_events']

  it.each(tables)('%s is scoped, forced and policed like every tenant table', (table) => {
    expect(migration).toMatch(
      new RegExp(`create table public\\.${table} \\([\\s\\S]*?tenant_id\\s+uuid not null references public\\.tenants\\(id\\)`),
    )
    expect(migration).toContain(`alter table public.${table} enable row level security;`)
    expect(migration).toContain(`alter table public.${table} force row level security;`)
    for (const verb of ['select', 'insert']) {
      expect(migration, `${table}: no ${verb} policy`).toMatch(
        new RegExp(`on public\\.${table} for ${verb}`),
      )
    }
    expect(migration).toMatch(
      new RegExp(`on public\\.${table} for insert\\s+with check \\(tenant_id = public\\.current_tenant_id\\(\\)\\)`),
    )
  })

  it('lets nobody rewrite a usage row', () => {
    // A usage event is a fact about a call that happened. No update, no delete.
    expect(migration).not.toMatch(/on public\.ai_usage_events for (update|delete)/)
  })

  it('holds no credential and no provider secret', () => {
    expect(migration).not.toMatch(/secret|access_key|api_key/i)
  })

  it('is exercised by the isolation suite', () => {
    const suite = read('supabase', 'tests', '060_ai_isolation.sql')
    expect(suite).toContain('set local role koras_rls_test;')
    expect(suite).toContain("raise exception 'ai: another tenant''s message was visible'")
    expect(suite).toContain("raise exception 'ai: another tenant''s action was approved'")
    expect(suite).toContain('a message was written into another tenant')
  })
})

// ── the names the sides share ─────────────────────────────────────────────────

describe('the names the sides share', () => {
  const branding = read('packages', 'branding', 'src', 'index.ts.hbs')
  const permissions = read('packages', 'permissions', 'src', 'index.ts')
  const pyPermissions = read('python-packages', 'koras-auth', 'src', 'koras_auth', 'permissions.py')
  const core = read('services', 'api', 'koras_api', 'core', 'ai.py')

  it('gates the module on the same entitlement the API enforces', () => {
    expect(core).toContain('AI_ENTITLEMENT = "ai.assistant"')
    expect(branding).toMatch(/id: 'assistant',[\s\S]*?requiredEntitlements: \['ai\.assistant'\]/)
    expect(branding).toMatch(/id: 'assistant',[\s\S]*?requiredCapabilities: \['ai'\]/)
    expect(branding).toMatch(/id: 'assistant',[\s\S]*?requiredPermissions: \['ai\.use'\]/)
    expect(core).toContain('status.HTTP_402_PAYMENT_REQUIRED')
  })

  it('names the two permissions in both catalogues', () => {
    for (const permission of ['ai.use', 'ai.approve']) {
      expect(permissions).toContain(`'${permission}'`)
      expect(pyPermissions).toContain(`"${permission}"`)
    }
  })

  /**
   * The Python catalogue mirrors the TypeScript one by hand, because the two
   * runtimes cannot import each other. This is what keeps them level: the
   * permission list and the map from each role are parsed out of both files
   * and compared as sets.
   */
  it('keeps the Python permission catalogue level with the TypeScript one', () => {
    const tsList = /export const PRODUCT_PERMISSIONS = \[([\s\S]*?)\] as const/.exec(permissions)
    const pyList = /PRODUCT_PERMISSIONS: tuple\[str, \.\.\.\] = \(([\s\S]*?)\)\n/.exec(pyPermissions)
    expect(tsList && pyList).toBeTruthy()
    const names = (block: string) => [...block.matchAll(/['"]([a-z_.]+)['"]/g)].map((m) => m[1]).sort()
    expect(names(pyList?.[1] ?? '')).toEqual(names(tsList?.[1] ?? ''))

    // Per role. The Python side spells owner and admin as the whole catalogue
    // and members through a shared tuple; both are resolved by the permissions
    // package's own test at runtime. Here the two files' explicit lists are
    // compared for the three roles that carry a literal list on both sides.
    const tsRole = (role: string) => {
      const match = new RegExp(`^ {2}${role}: \\[([^\\]]*)\\]`, 'm').exec(permissions)
      return names(match?.[1] ?? '')
    }
    const everyone = names(/_EVERYONE: tuple\[str, \.\.\.\] = \(([^)]*)\)/.exec(pyPermissions)?.[1] ?? '')
    const pyRole = (role: string) => {
      const match = new RegExp(`OrganizationRole\\.${role}: \\(\\*_EVERYONE, ([^)]*)\\)`).exec(pyPermissions)
      return [...everyone, ...names(match?.[1] ?? '')].sort()
    }
    expect(pyRole('SECURITY_ADMIN')).toEqual(tsRole('security_admin'))
    expect(pyRole('BILLING_ADMIN')).toEqual(tsRole('billing_admin'))
    expect(everyone).toEqual(tsRole('member'))
  })

  it('routes every catalogue model to a name the gateway lists', () => {
    const catalogue = read('services', 'api', 'koras_api', 'ai', 'models.py')
    const gateway = read('services', 'ai-gateway', 'litellm_config.yaml')
    const listed = new Set([...gateway.matchAll(/model_name: (\S+)/g)].map((m) => m[1]))
    const routed = [...catalogue.matchAll(/model="([^"]+)"/g)].map((m) => m[1])
    expect(routed.length).toBeGreaterThan(3)
    for (const model of routed) {
      expect(listed.has(model), `${model} is routed to but the gateway does not list it`).toBe(true)
    }
    // And never a vendor route: the gateway is the only place one is written.
    expect(catalogue).not.toMatch(/openai\/|anthropic\//)
  })

  it('serves the page the module points at, and a browser test for it', () => {
    expect(has('apps', 'web', 'src', 'app', 'dashboard', 'assistant', 'page.tsx.hbs')).toBe(true)
    expect(has('e2e', 'assistant.spec.ts.hbs')).toBe(true)
  })
})

// ── the capability ────────────────────────────────────────────────────────────

describe('the capability', () => {
  const manifest = yaml.load(readFileSync(join(STARTER, 'profiles', 'product', 'manifest.yaml'), 'utf8')) as {
    capabilities: Record<string, boolean>
    template_map: { capabilities: Record<string, string | string[]> }
    requires: Record<string, string[]>
  }
  const defaults = yaml.load(readFileSync(join(STARTER, 'profiles', 'product', 'defaults.yaml'), 'utf8')) as {
    capabilities: Record<string, boolean>
  }

  it('is declared, off by default, and needs the gateway', () => {
    expect(manifest.capabilities.ai).toBe(true)
    expect(defaults.capabilities.ai).toBe(false)
    expect(manifest.requires.ai).toEqual(['ai_gateway'])
  })

  it('gates paths that all exist in the template', () => {
    const paths = manifest.template_map.capabilities.ai
    expect(Array.isArray(paths)).toBe(true)
    for (const path of paths as string[]) {
      const found = has(path) || has(`${path}.hbs`)
      expect(found, `${path} is gated but not in the template`).toBe(true)
    }
    // The four things a product cannot run AI without.
    expect(paths).toContain('services/api/koras_api/routers/ai.py')
    expect(paths).toContain('supabase/migrations/00006_ai.sql')
    expect(paths).toContain('apps/web/src/app/dashboard/assistant')
    expect(paths).toContain('services/api/koras_api/ai')
  })

  it('runs in Generator Integration with the browser suite', () => {
    const workflow = readFileSync(join(STARTER, '.github', 'workflows', 'generator-integration.yml'), 'utf8')
    expect(workflow).toMatch(/--with [a-z_,]*\bai\b[a-z_,]*/)
    expect(workflow).toMatch(/--with [a-z_,]*ai_gateway/)
  })
})

// ── the boundary ──────────────────────────────────────────────────────────────

describe('the boundary', () => {
  it('keeps the provider library in the gateway and out of the runtime', () => {
    const runtime = read('python-packages', 'koras-ai', 'pyproject.toml')
    // The dependency list alone: the manifest's comment is allowed to say why
    // the proxy library is absent, and does.
    const dependencies = /dependencies = \[([\s\S]*?)\]/.exec(runtime)?.[1] ?? ''
    expect(dependencies).not.toContain('litellm')
    expect(dependencies).toContain('httpx')
    const gateway = read('services', 'ai-gateway', 'pyproject.toml.hbs')
    expect(gateway).toContain('litellm')
  })

  it('keeps the API address and the token on the server', () => {
    const panel = read('apps', 'web', 'src', 'app', 'dashboard', 'assistant', 'AssistantPanel.tsx.hbs')
    const launcher = read('apps', 'web', 'src', 'app', 'dashboard', 'assistant', 'AssistantLauncher.tsx.hbs')
    const actions = read('apps', 'web', 'src', 'app', 'dashboard', 'assistant', 'actions.ts.hbs')
    for (const source of [panel, launcher]) {
      expect(source).not.toContain('NEXT_PUBLIC_API_URL')
      expect(source).not.toContain('providerToken')
      expect(source).not.toContain('LITELLM_MASTER_KEY')
    }
    expect(actions).toContain("'use server'")
    expect(actions).toContain('providerToken()')
  })

  it('tells the gateway README to use the runtime, not a vendor SDK', () => {
    const readme = read('services', 'ai-gateway', 'README.md')
    expect(readme).not.toContain('new OpenAI(')
    expect(readme).toContain('koras_ai')
  })

  it('exports every assistant component from the design system', () => {
    const barrel = read('packages', 'ui', 'src', 'index.ts')
    for (const name of [
      'AITrigger',
      'AIDrawer',
      'AIConversation',
      'AIMessage',
      'AIComposer',
      'AISuggestedActions',
      'AICitations',
      'AIToolResult',
      'AIActionApproval',
      'AIUsageNotice',
      'AIError',
    ]) {
      expect(barrel).toContain(`export { ${name} }`)
    }
  })

  it('puts nothing of the assistant into the shell', () => {
    const shell = join(PRODUCT, 'packages', 'ui', 'src', 'shell')
    for (const file of ['product-shell.tsx.hbs', 'product-header.tsx.hbs', 'product-navigation.tsx.hbs']) {
      expect(readFileSync(join(shell, file), 'utf8')).not.toMatch(/assistant|AITrigger|AIDrawer/i)
    }
  })
})

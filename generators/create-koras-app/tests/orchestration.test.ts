import { describe, it, expect, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { rmSync, existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import yaml from 'js-yaml'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'
import { validateGeneratedProject } from '../src/validation/generated-project.js'
import { WORKTREE_SEGMENTS } from '../src/generation/skip.js'
import {
  DEVELOPER_WORKERS,
  PRODUCT_ORCHESTRATION_PATHS,
  PROFILE_CARRIES_ORCHESTRATION,
} from '../src/validation/claude-config.js'

/**
 * The multi-agent engineering framework is a *product* capability.
 *
 * It is template-owned at `profiles/product/template/.claude/` rather than
 * placed in the starter's root `.claude`, because that directory is a
 * shared_asset: copied verbatim and unconditionally into both profiles. The
 * two halves asserted here are "a product got it" and "the Control Plane did
 * not", and the second is the one that fails quietly -- a Control Plane
 * repository carrying a customer-product orchestration contract looks entirely
 * normal until an agent follows it.
 *
 * Everything else in this file exists because the framework is configuration
 * describing other configuration. A registry that names an agent with no file,
 * a workflow that routes to an id nobody defined, or a policy pointing at a
 * template that was never written are all silent: nothing goes red, and the
 * first symptom is an agent behaving as though a rule does not exist.
 */

const STARTER_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../..')
const PRODUCT_TEMPLATE = join(STARTER_ROOT, 'profiles/product/template')
const ORCHESTRATION = join(PRODUCT_TEMPLATE, '.claude/orchestration')

const OUT = join(tmpdir(), `koras-orch-${process.pid}-${Date.now()}`)
afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

interface RegistryAgent {
  id: string
  category: string
  title: string
  definition: string
  modifies_production_code: 'yes' | 'no' | 'limited'
}

interface Registry {
  schema_version: number
  agent_count: number
  category_counts: Record<string, number>
  developer_pool: {
    workers: string[]
    max_parallel: number
    isolation: string
    worktree_root: string
    worktree_path: string
  }
  agents: RegistryAgent[]
}

interface ActivationRules {
  schema_version: number
  always_consider: string[]
  conditional: Record<string, { trigger: string; agents: string[] }>
}

interface Workflow {
  schema_version: number
  workflow: {
    planning: { sequence: string[]; human_gate: string }
    execution: {
      coordinator: string
      developer_pool: string[]
      max_parallel_developers: number
      isolation: string
      pre_parallel_checks: string[]
    }
    verification: { default: string[]; independence_required: string[] }
    rework: { failed_gate_route: string; require_independent_reverification: boolean; blocking_severities: string[] }
    integration: { agent: string; required_when: string[] }
    completion: { acceptance: string; human_gates: string[] }
  }
}

interface QualityGates {
  schema_version: number
  human_gates: Record<string, { required: boolean; description: string }>
  blocking_severities: string[]
  feature_gates: Array<{ id: string; owner: string; applies: string; independent?: boolean }>
}

interface DocumentationPolicy {
  schema_version: number
  documentation: {
    root_pattern: string
    sections: Record<string, string>
    required_for_all_features: string[]
    required_for_user_facing_features: string[]
    screenshot_path: string
    screenshot_naming: string
    templates: { root: string; map: Record<string, string> }
    test_case_fields: string[]
    evidence_rules: Record<string, boolean | string[]>
  }
}

interface DomainRegistryExample {
  agents: Array<{ id: string; definition: string; role: string }>
  domain_review: { contract: string }
}

function readYaml<T>(absPath: string): T {
  return yaml.load(readFileSync(absPath, 'utf8')) as T
}

function walk(dir: string, base = dir): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir).flatMap((entry) => {
    const abs = join(dir, entry)
    return statSync(abs).isDirectory()
      ? walk(abs, base)
      : [abs.slice(base.length + 1).replace(/\\/g, '/')]
  })
}

const registry = readYaml<Registry>(join(ORCHESTRATION, 'agent-registry.yaml'))
const activation = readYaml<ActivationRules>(join(ORCHESTRATION, 'activation-rules.yaml'))
const workflow = readYaml<Workflow>(join(ORCHESTRATION, 'workflow.yaml'))
const gates = readYaml<QualityGates>(join(ORCHESTRATION, 'quality-gates.yaml'))
const docPolicy = readYaml<DocumentationPolicy>(join(ORCHESTRATION, 'documentation-policy.yaml'))

const AGENT_IDS: string[] = registry.agents.map((a) => a.id)

async function generate(profile: ProfileName, slug: string) {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  const { fileList } = await writeFiles(ctx, renderTemplate(ctx))
  const projectRoot = join(OUT, slug)
  return {
    slug,
    profile,
    projectRoot,
    fileList,
    has: (p: string) => existsSync(join(projectRoot, p)),
    read: (p: string) => readFileSync(join(projectRoot, p), 'utf8'),
  }
}

const PRODUCT = await generate('product', 'orch-product')
const CONTROL_PLANE = await generate('control-plane', 'orch-cp')

describe('the framework reaches the product profile and only the product profile', () => {
  it.each(PRODUCT_ORCHESTRATION_PATHS)('a product carries %s', (path) => {
    expect(PRODUCT.has(path)).toBe(true)
  })

  it.each(PRODUCT_ORCHESTRATION_PATHS)('the Control Plane does not carry %s', (path) => {
    expect(CONTROL_PLANE.has(path)).toBe(false)
  })

  it('gives the Control Plane no orchestration, agents or domain tree at all', () => {
    const leaked = CONTROL_PLANE.fileList.filter(
      (f) =>
        f.startsWith('.claude/orchestration/') ||
        f.startsWith('.claude/agents/orchestration/') ||
        f.startsWith('.claude/agents/planning/') ||
        f.startsWith('.claude/agents/development/') ||
        f.startsWith('.claude/agents/testing/') ||
        f.startsWith('.claude/agents/review/') ||
        f.startsWith('.claude/agents/documentation/') ||
        f.startsWith('.claude/agents/delivery/') ||
        f.startsWith('.claude/domain/') ||
        f.startsWith('.claude/templates/'),
    )
    expect(leaked).toEqual([])
  })

  it('keeps the framework out of the shared asset, which both profiles receive', () => {
    // The mechanism, not just the outcome. If any of this were placed in the
    // starter's root `.claude`, the assertions above would start failing for
    // the Control Plane -- so assert directly that it is not there.
    for (const path of PRODUCT_ORCHESTRATION_PATHS) {
      expect(existsSync(join(STARTER_ROOT, path))).toBe(false)
    }
  })

  it('still gives both profiles the four original Koras agents, unchanged', () => {
    // The V2 package replaced these with three-line stubs. They are shared
    // configuration and their content is a capability: emptying them is
    // invisible to every other check, because the files still exist.
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      for (const agent of ['architect', 'frontend', 'reviewer', 'tester']) {
        const body = gen.read(`.claude/agents/${agent}.md`)
        expect(body).toContain('Koras')
        expect(body).not.toContain('Compatibility Alias')
        expect(body.length).toBeGreaterThan(400)
      }
    }
  })

  it('leaves the four shared commands shared and adds five product-only ones', () => {
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      for (const c of ['feature', 'review', 'test', 'ui-review']) {
        expect(gen.has(`.claude/commands/${c}.md`)).toBe(true)
      }
    }
    for (const c of ['plan-next', 'orchestrate-feature', 'run-parallel', 'manual-test-doc', 'agent-status']) {
      expect(PRODUCT.has(`.claude/commands/${c}.md`)).toBe(true)
      expect(CONTROL_PLANE.has(`.claude/commands/${c}.md`)).toBe(false)
    }
  })

  it('passes post-write validation for both profiles', () => {
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      const result = validateGeneratedProject({
        projectRoot: gen.projectRoot,
        expectedSlug: gen.slug,
        expectedProfile: gen.profile,
      })
      expect(result.error).toBeUndefined()
      expect(result.valid).toBe(true)
    }
  })

  it('declares the split for every profile the generator knows', () => {
    // Guards the guard: a profile added without an entry here would validate
    // by checking neither presence nor absence.
    for (const profile of ['product', 'control-plane']) {
      expect(typeof PROFILE_CARRIES_ORCHESTRATION[profile]).toBe('boolean')
    }
  })
})

describe('the agent registry agrees with the files on disk', () => {
  const definitionFiles = walk(join(PRODUCT_TEMPLATE, '.claude/agents'))
    .filter((f) => f.includes('/'))
    .map((f) => `.claude/agents/${f}`)

  it('registers exactly as many agents as it declares', () => {
    expect(registry.agents).toHaveLength(registry.agent_count)
  })

  it('has one definition file per registered agent, and no unregistered ones', () => {
    const registered = registry.agents.map((a) => a.definition).sort()
    expect(definitionFiles.sort()).toEqual(registered)
  })

  it.each(registry.agents.map((a) => [a.id, a.definition] as [string, string]))(
    '%s has a definition file that exists',
    (_id: string, definition: string) => {
      expect(existsSync(join(PRODUCT_TEMPLATE, definition))).toBe(true)
    },
  )

  it('uses unique agent ids', () => {
    expect(new Set(AGENT_IDS).size).toBe(AGENT_IDS.length)
  })

  it('agrees with the category counts it publishes', () => {
    const actual: Record<string, number> = {}
    for (const a of registry.agents) actual[a.category] = (actual[a.category] ?? 0) + 1
    expect(actual).toEqual(registry.category_counts)
    const summed = Object.values(registry.category_counts as Record<string, number>).reduce(
      (a, b) => a + b,
      0,
    )
    expect(summed).toBe(registry.agent_count)
  })

  it('states the same agent count in the inventory document', () => {
    // The V2 package said 38 in three documents and 40 in the registry. Nothing
    // caught it, because the docs tests only scan top-level `docs/`.
    const inventory = readFileSync(join(PRODUCT_TEMPLATE, '.claude/AGENT-INVENTORY.md'), 'utf8')
    expect(inventory).toContain(`**${registry.agent_count} agents**`)
    for (const id of AGENT_IDS) expect(inventory).toContain(`\`${id}\``)
  })
})

describe('every agent definition is a usable Claude Code agent', () => {
  const agents = registry.agents.map((a) => [
    a.id,
    readFileSync(join(PRODUCT_TEMPLATE, a.definition), 'utf8'),
  ]) as Array<[string, string]>

  it.each(agents)('%s has frontmatter naming itself', (id, body) => {
    expect(body.startsWith('---\n')).toBe(true)
    const frontmatter = body.slice(4, body.indexOf('\n---', 4))
    expect(frontmatter).toContain(`name: ${id}`)
  })

  it.each(agents)('%s has a description long enough to route on', (_id, body) => {
    const description = /^description: (.+)$/m.exec(body)?.[1] ?? ''
    // Claude Code selects an agent from its description. A one-word one is
    // frontmatter that parses and routing that cannot work.
    expect(description.length).toBeGreaterThan(60)
  })

  it.each(agents)('%s declares responsibilities, boundaries, inputs, outputs and handoff', (_id, body) => {
    for (const section of [
      '## Mission',
      '## Activation',
      '## Responsibilities',
      '## Boundaries',
      '## Inputs',
      '## Outputs',
      '## Handoff contract',
    ]) {
      expect(body).toContain(section)
    }
  })

  it.each(agents)('%s states whether it may modify production code', (_id, body) => {
    expect(body).toMatch(/\*\*Modifies production code\*\* \| (Yes|No|Limited)/)
  })

  it.each(agents)('%s states that it never approves its own work', (_id, body) => {
    expect(body).toContain('**Approves its own work** | Never')
  })

  it('does not ship forty near-identical files', () => {
    // The V2 package gave all 38 agents a byte-identical rules block and one
    // differing line of Mission. The files existed; the roles did not.
    const bodies = agents.map(([, body]) =>
      body.slice(0, body.indexOf('## Koras rules that always apply')),
    )
    expect(new Set(bodies).size).toBe(agents.length)

    for (const [id, body] of agents) {
      const responsibilities = /## Responsibilities\n\n([\s\S]*?)\n\n## Boundaries/.exec(body)?.[1] ?? ''
      const boundaries = /## Boundaries\n\n([\s\S]*?)\n\n## Inputs/.exec(body)?.[1] ?? ''
      expect(responsibilities.split('\n').length, `${id} responsibilities`).toBeGreaterThanOrEqual(5)
      expect(boundaries.split('\n').length, `${id} boundaries`).toBeGreaterThanOrEqual(3)
    }
  })

  it('carries no product-specific domain knowledge in the shared agents', () => {
    // The shared catalog is identical in every KORAS product. A product name
    // in one of these files is a domain rule that has escaped `.claude/domain/`.
    for (const [id, body] of agents) {
      for (const product of ['Docoris', 'Dianova', 'LegalApp']) {
        expect(body, `${id} names ${product}`).not.toContain(product)
      }
    }
  })
})

describe('the workflow, activation rules and gates reference real agents', () => {
  // Collected from the leaf positions that name agents, then checked against
  // the registry. Asserting the positive direction would only prove the file
  // mentions something; what matters is that it mentions nothing else.
  const referenced = (doc: unknown, keys: string[]): string[] => {
    const found = new Set<string>()
    const visit = (node: unknown): void => {
      if (Array.isArray(node)) return node.forEach(visit)
      if (!node || typeof node !== 'object') return
      for (const [key, value] of Object.entries(node)) {
        if (keys.includes(key)) {
          for (const v of Array.isArray(value) ? value : [value]) {
            if (typeof v === 'string') found.add(v)
          }
        }
        visit(value)
      }
    }
    visit(doc)
    return [...found]
  }

  it('workflow.yaml names only registered agents', () => {
    const named = referenced(workflow, [
      'sequence',
      'coordinator',
      'developer_pool',
      'default',
      'independence_required',
      'failed_gate_route',
      'acceptance',
      'agent',
    ])
    expect(named.length).toBeGreaterThan(0)
    for (const id of named) expect(AGENT_IDS, `workflow references ${id}`).toContain(id)
  })

  it('activation-rules.yaml names only registered agents', () => {
    const named = [
      ...activation.always_consider,
      ...Object.values(activation.conditional).flatMap((c) => c.agents),
    ]
    expect(named.length).toBeGreaterThan(0)
    for (const id of named) expect(AGENT_IDS, `activation references ${id}`).toContain(id)
  })

  it('every conditional activation rule states its trigger', () => {
    for (const [name, rule] of Object.entries(activation.conditional) ) {
      expect(typeof rule.trigger, `${name} trigger`).toBe('string')
      expect(rule.agents.length, `${name} agents`).toBeGreaterThan(0)
    }
  })

  it('quality-gates.yaml names only registered agents as gate owners', () => {
    const owners = gates.feature_gates
      .map((g) => g.owner)
      .filter((o: string) => o !== 'developer_pool' && o !== 'domain_registry')
    expect(owners.length).toBeGreaterThan(0)
    for (const id of owners) expect(AGENT_IDS, `gate owned by ${id}`).toContain(id)
  })

  it('routes gate failures to an agent that exists', () => {
    expect(AGENT_IDS).toContain(workflow.workflow.rework.failed_gate_route)
    expect(workflow.workflow.rework.require_independent_reverification).toBe(true)
  })

  it('does not activate the whole registry for one feature', () => {
    // Over-activation is the failure this contract exists to prevent. The
    // always-on set plus any single conditional set must stay a small
    // fraction of forty.
    const always = activation.always_consider.length
    expect(always).toBeLessThan(AGENT_IDS.length / 2)
    for (const [name, rule] of Object.entries(activation.conditional) ) {
      expect(always + rule.agents.length, `${name}`).toBeLessThan(AGENT_IDS.length)
    }
  })
})

describe('exactly three developer workers, isolated by worktree', () => {
  it('declares three worker slots and no more', () => {
    expect(registry.developer_pool.workers).toEqual([...DEVELOPER_WORKERS])
    expect(registry.developer_pool.max_parallel).toBe(3)
    expect(workflow.workflow.execution.developer_pool).toEqual([...DEVELOPER_WORKERS])
    expect(workflow.workflow.execution.max_parallel_developers).toBe(3)
  })

  it('registers each worker as a real agent definition', () => {
    for (const worker of DEVELOPER_WORKERS) {
      expect(AGENT_IDS).toContain(worker)
      const entry = registry.agents.find((a) => a.id === worker)
      expect(entry.modifies_production_code).toBe('yes')
      expect(existsSync(join(PRODUCT_TEMPLATE, entry.definition))).toBe(true)
    }
  })

  it('configures git-worktree isolation on both sides', () => {
    expect(registry.developer_pool.isolation).toBe('git-worktree')
    expect(workflow.workflow.execution.isolation).toBe('git-worktree')
  })

  it('places the canonical worktree root outside the repository', () => {
    // A worktree inside the repository is copied into every generated project
    // as part of the `.claude` shared asset. One existed on 2026-09-15.
    expect(registry.developer_pool.worktree_root.startsWith('..')).toBe(true)
    expect(registry.developer_pool.worktree_path).toContain('.koras-worktrees')
  })

  it('requires overlap analysis before any concurrent assignment', () => {
    const checks = workflow.workflow.execution.pre_parallel_checks
    expect(checks).toContain('dependency_graph')
    expect(checks).toContain('file_overlap_analysis')
    expect(checks).toContain('contract_overlap_analysis')
  })

  it('tells each worker not to leave its own worktree', () => {
    for (const worker of DEVELOPER_WORKERS) {
      const body = readFileSync(
        join(PRODUCT_TEMPLATE, `.claude/agents/development/${worker}.md`),
        'utf8',
      )
      expect(body).toMatch(/Never edit files outside worktree slot/)
      expect(body).toContain('Never approve, review or accept its own implementation.')
    }
  })
})

describe('runtime worktrees can never be copied into a generated project', () => {
  it('skips every worktree segment during the walk', () => {
    for (const segment of WORKTREE_SEGMENTS) {
      expect(segment.length).toBeGreaterThan(0)
    }
    expect(WORKTREE_SEGMENTS.has('worktrees')).toBe(true)
    expect(WORKTREE_SEGMENTS.has('.koras-worktrees')).toBe(true)
  })

  it('emits no path containing a worktree segment, for either profile', () => {
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      for (const file of gen.fileList) {
        const segments = file.split('/')
        const hit = segments.find((s) => WORKTREE_SEGMENTS.has(s))
        expect(hit, `${gen.profile} emitted ${file}`).toBeUndefined()
      }
    }
  })

  it('never emits a nested .git file or directory', () => {
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      expect(gen.fileList.filter((f) => f.split('/').includes('.git'))).toEqual([])
    }
  })

  it('documents the standard where a worker will read it', () => {
    const standard = PRODUCT.read('.claude/orchestration/WORKTREE-STANDARD.md')
    expect(standard).toContain('.koras-worktrees')
    expect(standard).toMatch(/outside the repository/i)
  })
})

describe('manual QA evidence must be executed, never composed', () => {
  const manualQa = readFileSync(
    join(PRODUCT_TEMPLATE, '.claude/agents/testing/manual-qa.md'),
    'utf8',
  )

  it('declares the three permitted verdicts and nothing else', () => {
    expect(docPolicy.documentation.evidence_rules.verdicts).toEqual(['PASS', 'FAIL', 'BLOCKED'])
  })

  it('requires real execution and forbids fabricated evidence', () => {
    const rules = docPolicy.documentation.evidence_rules
    expect(rules.actual_execution_only).toBe(true)
    expect(rules.no_fabricated_screenshots).toBe(true)
    expect(rules.screenshots_from_executed_steps_only).toBe(true)
    expect(rules.expected_and_actual_required).toBe(true)
    expect(rules.blocked_requires_documented_reason).toBe(true)
    expect(rules.commit_and_environment_required).toBe(true)
    expect(rules.automated_results_do_not_satisfy_manual_gate).toBe(true)
  })

  it('binds the Manual QA agent to the same rules', () => {
    expect(manualQa).toContain('Never fabricate a screenshot')
    expect(manualQa).toContain('Never record PASS for a case that was not executed.')
    expect(manualQa).toMatch(/BLOCKED/)
    expect(manualQa).toMatch(/\*\*Modifies production code\*\* \| No/)
  })

  it('requires every field of a manual test case', () => {
    for (const field of [
      'test_case_id',
      'objective',
      'priority',
      'preconditions',
      'test_data',
      'numbered_steps',
      'expected_result',
      'actual_result',
      'verdict',
      'evidence_reference',
    ]) {
      expect(docPolicy.documentation.test_case_fields).toContain(field)
    }
  })

  it('has Test Documentation consume evidence rather than produce it', () => {
    const testDoc = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/agents/documentation/test-documentation.md'),
      'utf8',
    )
    expect(testDoc).toContain('Never write an actual result that Manual QA did not report.')
    expect(testDoc).toContain('Never generate, mock or illustrate a screenshot.')
  })
})

describe('independent review and the human gates', () => {
  it('requires independence for every review and acceptance role', () => {
    const independent = workflow.workflow.verification.independence_required
    for (const id of ['code-reviewer', 'security-reviewer', 'qa-reviewer', 'final-acceptance']) {
      expect(independent).toContain(id)
    }
    for (const id of independent) expect(AGENT_IDS).toContain(id)
  })

  it('marks the independent gates in quality-gates.yaml', () => {
    const independentGates = gates.feature_gates.filter((g) => g.independent === true)
    const owners = independentGates.map((g) => g.owner)
    expect(owners).toContain('code-reviewer')
    expect(owners).toContain('manual-qa')
    expect(owners).toContain('qa-reviewer')
    expect(owners).toContain('final-acceptance')
  })

  it('has an independent AI evaluation gate for AI features', () => {
    const ai = gates.feature_gates.find((g) => g.owner === 'ai-evaluation')
    expect(ai.independent).toBe(true)
    expect(activation.conditional.ai.agents).toContain('ai-evaluation')
  })

  it('requires all four human gates', () => {
    for (const gate of [
      'start_planner_recommended_feature',
      'material_architecture_change',
      'merge_to_protected_branch',
      'production_deployment',
    ]) {
      expect(gates.human_gates[gate].required).toBe(true)
    }
    expect(workflow.workflow.planning.human_gate).toBe('start_planner_recommended_feature')
    expect(workflow.workflow.completion.human_gates).toContain('merge_to_protected_branch')
    expect(workflow.workflow.completion.human_gates).toContain('production_deployment')
  })

  it('blocks on CRITICAL and HIGH', () => {
    expect(gates.blocking_severities).toEqual(['CRITICAL', 'HIGH'])
    expect(workflow.workflow.rework.blocking_severities).toEqual(['CRITICAL', 'HIGH'])
  })

  it('keeps the Planner unable to start its own recommendation', () => {
    const planner = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/agents/planning/product-planner.md'),
      'utf8',
    )
    expect(planner).toContain('WAITING FOR HUMAN APPROVAL')
    expect(planner).toContain('Never treat its own recommendation as an authorization.')
    expect(planner).toMatch(/\*\*Modifies production code\*\* \| No/)
  })
})

describe('the documentation policy is authoritative and resolvable', () => {
  const doc = docPolicy.documentation

  it('defines one feature documentation root', () => {
    expect(doc.root_pattern).toBe('docs/features/<feature-id>-<slug>')
  })

  it('names the six sections', () => {
    expect(Object.keys(doc.sections)).toEqual([
      'requirements',
      'design',
      'testing',
      'security',
      'documentation',
      'release',
    ])
  })

  it('points every required document at a section that exists', () => {
    const sections = Object.values(doc.sections) as string[]
    const required = [...doc.required_for_all_features, ...doc.required_for_user_facing_features]
    for (const path of required) {
      expect(sections.some((s) => path.startsWith(s)), `${path}`).toBe(true)
    }
  })

  it('maps every documented file to a template that exists', () => {
    const root = join(PRODUCT_TEMPLATE, doc.templates.root)
    for (const [target, template] of Object.entries(doc.templates.map) as Array<[string, string]>) {
      expect(existsSync(join(root, template)), `${target} -> ${template}`).toBe(true)
    }
  })

  it('has a template for every required document', () => {
    const mapped = Object.keys(doc.templates.map)
    for (const path of [...doc.required_for_all_features, ...doc.required_for_user_facing_features]) {
      if (path.endsWith('/')) continue
      expect(mapped, `${path} has no template`).toContain(path)
    }
  })

  it('ships no template that the map does not reference', () => {
    const shipped = readdirSync(join(PRODUCT_TEMPLATE, doc.templates.root)).filter(
      (f) => f !== 'README.md',
    )
    const mapped = new Set(Object.values(doc.templates.map) as string[])
    for (const file of shipped) expect(mapped, `${file} is unreferenced`).toContain(file)
  })

  it('defines one screenshot location and naming scheme', () => {
    expect(doc.screenshot_path).toBe('testing/manual/screenshots/<test-case-id>/')
    expect(doc.screenshot_naming).toBe('step-<nn>-<description>.png')
  })

  it('is the only layout the package describes', () => {
    // The V2 package shipped two incompatible layouts -- a flat one in the
    // policy and a numbered-directory one in the usage examples -- so QA
    // evidence had two homes and the evidence reviewer could find neither
    // reliably. Assert the numbered form is gone everywhere.
    const files = walk(join(PRODUCT_TEMPLATE, '.claude')).map((f) =>
      readFileSync(join(PRODUCT_TEMPLATE, '.claude', f), 'utf8'),
    )
    for (const body of files) {
      expect(body).not.toMatch(/0[1-6]-(requirements|design|testing|security|documentation|release)/)
    }
  })
})

describe('the domain framework ships contracts, not domain facts', () => {
  const domainDir = join(PRODUCT_TEMPLATE, '.claude/domain')

  it('ships only the contract, template and example', () => {
    expect(walk(domainDir).sort()).toEqual([
      'DOMAIN-AGENT-TEMPLATE.md',
      'DOMAIN-REVIEW-CONTRACT.md',
      'README.md',
      'domain-registry.example.yaml',
    ])
  })

  it('ships no product domain knowledge', () => {
    for (const file of walk(domainDir)) {
      const body = readFileSync(join(domainDir, file), 'utf8')
      for (const product of ['Docoris', 'Dianova', 'LegalApp']) {
        expect(body, `${file} names ${product}`).not.toContain(product)
      }
    }
  })

  it('keeps domain agents out of the shared registry', () => {
    for (const id of AGENT_IDS) expect(id).not.toContain('domain-expert')
    for (const a of registry.agents) expect(a.category).not.toBe('domain')
  })

  it('has no dangling reference in the example registry', () => {
    // Every path an `.example` file names is product-created by definition.
    // What must hold is that anything it points at which is NOT product-created
    // -- the contract it cites -- actually exists.
    const example = readYaml<DomainRegistryExample>(join(domainDir, 'domain-registry.example.yaml'))
    expect(existsSync(join(PRODUCT_TEMPLATE, example.domain_review.contract))).toBe(true)
    for (const agent of example.agents) {
      expect(agent.definition.startsWith('.claude/domain/')).toBe(true)
    }
  })

  it('documents which files the product must create', () => {
    const readme = readFileSync(join(domainDir, 'README.md'), 'utf8')
    expect(readme).toContain('domain-registry.yaml')
    expect(readme).toMatch(/product-created/)
    expect(readme).toMatch(/\.example/)
  })

  it('resolves the registry the product profile example points at', () => {
    const profileExample = readYaml<{ product_domain: { registry: string } }>(join(ORCHESTRATION, 'product-profile.example.yaml'))
    // Product-created, so it must not exist in the starter -- and the file
    // pointing at it must say so rather than dangle silently.
    expect(profileExample.product_domain.registry).toBe('.claude/domain/domain-registry.yaml')
    expect(existsSync(join(PRODUCT_TEMPLATE, profileExample.product_domain.registry))).toBe(false)
    const body = readFileSync(join(ORCHESTRATION, 'product-profile.example.yaml'), 'utf8')
    expect(body).toMatch(/[Pp]roduct-created/)
  })
})

describe('every orchestration file parses', () => {
  const files = walk(join(PRODUCT_TEMPLATE, '.claude'))

  it('parses every YAML file in the product .claude tree', () => {
    const yamlFiles = files.filter((f) => f.endsWith('.yaml') || f.endsWith('.yml'))
    expect(yamlFiles.length).toBeGreaterThan(0)
    for (const file of yamlFiles) {
      const body = readFileSync(join(PRODUCT_TEMPLATE, '.claude', file), 'utf8')
      expect(() => yaml.load(body), `${file}`).not.toThrow()
    }
  })

  it('parses every JSON file in the product .claude tree', () => {
    for (const file of files.filter((f) => f.endsWith('.json'))) {
      const body = readFileSync(join(PRODUCT_TEMPLATE, '.claude', file), 'utf8')
      expect(() => JSON.parse(body), `${file}`).not.toThrow()
    }
  })

  it('declares a schema_version on every orchestration config', () => {
    for (const doc of [registry, activation, workflow, gates, docPolicy]) {
      expect(doc.schema_version).toBe(1)
    }
  })

  it('leaves no unrendered Handlebars token in what a product receives', () => {
    for (const file of PRODUCT.fileList.filter((f) => f.startsWith('.claude/'))) {
      expect(PRODUCT.read(file), file).not.toMatch(/\{\{[a-zA-Z]/)
    }
  })
})

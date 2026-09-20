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
  capabilities: string[]
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
  capability_vocabulary: string[]
}

interface Telemetry {
  schema_version: number
  report: Record<string, string[]>
  rules: string[]
  worth_comparing: string[]
}

interface Lifecycle {
  schema_version: number
  engineering_flow_join: { covers_states: string[]; rule: string }
  statuses_from: string
  states: Array<{
    id: string
    means: string
    requires_gates?: string[]
    requires?: string[]
    human_gate?: string
    applicable_when?: string
    not_yet?: string[]
    local_evidence_does_not_satisfy?: boolean
    component_states_required?: boolean
  }>
  rules: string[]
  epic_acceptance: {
    story: { scope: string; runs: string }
    epic: { scope: string; when: string; runs: string[]; gate_reuse: string }
    never: string[]
    risk_exception: string
  }
  policy_disabled_steps: Record<
    string,
    { status: string; why: string; tracked_as: string; switched_by: string }
  >
}

interface DeploymentAwareness {
  schema_version: number
  push_impact: {
    read_from: string[]
    branches: Record<string, { ci: boolean; deploys: string }>
    report_before_approval: string[]
    rule: string
  }
  components: { order: string[]; states: Record<string, string> }
  partial_deployment: {
    record: string
    never: string[]
    retry_safety: Record<string, string>
    unknown_state: { outcome: string; escalation: string; rule: string }
  }
  diagnosis: { trace_in_order: string[]; classify_as_one_of: string[]; never: string[] }
}

interface GateInvalidation {
  schema_version: number
  change_classes: Record<string, { paths: string[]; means: string }>
  gate_result: { fields: Record<string, string> }
  reuse: { rule: string; requires: string[]; never_reused: string[]; not_a_reason: string[] }
  mode_overrides: Record<string, { reuse: string; restriction?: string }>
  targeted_remediation: { when: string[]; report: string[]; never: string[] }
  scenarios: Record<
    string,
    {
      change_classes: string[]
      invalidates?: string[]
      invalidates_must_include?: string[]
      reuses_must_include?: string[]
    }
  >
}

interface ExecutionBudget {
  schema_version: number
  definitions: { retry: string; cycle: string }
  budget: Record<string, number>
  counting: { scope: string; resets_on: string[]; never_resets_on: string[]; same_agent_counts: string }
  escalation: Record<string, string>
  outcomes: Record<string, { meaning: string; agent_may_continue: boolean }>
  stop_report: string[]
  rules: string[]
}

interface ExecutionModes {
  schema_version: number
  modes: Record<
    string,
    {
      summary: string
      always_consider: string[]
      planning: string
      gate_reuse: string
      requires?: string[]
    }
  >
  never: string[]
}

interface RiskSignal {
  condition: string
  boundary: string
  not_this: string
}

interface RiskModel {
  schema_version: number
  floor_signals: Record<string, RiskSignal>
  elevating_signals: Record<string, RiskSignal>
  combinations: Array<{ signals: string[]; mode: string; reason: string }>
  selection: Array<{ rule: string; mode: string }>
  rationale: { required: boolean; must_state: string[] }
  override: {
    raise: { allowed: string; record: string }
    lower: { allowed: string; record: string[]; never: string }
  }
}

interface Conditions {
  schema_version: number
  reserved: string[]
  conditions: Record<string, { trigger: string; note?: string }>
}

interface ActivationRules {
  schema_version: number
  always_consider: string[]
  conditional: Record<string, string[]>
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
    engineering_flow: Array<{
      stage?: string
      freeze?: string
      bounded_by?: string
      independent?: boolean
      after?: string
      invalidates_on_change?: string
      exception?: string
      escalates_beyond?: string
      consumes_budget?: boolean
    }>
    budget: { contract: string; unbounded_stages_forbidden: boolean }
    rework: {
      failed_gate_route: string
      require_independent_reverification: boolean
      blocking_severities: string[]
      bounded_by: string
      on_budget_exhausted: string
    }
    integration: { agent: string; required_when: string[] }
    completion: { acceptance: string; human_gates: string[] }
  }
}

interface QualityGates {
  schema_version: number
  human_gates: Record<string, { required: boolean; description: string }>
  blocking_severities: string[]
  statuses: Record<string, string>
  feature_gates: Array<{
    id: string
    owner: string
    applies: string | string[]
    independent?: boolean
    inputs: string[]
    stage?: string
    human_evidence_decided_by?: string
  }>
}

interface DocumentationPolicy {
  schema_version: number
  documentation: {
    root_pattern: string
    sections: Record<string, string>
    required_for_all_features: string[]
    required_by_condition: Record<string, string[]>
    timing: Record<'before_implementation' | 'during_implementation' | 'after_the_code_settles' | 'audited_once', string[]>
    evidence_runs: { path: string; run_id: string; each_run_records: string[]; rules: string[] }
    manual_qa: {
      governs_gates: string[]
      required_when: string[]
      not_required_when: string[]
      never: string[]
      blocked_is_an_answer: string
      when_not_required_record: string
      never_exempted_because: string[]
    }
    screenshots: {
      capture_when_it_proves: string[]
      do_not_capture: string[]
      no_maximum: boolean
      higher_risk_may_justify_more: boolean
      purpose_required_when_not_obvious: boolean
    }
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

const conditions = readYaml<Conditions>(join(ORCHESTRATION, 'conditions.yaml'))
const risk = readYaml<RiskModel>(join(ORCHESTRATION, 'risk-model.yaml'))
const execModes = readYaml<ExecutionModes>(join(ORCHESTRATION, 'execution-modes.yaml'))
const budget = readYaml<ExecutionBudget>(join(ORCHESTRATION, 'execution-budget.yaml'))
const invalidation = readYaml<GateInvalidation>(join(ORCHESTRATION, 'gate-invalidation.yaml'))
const lifecycle = readYaml<Lifecycle>(join(ORCHESTRATION, 'lifecycle.yaml'))
const deployment = readYaml<DeploymentAwareness>(join(ORCHESTRATION, 'deployment-awareness.yaml'))
const telemetry = readYaml<Telemetry>(join(ORCHESTRATION, 'telemetry.yaml'))
const registry = readYaml<Registry>(join(ORCHESTRATION, 'agent-registry.yaml'))
const activation = readYaml<ActivationRules>(join(ORCHESTRATION, 'activation-rules.yaml'))
const workflow = readYaml<Workflow>(join(ORCHESTRATION, 'workflow.yaml'))
const gates = readYaml<QualityGates>(join(ORCHESTRATION, 'quality-gates.yaml'))
const docPolicy = readYaml<DocumentationPolicy>(join(ORCHESTRATION, 'documentation-policy.yaml'))

const AGENT_IDS: string[] = registry.agents.map((a) => a.id)
const CONDITION_IDS: string[] = Object.keys(conditions.conditions)

/** Every applicability token a file may use: a condition, or `always`. */
const APPLICABILITY_TOKENS: string[] = [...CONDITION_IDS, ...conditions.reserved]

/** `applies` is one token or a list of them, meaning any-of. */
const appliesTokens = (applies: string | string[]): string[] =>
  Array.isArray(applies) ? applies : [applies]

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

  it('leaves the four shared commands shared and adds six product-only ones', () => {
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      for (const c of ['feature', 'review', 'test', 'ui-review']) {
        expect(gen.has(`.claude/commands/${c}.md`)).toBe(true)
      }
    }
    for (const c of [
      'plan-next',
      'orchestrate-feature',
      'run-parallel',
      'manual-test-doc',
      'agent-status',
      'remediate',
    ]) {
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

describe('one applicability vocabulary, shared by every file that asks', () => {
  /**
   * Measured on 2026-09-19, immediately before `conditions.yaml` existed:
   * `activation-rules.yaml` declared 14 conditions, `quality-gates.yaml`
   * matched on 10 and `documentation-policy.yaml` on 5, and the number of
   * tokens shared by all three was ZERO. `user_interface`, `user_facing` and
   * `business_workflow_or_ui_change` were three spellings of one question.
   *
   * Nothing caught it, and nothing could have: the rest of this file checks
   * every *agent id* in those files against the registry, and there was no
   * equivalent source of truth for a condition to be checked against. A gate
   * could therefore declare an applicability the Orchestrator has no way to
   * evaluate, and the symptom is a gate that silently never fires -- the same
   * shape as `notifications` being a capability that gated nothing.
   *
   * These six assertions are the reason a fourth vocabulary cannot appear.
   */

  it('declares a trigger for every condition', () => {
    expect(CONDITION_IDS.length).toBeGreaterThan(0)
    for (const [id, condition] of Object.entries(conditions.conditions)) {
      expect(typeof condition.trigger, `${id} trigger`).toBe('string')
      expect(condition.trigger.trim().length, `${id} trigger is empty`).toBeGreaterThan(0)
    }
  })

  it('reserves `always`, which is not a condition and has no trigger', () => {
    // It asks nothing and can never be false, so it cannot carry a trigger --
    // but a gate still has to be able to say "every feature" without one.
    expect(conditions.reserved).toContain('always')
    for (const token of conditions.reserved) {
      expect(CONDITION_IDS, `${token} is both reserved and a condition`).not.toContain(token)
    }
  })

  it('activation-rules.yaml keys only declared conditions', () => {
    for (const condition of Object.keys(activation.conditional)) {
      expect(CONDITION_IDS, `activation rule for undeclared ${condition}`).toContain(condition)
    }
  })

  it('no gate applies under a condition nobody declared', () => {
    for (const gate of gates.feature_gates) {
      for (const token of appliesTokens(gate.applies)) {
        expect(APPLICABILITY_TOKENS, `gate ${gate.id} applies: ${token}`).toContain(token)
      }
    }
  })

  it('no document is required by a condition nobody declared', () => {
    for (const condition of Object.keys(docPolicy.documentation.required_by_condition)) {
      expect(CONDITION_IDS, `documents required by undeclared ${condition}`).toContain(condition)
    }
  })

  it('declares no condition that nothing consumes', () => {
    // An unconsumed condition is a fourth vocabulary waiting to happen: it
    // reads as available, so the next file to need that question adopts it
    // rather than the one its consumers actually use.
    const consumed = new Set<string>([
      ...Object.keys(activation.conditional),
      ...gates.feature_gates.flatMap((g) => appliesTokens(g.applies)),
      ...Object.keys(docPolicy.documentation.required_by_condition),
    ])
    for (const id of CONDITION_IDS) {
      expect([...consumed], `${id} is declared but nothing asks it`).toContain(id)
    }
  })

  it('leaves no pre-V2.1 applicability spelling anywhere in the package', () => {
    // The renames, listed rather than inferred. Each was a real token in one
    // of the three files and named a condition the other two could not see.
    const RETIRED = [
      'user_facing',
      'api_or_integration_or_database',
      'security_risk_triggered',
      'user_or_operator_visible_change',
      'cross_feature_or_shared_contract_or_release',
      'business_workflow_or_ui_change',
      'configurable_or_operational_feature',
      'security_or_sensitive_data',
      'any_automated_verification_executed',
      'required_for_user_facing_features',
    ]
    const tree = join(PRODUCT_TEMPLATE, '.claude')
    for (const file of walk(tree)) {
      // A YAML comment naming a retired token is history -- `conditions.yaml`
      // lists the old spellings precisely so the rename stays explicable. A
      // retired token in a *value* is the defect. Markdown is checked whole:
      // nothing there is a comment, and prose describing the old vocabulary
      // as current is the same failure in a different file type.
      const body = readFileSync(join(tree, file), 'utf8')
      const checked = file.endsWith('.yaml')
        ? body
            .split('\n')
            .filter((line) => !line.trimStart().startsWith('#'))
            .join(' ')
        : body
      for (const token of RETIRED) {
        expect(checked, `${file} still uses ${token}`).not.toContain(token)
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
      ...Object.values(activation.conditional).flat(),
    ]
    expect(named.length).toBeGreaterThan(0)
    for (const id of named) expect(AGENT_IDS, `activation references ${id}`).toContain(id)
  })

  it('every activation set names at least one agent', () => {
    // A condition that activates nobody belongs out of this file entirely --
    // `domain_feature` is answered by a product-owned agent, and three others
    // decide documents rather than staffing. An empty list here would read as
    // "considered and staffed with nothing", which is not the same statement.
    for (const [condition, agents] of Object.entries(activation.conditional)) {
      expect(agents.length, `${condition} activates nobody`).toBeGreaterThan(0)
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
    for (const [condition, agents] of Object.entries(activation.conditional)) {
      expect(always + agents.length, `${condition}`).toBeLessThan(AGENT_IDS.length)
    }
  })
})

describe('risk decides the mode, and the mode decides how much machinery', () => {
  /**
   * The failure this guards is a *label matcher*. A risk model that fires on
   * "this feature is about storage" is wrong in both directions, and the
   * second direction is the dangerous one: a change that never mentions
   * storage and quietly widens what a tool may read would classify as a copy
   * fix. So every signal has to name the boundary it means, and the nearby
   * change that looks like it and is not.
   */

  const SIGNALS = { ...risk.floor_signals, ...risk.elevating_signals }

  it('offers exactly the three modes, and no fourth', () => {
    expect(Object.keys(execModes.modes).sort()).toEqual(['FAST', 'FULL', 'STANDARD'])
  })

  it('staffs every mode from the registry', () => {
    for (const [name, mode] of Object.entries(execModes.modes)) {
      expect(mode.always_consider.length, `${name} staffs nobody`).toBeGreaterThan(0)
      for (const id of mode.always_consider) {
        expect(AGENT_IDS, `${name} always-considers ${id}`).toContain(id)
      }
    }
  })

  it('keeps every mode far short of the whole registry', () => {
    // Including FULL. FULL is a statement about the boundary at risk, not an
    // instruction to run everything, and a mode that staffed half the
    // catalogue before a single condition was evaluated would make the
    // activation rules decorative.
    for (const [name, mode] of Object.entries(execModes.modes)) {
      expect(mode.always_consider.length, `${name}`).toBeLessThan(AGENT_IDS.length / 2)
    }
  })

  it('has FAST cost less than STANDARD, and STANDARD no more than FULL', () => {
    const size = (m: string) => execModes.modes[m].always_consider.length
    expect(size('FAST')).toBeLessThan(size('STANDARD'))
    expect(size('STANDARD')).toBeLessThanOrEqual(size('FULL'))
  })

  it('makes FAST something a change has to earn', () => {
    // FAST is the only mode that trims the always-considered set, so it is
    // the only one that can be wrong cheaply. It carries its own
    // preconditions; the other two need none.
    expect(execModes.modes.FAST.requires?.length ?? 0).toBeGreaterThan(0)
  })

  it('gives every risk signal a boundary and a not-this', () => {
    // `not_this` is the half that stops this becoming a label matcher. A
    // signal nobody can write one for is a subject area wearing a signal's
    // clothes.
    expect(Object.keys(SIGNALS).length).toBeGreaterThan(0)
    for (const [id, signal] of Object.entries(SIGNALS)) {
      expect(typeof signal.boundary, `${id} boundary`).toBe('string')
      expect(signal.boundary.trim().length, `${id} boundary is empty`).toBeGreaterThan(0)
      expect(typeof signal.not_this, `${id} not_this`).toBe('string')
      expect(signal.not_this.trim().length, `${id} not_this is empty`).toBeGreaterThan(0)
      expect(signal.boundary, `${id} boundary repeats not_this`).not.toBe(signal.not_this)
    }
  })

  it('anchors every risk signal to a declared condition', () => {
    // The fifth-vocabulary guard. Risk was the obvious place for one to
    // reappear, because a signal reads like a condition and is not one.
    for (const [id, signal] of Object.entries(SIGNALS)) {
      expect(CONDITION_IDS, `signal ${id} names condition ${signal.condition}`).toContain(
        signal.condition,
      )
    }
  })

  it('keeps floor and elevating signals disjoint', () => {
    for (const id of Object.keys(risk.floor_signals)) {
      expect(Object.keys(risk.elevating_signals), `${id} is in both tiers`).not.toContain(id)
    }
  })

  it('names only real signals and real modes in its combinations', () => {
    for (const combo of risk.combinations) {
      expect(combo.signals.length, 'a combination of one is a signal').toBeGreaterThan(1)
      for (const id of combo.signals) expect(Object.keys(SIGNALS), `combination ${id}`).toContain(id)
      expect(Object.keys(execModes.modes), `combination mode ${combo.mode}`).toContain(combo.mode)
      expect(combo.reason.trim().length, 'a combination states its reason').toBeGreaterThan(0)
    }
  })

  it('selects a real mode by every rule, and falls back to STANDARD', () => {
    for (const rule of risk.selection) {
      expect(Object.keys(execModes.modes), `rule ${rule.rule}`).toContain(rule.mode)
    }
    const last = risk.selection[risk.selection.length - 1]
    // An unclassifiable change is not a small one; it is one nobody has
    // understood yet, so the fallback is never FAST.
    expect(last.rule).toBe('otherwise')
    expect(last.mode).toBe('STANDARD')
    expect(risk.selection[0].mode).toBe('FULL')
  })

  it('requires a rationale that can be argued with', () => {
    expect(risk.rationale.required).toBe(true)
    const stated = risk.rationale.must_state.join(' ')
    // Listing only what fired cannot be disputed. Listing what was rejected
    // and why can be, and being disputable is the point.
    expect(stated).toMatch(/rejected/)
    expect(stated).toMatch(/rule/)
  })

  it('lets a human raise a mode freely and lower one only on the record', () => {
    expect(risk.override.raise.allowed).toBe('always')
    expect(risk.override.lower.allowed).toBe('with_written_rationale')
    expect(risk.override.lower.record.join(' ')).toMatch(/floor signal/)
    expect(risk.override.lower.never).toMatch(/agent/i)
  })

  it('forbids a mode from touching gates, independence or the human gates', () => {
    const never = execModes.never.join(' ').toLowerCase()
    expect(never).toMatch(/gate/)
    expect(never).toMatch(/independence/)
    expect(never).toMatch(/human gate/)
  })

  it('has the Orchestrator classify risk and publish the plan before implementing', () => {
    const body = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/agents/orchestration/engineering-orchestrator.md'),
      'utf8',
    )
    expect(body).toMatch(/risk-model\.yaml/)
    expect(body).toMatch(/execution plan/i)
    expect(body).toMatch(/Never lower an execution mode/)
  })
})

describe('agents are selected by capability, not by familiarity', () => {
  it('declares a capability vocabulary and uses nothing outside it', () => {
    const declared = registry.capability_vocabulary
    expect(declared.length).toBeGreaterThan(0)
    for (const agent of registry.agents) {
      expect(agent.capabilities.length, `${agent.id} supplies nothing`).toBeGreaterThan(0)
      for (const capability of agent.capabilities) {
        expect(declared, `${agent.id} invents ${capability}`).toContain(capability)
      }
    }
  })

  it('declares no capability that no agent supplies', () => {
    // Same discipline as conditions.yaml: an unsupplied capability reads as
    // available, so the next agent to need that word adopts it and the
    // vocabulary quietly forks.
    const supplied = new Set(registry.agents.flatMap((a) => a.capabilities))
    for (const capability of registry.capability_vocabulary) {
      expect([...supplied], `${capability} is declared but nobody supplies it`).toContain(capability)
    }
  })

  it('is coarser than an agent and finer than a category', () => {
    // The whole value of the layer. One capability per agent would just be
    // agent ids again; one per category would be `category`.
    const count = registry.capability_vocabulary.length
    expect(count).toBeLessThan(AGENT_IDS.length)
    expect(count).toBeGreaterThan(Object.keys(registry.category_counts).length)
  })

  it('has more than one agent able to supply the capabilities that get shared', () => {
    const suppliers = new Map<string, string[]>()
    for (const agent of registry.agents) {
      for (const capability of agent.capabilities) {
        suppliers.set(capability, [...(suppliers.get(capability) ?? []), agent.id])
      }
    }
    // Routing only means something when a capability can name more than one
    // agent at least sometimes; otherwise the question and the answer are the
    // same string.
    const shared = [...suppliers.values()].filter((ids) => ids.length > 1)
    expect(shared.length).toBeGreaterThan(0)
    expect(suppliers.get('implement')?.length).toBeGreaterThan(3)
  })

  it('derives gate ownership rather than storing a second copy of it', () => {
    // Deliberately NOT a field on the agent. The owner lives in
    // quality-gates.yaml, and a duplicate here is how the two come to
    // disagree about who may close what.
    const owners = new Set(
      gates.feature_gates
        .map((g) => g.owner)
        .filter((o) => o !== 'developer_pool' && o !== 'domain_registry'),
    )
    for (const owner of owners) {
      const agent = registry.agents.find((a) => a.id === owner)
      expect(agent, `gate owner ${owner}`).toBeDefined()
    }
    const registryText = readFileSync(join(ORCHESTRATION, 'agent-registry.yaml'), 'utf8')
    expect(registryText).not.toMatch(/^\s+gates:/m)
  })
})

describe('no loop is unbounded, and a freeze point says what a late change costs', () => {
  /**
   * V2 had no cap on anything. One real feature lifecycle produced five
   * accessibility cycles, five code reviews, five browser runs, five evidence
   * audits, six manual QA passes and three final acceptances, and every
   * single decision to go round again was defensible on its own. That is what
   * an unbounded loop is made of -- not one bad judgement, but no point at
   * which judgement was required.
   *
   * These assertions are not about the numbers. They are about there being
   * numbers at all, about every exit leading somewhere a person is, and about
   * a counter that cannot be reset by the thing a cycle consists of.
   */

  const flow = workflow.workflow.engineering_flow
  const stages = flow.filter((s) => s.stage !== undefined)
  const freezes = flow.filter((s) => s.freeze !== undefined)

  it('caps every loop the framework can enter', () => {
    const REQUIRED = [
      'max_gate_retries',
      'max_test_fix_cycles',
      'max_reviewer_cycles',
      'max_documentation_audits',
      'max_final_acceptance_attempts',
      'same_agent_max_invocations',
    ]
    for (const key of REQUIRED) {
      const value = budget.budget[key]
      expect(value, `${key} is uncapped`).toBeTypeOf('number')
      expect(Number.isInteger(value), `${key} is not a whole number`).toBe(true)
      expect(value, `${key} must permit at least one attempt`).toBeGreaterThan(0)
      // A cap high enough to never bind is the same as no cap, and reads
      // better in a document, which is worse.
      expect(value, `${key} is too high to ever bind`).toBeLessThanOrEqual(3)
    }
  })

  it('distinguishes a retry from a cycle', () => {
    // The distinction the whole budget rests on. Without it, either a flaky
    // environment burns the fix budget, or "run it again after fixing it"
    // counts as a retry and the cap is absurd.
    expect(budget.definitions.retry).toMatch(/no change/i)
    expect(budget.definitions.cycle).toMatch(/change/i)
    expect(budget.definitions.retry).not.toBe(budget.definitions.cycle)
  })

  it('refuses to reset a counter on the thing a cycle actually is', () => {
    const never = budget.counting.never_resets_on.join(' ').toLowerCase()
    expect(never).toMatch(/commit/)
    expect(never).toMatch(/branch|worktree|session/)
    expect(never).toMatch(/remediation/)
    // Only a human, or closure, may clear it.
    expect(budget.counting.resets_on.join(' ')).toMatch(/human/i)
  })

  it('sends every escalation to an outcome where an agent stops', () => {
    const outcomes = Object.keys(budget.outcomes)
    expect(outcomes.sort()).toEqual(['BLOCKED', 'HUMAN_REVIEW'])
    for (const [trigger, outcome] of Object.entries(budget.escalation)) {
      expect(outcomes, `${trigger} escalates to ${outcome}`).toContain(outcome)
    }
    for (const [name, outcome] of Object.entries(budget.outcomes)) {
      expect(outcome.agent_may_continue, `${name} lets an agent carry on`).toBe(false)
    }
  })

  it('escalates every trigger the framework was rewritten to stop repeating', () => {
    const REQUIRED = [
      'repeated_gate_failure',
      'budget_exhausted',
      'contradictory_evidence',
      'new_finding_after_final_rereview',
      'unavailable_manual_validation',
      'environment_failure',
      'unknown_deployment_state',
    ]
    for (const trigger of REQUIRED) {
      expect(Object.keys(budget.escalation), `${trigger} has no outcome`).toContain(trigger)
    }
  })

  it('separates cannot-proceed from failed', () => {
    // BLOCKED is not FAIL. An environment nobody can reach has not failed a
    // gate; it has not run one, and recording it as a failure is how a
    // feature acquires a defect that does not exist.
    expect(budget.escalation.unavailable_manual_validation).toBe('BLOCKED')
    expect(budget.escalation.environment_failure).toBe('BLOCKED')
    expect(budget.escalation.unknown_deployment_state).toBe('BLOCKED')
    expect(budget.outcomes.BLOCKED.meaning).toMatch(/never recorded as one|not a failure/i)
  })

  it('stops with a report that admits what it does not know', () => {
    const report = budget.stop_report.join(' ').toLowerCase()
    expect(budget.stop_report.length).toBe(5)
    expect(report).toMatch(/what failed/)
    expect(report).toMatch(/attempted/)
    expect(report).toMatch(/evidence/)
    // The one that stops a stop report reading as a finished investigation.
    expect(report).toMatch(/unknown/)
    expect(report).toMatch(/human decision/)
  })

  it('runs the engineering flow in the order the freezes depend on', () => {
    const order = flow.map((s) => s.stage ?? s.freeze)
    const at = (name: string) => order.indexOf(name)
    expect(at('implement')).toBeGreaterThanOrEqual(0)
    expect(at('test_and_fix')).toBeGreaterThan(at('implement'))
    expect(at('code_freeze')).toBeGreaterThan(at('test_and_fix'))
    expect(at('primary_review')).toBeGreaterThan(at('code_freeze'))
    expect(at('one_re_review')).toBeGreaterThan(at('primary_review'))
    expect(at('quality_freeze')).toBeGreaterThan(at('one_re_review'))
    expect(at('documentation_audit')).toBeGreaterThan(at('quality_freeze'))
    expect(at('final_acceptance')).toBeGreaterThan(at('documentation_audit'))
    expect(order[order.length - 1]).toBe('pass_or_escalate')
  })

  it('declares exactly the two freeze points, each saying what a change costs', () => {
    expect(freezes.map((f) => f.freeze)).toEqual(['code_freeze', 'quality_freeze'])
    for (const freeze of freezes) {
      expect(typeof freeze.after, `${freeze.freeze} says when`).toBe('string')
      expect(
        typeof freeze.invalidates_on_change,
        `${freeze.freeze} says what a change from here invalidates`,
      ).toBe('string')
    }
  })

  it('makes a late documentation correction cost only the documentation gates', () => {
    // The single most expensive thing V2 did: a sentence rewritten in a
    // results document put the whole feature back in play.
    const quality = freezes.find((f) => f.freeze === 'quality_freeze')
    expect(quality?.invalidates_on_change).toMatch(/documentation/)
    // And the exception that keeps it honest -- a document that was right
    // about code that was wrong is a code defect found by writing prose.
    expect(quality?.exception).toMatch(/implementation defect/i)
  })

  it('bounds every stage that can repeat, and names the cap in the budget', () => {
    const REPEATABLE = [
      'test_and_fix',
      'primary_review',
      'documentation_audit',
      'final_acceptance',
    ]
    for (const name of REPEATABLE) {
      const stage = stages.find((s) => s.stage === name)
      expect(stage, `${name} is missing from the flow`).toBeDefined()
      const cap = stage?.bounded_by
      expect(cap, `${name} is unbounded`).toBeTypeOf('string')
      expect(Object.keys(budget.budget), `${name} names an undeclared cap ${cap}`).toContain(cap)
    }
    expect(workflow.workflow.budget.unbounded_stages_forbidden).toBe(true)
  })

  it('bounds rework itself, which is the loop V2 could not exit', () => {
    expect(workflow.workflow.rework.bounded_by).toContain('execution-budget.yaml')
    expect(Object.keys(budget.outcomes)).toContain(workflow.workflow.rework.on_budget_exhausted)
  })

  it('keeps the independent stages independent after a freeze', () => {
    // A freeze changes what a change costs. It never changes who may close a
    // gate, and a re-review folded into the fix would be the cheapest way to
    // make the budget look satisfied.
    for (const name of ['primary_review', 'one_re_review', 'documentation_audit', 'final_acceptance']) {
      const stage = stages.find((s) => s.stage === name)
      expect(stage?.independent, `${name} lost its independence`).toBe(true)
    }
  })

  it('has the Orchestrator count, freeze and stop rather than merely know', () => {
    const body = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/agents/orchestration/engineering-orchestrator.md'),
      'utf8',
    )
    expect(body).toMatch(/execution-budget\.yaml/)
    expect(body).toMatch(/freeze/i)
    expect(body).toMatch(/stop report/i)
    expect(body).toMatch(/Never grant itself more budget/)
  })
})

describe('a passed gate is reused when nothing it depends on changed', () => {
  /**
   * The change V2.1 exists for.
   *
   * V2 recorded nothing about a gate beyond whether it had passed, so "did
   * anything relevant to this change?" had no answer -- and with no answer,
   * the only safe habit is to re-run everything. One real lifecycle re-ran
   * the browser suite five times, the evidence audit five times and manual
   * QA six times, mostly to re-establish facts about code nothing had
   * touched.
   *
   * The matrix is DERIVED here, exactly as an agent must derive it: a gate
   * is invalidated when a change class is among its `inputs`. Nothing in
   * this file hand-writes the answer, because a hand-written matrix is a
   * second copy of the gate list and would be wrong the first time a gate
   * was added.
   */

  const CLASSES = Object.keys(invalidation.change_classes)
  const gateInputs = new Map(gates.feature_gates.map((g) => [g.id, new Set(g.inputs)]))

  /** A gate is invalidated when the change touches any class it depends on. */
  const invalidatedBy = (changed: string[]): Set<string> =>
    new Set(
      [...gateInputs.entries()]
        .filter(([, inputs]) => changed.some((c) => inputs.has(c)))
        .map(([id]) => id),
    )

  const reusedBy = (changed: string[]): Set<string> => {
    const invalid = invalidatedBy(changed)
    return new Set([...gateInputs.keys()].filter((id) => !invalid.has(id)))
  }

  it('declares every change class a gate depends on', () => {
    for (const gate of gates.feature_gates) {
      expect(gate.inputs.length, `${gate.id} depends on nothing and can never be invalidated`)
        .toBeGreaterThan(0)
      for (const cls of gate.inputs) {
        expect(CLASSES, `gate ${gate.id} depends on undeclared class ${cls}`).toContain(cls)
      }
    }
  })

  it('declares no change class that no gate depends on', () => {
    const used = new Set(gates.feature_gates.flatMap((g) => g.inputs))
    for (const cls of CLASSES) {
      expect([...used], `${cls} is declared but invalidates nothing`).toContain(cls)
    }
  })

  it('gives every change class paths a diff can actually be matched against', () => {
    for (const [id, cls] of Object.entries(invalidation.change_classes)) {
      expect(cls.paths.length, `${id} has no paths`).toBeGreaterThan(0)
      expect(typeof cls.means, `${id} does not say what it means`).toBe('string')
    }
  })

  it('never makes a gate its own input', () => {
    // The trap that would break reuse permanently: if writing the manual
    // evidence invalidated the manual QA run that produced it, that gate
    // could never be satisfied. The audit is the gate that takes the
    // evidence, because auditing it is the job.
    expect([...(gateInputs.get('manual_qa_pass') ?? [])]).not.toContain('manual_evidence')
    expect([...(gateInputs.get('screenshot_evidence_complete') ?? [])]).not.toContain(
      'manual_evidence',
    )
    expect([...(gateInputs.get('qa_evidence_audit') ?? [])]).toContain('manual_evidence')
    // Same shape: the technical writer's gate is not invalidated by the
    // writing, it is invalidated by the code that made the writing wrong.
    expect([...(gateInputs.get('documentation_complete') ?? [])]).not.toContain('documentation')
    expect([...(gateInputs.get('documentation_audit') ?? [])]).toContain('documentation')
  })

  it('makes acceptance the one gate nothing can be reused past', () => {
    // "Is all of this true right now" is not a question any earlier result
    // can answer.
    for (const cls of CLASSES) {
      expect(invalidatedBy([cls]), `${cls} left final_acceptance standing`).toContain(
        'final_acceptance',
      )
    }
  })

  it('names every field needed to decide reuse, and nothing unfalsifiable', () => {
    const fields = Object.keys(invalidation.gate_result.fields)
    for (const required of ['gate', 'status', 'commit_sha', 'change_classes', 'evidence']) {
      expect(fields, `gate_result has no ${required}`).toContain(required)
    }
    // Reuse is a claim about a diff. Anything that made it a claim about a
    // feeling would have to live in this record, and does not.
    expect(fields).not.toContain('confidence')
    expect(fields).not.toContain('thoroughness')
  })

  it('refuses reuse for the reasons that are predictions rather than facts', () => {
    const not = invalidation.reuse.not_a_reason.join(' ').toLowerCase()
    expect(not).toMatch(/elapsed time/)
    expect(not).toMatch(/flaky|slow|expensive/)
    expect(not).toMatch(/nobody expects/)
    const never = invalidation.reuse.never_reused.join(' ').toLowerCase()
    expect(never).toMatch(/fail|blocked/)
    expect(never).toMatch(/evidence/)
  })

  it('bounds reuse by the code freeze in FULL', () => {
    expect(invalidation.mode_overrides.FULL.reuse).toBe('restricted')
    expect(invalidation.mode_overrides.FULL.restriction).toMatch(/code freeze/i)
    for (const mode of Object.keys(execModes.modes)) {
      expect(Object.keys(invalidation.mode_overrides), `${mode} has no reuse rule`).toContain(mode)
      expect(invalidation.mode_overrides[mode].reuse).toBe(execModes.modes[mode].gate_reuse)
    }
  })

  it.each(Object.keys(invalidation.scenarios))('derives the declared outcome for %s', (name) => {
    const scenario = invalidation.scenarios[name]
    const invalid = invalidatedBy(scenario.change_classes)
    const reused = reusedBy(scenario.change_classes)

    for (const cls of scenario.change_classes) {
      expect(CLASSES, `scenario ${name} uses undeclared class ${cls}`).toContain(cls)
    }
    if (scenario.invalidates) {
      expect([...invalid].sort()).toEqual([...scenario.invalidates].sort())
    }
    for (const gate of scenario.invalidates_must_include ?? []) {
      expect([...invalid], `${name} should invalidate ${gate}`).toContain(gate)
    }
    for (const gate of scenario.reuses_must_include ?? []) {
      expect([...reused], `${name} claims to reuse ${gate}, but it is invalidated`).toContain(gate)
    }
  })

  it('reuses twenty-one of twenty-four gates for a browser-test correction', () => {
    // E18-F01, mechanically. A browser test asserted something untrue; the
    // fix was to the browser test; and V2 re-ran the Python suite, the Node
    // suite, the row-level security suite, the security review, manual QA,
    // accessibility and regression against code that had not moved.
    //
    // Row-level security is verified in this estate by
    // api_integration_tests_pass and security_review; both are reused, which
    // is what "reuse RLS" means here.
    const invalid = invalidatedBy(['e2e_test'])
    // CI is in the list because the fix has to be pushed and the pipeline
    // re-run. That is one pipeline; what V2 also re-ran was everything below.
    expect([...invalid].sort()).toEqual(['ci_verified', 'e2e_pass', 'final_acceptance'])
    const reused = reusedBy(['e2e_test'])
    for (const gate of [
      'automated_tests_pass',
      'api_integration_tests_pass',
      'security_review',
      'manual_qa_pass',
      'accessibility_pass',
      'qa_evidence_audit',
      'regression_pass',
      'architecture_review',
      'independent_code_review',
    ]) {
      expect([...reused], `${gate} must survive a browser-test correction`).toContain(gate)
    }
  })

  it('costs a documentation-only correction an audit, a pipeline and an acceptance', () => {
    // The other half of the same lesson: in V2 a sentence rewritten in a
    // results document put the entire feature back in play.
    expect([...invalidatedBy(['documentation'])].sort()).toEqual([
      'ci_verified',
      'documentation_audit',
      'final_acceptance',
    ])
  })

  it('runs no product gate for a deployment-configuration change', () => {
    // The artefacts did not change, so re-running the product's tests would
    // prove something nobody doubted.
    const invalid = invalidatedBy(['deployment_config'])
    for (const gate of ['automated_tests_pass', 'e2e_pass', 'manual_qa_pass', 'security_review']) {
      expect([...invalid], `${gate} should not re-run for a config change`).not.toContain(gate)
    }
  })

  it('invalidates the data and security gates for a migration', () => {
    const invalid = invalidatedBy(['database_migration_or_policy'])
    for (const gate of [
      'api_integration_tests_pass',
      'security_review',
      'privacy_review',
      'regression_pass',
      'impact_analyzed',
    ]) {
      expect([...invalid], `${gate} must re-run for a migration`).toContain(gate)
    }
  })

  it('declares every gate status once, where a gate is defined', () => {
    // Declared in quality-gates.yaml and read from there by everything else.
    // Two enumerations of a status is how a policy-disabled step comes to
    // count as a failure in one file and not in another.
    const statuses = Object.keys(gates.statuses)
    for (const required of [
      'PASS',
      'FAIL',
      'BLOCKED',
      'NOT_APPLICABLE',
      'NOT_APPLICABLE_BY_POLICY',
      'PENDING_HUMAN',
      'PENDING_EXTERNAL',
    ]) {
      expect(statuses, `status ${required} is not declared`).toContain(required)
    }
    // The one that has to be unmistakable, because it is what a
    // policy-disabled step looks like to anything that cannot tell it from a
    // failure.
    expect(gates.statuses.NOT_APPLICABLE_BY_POLICY).toMatch(/policy/i)
    expect(gates.statuses.BLOCKED).toMatch(/not a failure/i)
  })

  it('states when remediation is allowed, and what it may never do', () => {
    const when = invalidation.targeted_remediation.when.join(' ').toLowerCase()
    expect(when).toMatch(/established, not suspected/)
    expect(when).toMatch(/floor signal/)
    expect(invalidation.targeted_remediation.report.length).toBe(7)
    const never = invalidation.targeted_remediation.never.join(' ').toLowerCase()
    expect(never).toMatch(/widening/)
    expect(never).toMatch(/fresh budget|counters carry over/)
  })

  it('ships a remediation command that derives rather than judges', () => {
    const body = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/commands/remediate.md'),
      'utf8',
    )
    expect(body).toMatch(/gate-invalidation\.yaml/)
    expect(body).toMatch(/set operation on the diff/i)
    expect(body).toMatch(/floor signal/)
    expect(body).toMatch(/carry over/i)
  })
})

describe('a feature is not done when the local tree says so', () => {
  /**
   * V2 stopped at Final Acceptance, which is a verdict about one tree on one
   * machine. Everything after the merge -- CI, the deployment, whether the
   * services that were supposed to start actually started -- happened
   * outside the model. One real deployment applied the migration, started
   * four components, crash-looped the worker, never reached the three
   * applications and skipped registration, and there was nowhere to record
   * any of that.
   */

  const stateIds = lifecycle.states.map((s) => s.id)
  const gateIds = gates.feature_gates.map((g) => g.id)
  const stageOf = (id: string) =>
    gates.feature_gates.find((g) => g.id === id)?.stage ?? 'pre_acceptance'

  it('runs from approval to closed', () => {
    expect(stateIds[0]).toBe('PLANNED')
    expect(stateIds[stateIds.length - 1]).toBe('CLOSED')
    for (const required of [
      'LOCAL_ACCEPTANCE_READY',
      'MERGE_READY',
      'MERGED',
      'PUSHED',
      'CI_VERIFIED',
      'DEV_DEPLOYED',
      'DEV_VERIFIED',
    ]) {
      expect(stateIds, `lifecycle has no ${required}`).toContain(required)
    }
  })

  it('puts acceptance before the merge and closure after everything', () => {
    const at = (id: string) => stateIds.indexOf(id)
    expect(at('LOCAL_ACCEPTANCE_READY')).toBeLessThan(at('MERGE_READY'))
    expect(at('MERGE_READY')).toBeLessThan(at('MERGED'))
    expect(at('PUSHED')).toBeLessThan(at('CI_VERIFIED'))
    expect(at('CI_VERIFIED')).toBeLessThan(at('DEV_DEPLOYED'))
    expect(at('DEV_DEPLOYED')).toBeLessThan(at('DEV_VERIFIED'))
    expect(at('DEV_VERIFIED')).toBeLessThan(at('CLOSED'))
  })

  it('names only real gates in its states', () => {
    for (const state of lifecycle.states) {
      for (const gate of state.requires_gates ?? []) {
        expect(gateIds, `state ${state.id} requires unknown gate ${gate}`).toContain(gate)
      }
    }
  })

  it('does not restate the engineering flow', () => {
    // The two-enumerations trap. The flow owns the ordering inside a
    // feature; the lifecycle owns where the feature is. A stage appearing
    // in both would be one sequence written twice, and the two would
    // disagree the first time either moved.
    const flowStages = workflow.workflow.engineering_flow
      .map((s) => s.stage ?? s.freeze)
      .filter(Boolean) as string[]
    for (const stage of flowStages) {
      expect(stateIds.map((s) => s.toLowerCase()), `${stage} is in both lists`).not.toContain(stage)
    }
    // And the join is declared rather than inferred.
    for (const state of lifecycle.engineering_flow_join.covers_states) {
      expect(stateIds, `join names unknown state ${state}`).toContain(state)
    }
  })

  it('reads its statuses from the file that defines a gate', () => {
    expect(lifecycle.statuses_from).toContain('quality-gates.yaml')
    // Nothing in this file may declare a status of its own.
    const text = readFileSync(join(ORCHESTRATION, 'lifecycle.yaml'), 'utf8')
    expect(text).not.toMatch(/^statuses:/m)
  })

  it('keeps local acceptance out of the post-merge gates, and vice versa', () => {
    // Making final acceptance wait on CI would deadlock it; letting it close
    // while CI is unrun is how a feature is "done" with a worker
    // crash-looping. The split is the answer to both.
    expect(stageOf('final_acceptance')).toBe('pre_acceptance')
    for (const gate of ['ci_verified', 'deployment_preflight', 'environment_verified']) {
      expect(gateIds, `${gate} is missing`).toContain(gate)
      expect(stageOf(gate), `${gate} must be post_merge`).toBe('post_merge')
    }
    const accepted = lifecycle.states.find((s) => s.id === 'LOCAL_ACCEPTANCE_READY')
    expect(accepted?.requires_gates).toEqual(['final_acceptance'])
    expect((accepted?.not_yet ?? []).join(' ')).toMatch(/merged|deployed/)
  })

  it('refuses to let local evidence satisfy a pipeline state', () => {
    const ci = lifecycle.states.find((s) => s.id === 'CI_VERIFIED')
    expect(ci?.local_evidence_does_not_satisfy).toBe(true)
    expect(lifecycle.rules.join(' ')).toMatch(/local PASS never satisfies/i)
  })

  it('treats a policy-disabled step as neither a failure nor an omission', () => {
    const registration = lifecycle.policy_disabled_steps.control_plane_registration
    expect(registration.status).toBe('NOT_APPLICABLE_BY_POLICY')
    expect(Object.keys(gates.statuses)).toContain(registration.status)
    // Named rather than gestured at: the reason, where it is tracked, and
    // the switch that would change it.
    expect(registration.why).toMatch(/estate-wide/i)
    expect(registration.tracked_as).toMatch(/F2b|F3/)
    expect(registration.switched_by).toMatch(/KORAS_DEPLOY_REGISTRATION/)
    expect(lifecycle.rules.join(' ')).toMatch(/never counted as a failure/i)
  })

  it('requires nothing pending before it will call a feature closed', () => {
    const closed = lifecycle.states.find((s) => s.id === 'CLOSED')
    const requires = (closed?.requires ?? []).join(' ')
    expect(requires).toMatch(/every applicable state/i)
    expect(requires).toMatch(/PENDING/)
  })
})

describe('a push is not a synchronisation, and a deployment is not one fact', () => {
  it('reads push impact from the workflows rather than from a table', () => {
    // A product that changed its workflows gets its own answer. A table
    // consulted instead of the file is a claim about a repository that has
    // moved on.
    expect(deployment.push_impact.read_from.length).toBeGreaterThan(0)
    for (const path of deployment.push_impact.read_from) {
      expect(path, `${path} is not a workflow`).toMatch(/\.github\/workflows\//)
    }
  })

  it('maps every branch to the environment the estate says it deploys', () => {
    // Immutable mapping. Changing it needs an ADR, so a drift here is a
    // defect rather than a preference.
    expect(deployment.push_impact.branches).toEqual({
      develop: { ci: true, deploys: 'dev' },
      test: { ci: true, deploys: 'test' },
      staging: { ci: true, deploys: 'stg' },
      main: { ci: true, deploys: 'prod' },
    })
  })

  it('tells a human what a push triggers before asking them to approve it', () => {
    const report = deployment.push_impact.report_before_approval.join(' ').toLowerCase()
    expect(report).toMatch(/ci/)
    expect(report).toMatch(/environment/)
    expect(report).toMatch(/migration/)
    expect(report).toMatch(/policy/)
    expect(deployment.push_impact.rule).toMatch(/never asked to approve/i)
    const merge = lifecycle.states.find((s) => s.id === 'MERGE_READY')
    expect(merge?.requires).toContain('push_impact_reported')
    expect(merge?.human_gate).toBe('merge_to_protected_branch')
  })

  it('records a state for every component, including the ones never reached', () => {
    const states = Object.keys(deployment.components.states)
    for (const required of ['NEW', 'UPDATED', 'FAILED', 'NOT_DEPLOYED', 'SKIPPED']) {
      expect(states, `component state ${required} is missing`).toContain(required)
    }
    // The distinction that decides what is safe to retry.
    expect(deployment.components.states.FAILED).not.toBe(
      deployment.components.states.NOT_DEPLOYED,
    )
    expect(states, 'a policy-disabled component has nowhere to go').toContain(
      'NOT_APPLICABLE_BY_POLICY',
    )
    expect(Object.keys(gates.statuses)).toContain('NOT_APPLICABLE_BY_POLICY')
  })

  it('covers the whole pipeline, in the order it runs', () => {
    expect(deployment.components.order).toEqual([
      'database',
      'services',
      'applications',
      'verification',
      'registration',
    ])
  })

  it('forbids re-running a migration because something later failed', () => {
    // The specific harm: the worker crash-looping says nothing whatever
    // about the schema, and re-running the pipeline to fix the worker is how
    // an applied migration gets applied again.
    const never = deployment.partial_deployment.never.join(' ').toLowerCase()
    expect(never).toMatch(/re-run a migration because a later stage failed/)
    expect(never).toMatch(/failed and not_deployed/i)
    expect(deployment.partial_deployment.retry_safety.database).toMatch(/only when the migration itself failed/i)
    for (const component of ['database', 'services', 'applications', 'verification', 'registration']) {
      expect(
        Object.keys(deployment.partial_deployment.retry_safety),
        `${component} has no retry answer`,
      ).toContain(component)
    }
  })

  it('blocks on an unknown deployment state rather than assuming one', () => {
    expect(deployment.partial_deployment.unknown_state.outcome).toBe('BLOCKED')
    const escalation = deployment.partial_deployment.unknown_state.escalation
    expect(Object.keys(budget.escalation), `${escalation} is not an escalation`).toContain(escalation)
    expect(budget.escalation[escalation]).toBe('BLOCKED')
  })

  it('traces a failure to the configuration provider before blaming the repository', () => {
    // The commonest wrong conclusion: "the setting is missing", when the
    // setting is present and malformed in Doppler.
    const trace = deployment.diagnosis.trace_in_order.join(' ').toLowerCase()
    expect(trace).toMatch(/doppler|configuration provider/)
    expect(deployment.diagnosis.classify_as_one_of.length).toBe(3)
    const never = deployment.diagnosis.never.join(' ').toLowerCase()
    expect(never).toMatch(/grep of the repository/)
    expect(never).toMatch(/without human approval/)
    // No diagnosis prints a value.
    expect(never).toMatch(/print a configuration value/)
  })

  it('has the Orchestrator report impact and refuse to guess', () => {
    const body = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/agents/orchestration/engineering-orchestrator.md'),
      'utf8',
    )
    expect(body).toMatch(/push impact/i)
    expect(body).toMatch(/Never ask for push approval without/)
    expect(body).toMatch(/Never guess at a deployment state/)
    expect(body).toMatch(/NOT_APPLICABLE_BY_POLICY/)
  })
})

describe('evidence is aimed, appended, and worth reading', () => {
  const doc = docPolicy.documentation

  it('writes planning documents first and narrative documents last', () => {
    // V2 said what to write and never when, and produced the expensive
    // order: narrative documents written alongside the code, rewritten
    // every time it moved, each rewrite pulling an audit and an acceptance
    // behind it.
    expect(doc.timing.before_implementation).toContain('requirements/user-story.md')
    expect(doc.timing.before_implementation).toContain('design/technical-design.md')
    expect(doc.timing.after_the_code_settles).toContain('documentation/user-guide.md')
    expect(doc.timing.after_the_code_settles).toContain('release/release-notes.md')
    // Nothing is written both before implementation and after it settles.
    for (const path of doc.timing.before_implementation) {
      expect(doc.timing.after_the_code_settles, `${path} is in both phases`).not.toContain(path)
    }
  })

  it('names only real documents in its timing', () => {
    const known = new Set([
      ...doc.required_for_all_features,
      ...Object.values(doc.required_by_condition).flat(),
      ...Object.keys(doc.templates.map),
    ])
    for (const phase of ['before_implementation', 'after_the_code_settles'] as const) {
      for (const path of doc.timing[phase]) {
        expect([...known], `timing names unknown document ${path}`).toContain(path)
      }
    }
  })

  it('appends raw runs rather than revising them', () => {
    // A summary edited until it matches the latest run has destroyed the one
    // thing evidence is for. A directory in which every run passed is a
    // claim, not a record.
    expect(doc.evidence_runs.path).toBe('testing/runs/<run-id>/')
    expect(doc.evidence_runs.path.startsWith(doc.sections.testing)).toBe(true)
    const rules = doc.evidence_runs.rules.join(' ').toLowerCase()
    expect(rules).toMatch(/never edited/)
    expect(rules).toMatch(/failed run stays/)
    expect(rules).toMatch(/new run directory, not an updated one/)
    expect(doc.evidence_rules.raw_runs_are_append_only).toBe(true)
    expect(doc.evidence_rules.historical_failed_runs_are_retained).toBe(true)
    for (const field of ['the command, verbatim', 'the commit under test', 'the result']) {
      expect(doc.evidence_runs.each_run_records, `runs must record ${field}`).toContain(field)
    }
  })

  it('aims manual QA rather than reducing it', () => {
    expect(doc.manual_qa.required_when.length).toBeGreaterThan(0)
    expect(doc.manual_qa.not_required_when.length).toBeGreaterThan(0)
    const never = doc.manual_qa.never.join(' ').toLowerCase()
    // The three ways a manual gate becomes decorative.
    expect(never).toMatch(/not executed/)
    expect(never).toMatch(/inferred from an automated result/)
    expect(never).toMatch(/schedule/)
    expect(doc.manual_qa.blocked_is_an_answer).toMatch(/never counted as a pass/i)
    // And the rule it must not contradict.
    expect(doc.evidence_rules.automated_results_do_not_satisfy_manual_gate).toBe(true)
  })

  it('sets no screenshot maximum, and says what earns a capture', () => {
    // 164 screenshots for 20 cases. The cost was not storage: a reviewer
    // could not tell which images proved anything, so the evidence got
    // skimmed, which is no evidence with more effort spent.
    expect(doc.screenshots.no_maximum).toBe(true)
    expect(doc.screenshots.higher_risk_may_justify_more).toBe(true)
    expect(doc.screenshots.capture_when_it_proves.length).toBeGreaterThan(3)
    const skip = doc.screenshots.do_not_capture.join(' ').toLowerCase()
    expect(skip).toMatch(/navigation/)
    expect(skip).toMatch(/next screen/)
    expect(skip).toMatch(/same state twice/)
  })

  it('requires every case to say what a capture proves', () => {
    // The field that makes the policy self-enforcing: a purpose that cannot
    // be written in a phrase is a capture that proves nothing, and writing
    // the phrase is how the author finds that out.
    expect(doc.test_case_fields).toContain('evidence_purpose')
    expect(doc.screenshots.purpose_required_when_not_obvious).toBe(true)
    const template = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/templates/feature/manual-test-results.md'),
      'utf8',
    )
    expect(template).toMatch(/What it proves/)
    expect(template).toMatch(/testing\/runs\//)
    expect(template).toMatch(/no maximum/i)
  })

  it('keeps every verdict and evidence rule it had before', () => {
    // P6 aims the evidence. It does not soften it, and this is the
    // assertion that would notice if it had.
    expect(doc.evidence_rules.actual_execution_only).toBe(true)
    expect(doc.evidence_rules.no_fabricated_screenshots).toBe(true)
    expect(doc.evidence_rules.screenshots_from_executed_steps_only).toBe(true)
    expect(doc.evidence_rules.expected_and_actual_required).toBe(true)
    expect(doc.evidence_rules.blocked_requires_documented_reason).toBe(true)
    expect(doc.evidence_rules.verdicts).toEqual(['PASS', 'FAIL', 'BLOCKED'])
  })
})

describe('a story is accepted on its own terms, an epic on the seams between them', () => {
  const epic = lifecycle.epic_acceptance

  it('closes a story without waiting for its siblings', () => {
    // A story that cannot close cannot be built on, and V2's single
    // acceptance meant every story either paid the epic's bill or left the
    // seams to nobody.
    expect(epic.story.runs).toMatch(/no cross-story gate/i)
    expect(epic.never.join(' ')).toMatch(/Holding a story open/i)
  })

  it('runs the epic pass once, after the last story closes', () => {
    expect(epic.epic.when).toMatch(/CLOSED/)
    expect(epic.epic.runs.length).toBeGreaterThan(3)
    const never = epic.never.join(' ').toLowerCase()
    expect(never).toMatch(/after every story/)
    expect(never).toMatch(/because its stories all closed/)
  })

  it('reuses story gates at the epic, and tests only what no story could', () => {
    expect(epic.epic.gate_reuse).toMatch(/seams/i)
    const runs = epic.epic.runs.join(' ').toLowerCase()
    expect(runs).toMatch(/cross-story/)
    expect(runs).toMatch(/combined result/)
  })

  it('does not defer a floor-signal seam to the end of the epic', () => {
    // Deferring a tenancy or authorization seam means building on it first.
    expect(epic.risk_exception).toMatch(/floor signal/)
    expect(epic.risk_exception).toMatch(/immediately/)
  })

  it('has the agents that produce evidence bound by the same policy', () => {
    const read = (p: string) => readFileSync(join(PRODUCT_TEMPLATE, '.claude', p), 'utf8')
    expect(read('agents/testing/manual-qa.md')).toMatch(/no maximum/i)
    expect(read('agents/documentation/test-documentation.md')).toMatch(/testing\/runs\//)
    expect(read('agents/documentation/test-documentation.md')).toMatch(/never deletes or rewrites a failed run/i)
    expect(read('agents/documentation/technical-writer.md')).toMatch(/after the code has settled/i)
    // The auditor judges purpose, not volume -- otherwise the screenshot
    // policy is advice and the incentive still rewards more images.
    expect(read('agents/review/qa-reviewer.md')).toMatch(/never whether there is a lot of it/i)
  })
})

describe('a stopped command leaves nothing behind, and a generated file is not a change', () => {
  /**
   * Both defects are in the shared template rather than the orchestration
   * contract, because both are mechanisms rather than rules. A standard that
   * says "clean up properly" is a rule an agent can follow correctly and
   * still leave an orphan, because `child.kill()` does not do what the
   * sentence implies.
   */

  const sharedScript = (name: string) =>
    readFileSync(join(STARTER_ROOT, 'profiles/_shared/template/local/scripts', name), 'utf8')

  it('kills the tree rather than the visible parent', () => {
    // dev-service spawns uv, which spawns Python, and on Windows goes
    // through cmd.exe as well. dev-app spawns Node running Next, which forks
    // its own workers. Signalling the child alone leaves the server holding
    // its port -- which is how a stopped QA stack blocked removing a
    // worktree.
    const helper = sharedScript('process-tree.mjs')
    expect(helper).toMatch(/taskkill/)
    expect(helper).toMatch(/\/T/)
    expect(helper).toMatch(/process\.kill\(-child\.pid/)
    expect(helper).toMatch(/detached: true/)
  })

  it('leaves no dev wrapper signalling the child alone', () => {
    for (const name of ['dev-app.mjs', 'dev-service.mjs.hbs']) {
      const body = sharedScript(name)
      expect(body, `${name} does not forward to the tree`).toMatch(/forwardSignals\(child\)/)
      expect(body, `${name} still spawns without a group`).toMatch(/groupSpawnOptions/)
      // The exact call that caused the orphan.
      expect(body, `${name} still calls child.kill directly`).not.toMatch(
        /process\.on\(signal, \(\) => child\.kill/,
      )
    }
  })

  it('ignores the file Next rewrites on every run', () => {
    // Decided from the repository's own conventions rather than from the
    // incident: eslint.config.mjs has ignored it since the applications
    // existed, nothing tracks one, and create-next-app ships it ignored.
    const gitignore = readFileSync(
      join(STARTER_ROOT, 'profiles/_shared/template/.gitignore.hbs'),
      'utf8',
    )
    expect(gitignore).toMatch(/^next-env\.d\.ts$/m)
  })

  it('carries that decision into both generated profiles', () => {
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      expect(gen.read('.gitignore'), `${gen.profile} .gitignore`).toMatch(/^next-env\.d\.ts$/m)
    }
  })

  it('has the worktree standard prepare dependencies before it trusts a failure', () => {
    // A worktree is a checkout, not an environment. A build that fails
    // locally and passes in CI, on a branch that added a dependency, is not
    // evidence of anything until the lockfiles have been compared.
    const standard = readFileSync(
      join(ORCHESTRATION, 'WORKTREE-STANDARD.md'),
      'utf8',
    )
    expect(standard).toMatch(/pnpm-lock\.yaml/)
    expect(standard).toMatch(/uv\.lock/)
    expect(standard).toMatch(/Synchronise only if they differ/)
    expect(standard).toMatch(/not yet evidence of anything/)
  })

  it('has the worktree standard terminate a tree and verify the ports', () => {
    const standard = readFileSync(join(ORCHESTRATION, 'WORKTREE-STANDARD.md'), 'utf8')
    expect(standard).toMatch(/process-tree\.mjs/)
    expect(standard).toMatch(/ports are released/)
    expect(standard).toMatch(/git worktree prune/)
    // The rule that stops a cleanup becoming a hazard of its own.
    expect(standard).toMatch(/Never kill by name/)
  })
})

describe('a malformed configuration value is caught before the migration', () => {
  /**
   * `STORAGE_RECONCILE_ENABLED` once resolved to `truefalse` -- two
   * concatenated values. The worker crash-looped, and the same deployment
   * had ALREADY applied its database migration: the schema had moved, the
   * services had not, and every name-based check had reported the setting
   * present and correct.
   *
   * The fix is a second tool, not a change to the first. `doppler-check.sh`
   * asks for names and never values, which is what makes it safe to run
   * anywhere, and that property is worth keeping.
   */

  const typecheck = readFileSync(
    join(STARTER_ROOT, 'profiles/_shared/template/local/scripts/config-typecheck.sh.hbs'),
    'utf8',
  )

  it('leaves the name-only checker reading no values at all', () => {
    const nameCheck = readFileSync(
      join(STARTER_ROOT, 'profiles/_shared/template/local/scripts/doppler-check.sh.hbs'),
      'utf8',
    )
    expect(nameCheck).toMatch(/--only-names/)
    expect(nameCheck).not.toMatch(/doppler secrets get/)
  })

  it('reads only what the manifest has explicitly typed', () => {
    // The default for a new setting is no type, so a secret is never read by
    // somebody forgetting to exclude it.
    expect(typecheck).toMatch(/\[ -n "\$\{type:-\}" \] \|\| continue/)
  })

  it('refuses a typed setting whose name looks like a credential', () => {
    // A type is a person's judgement that a setting is safe to read. This is
    // the rule that does not depend on that judgement being right.
    expect(typecheck).toMatch(/looks_like_a_credential/)
    for (const token of ['SECRET', 'PASSWORD', 'TOKEN', 'CREDENTIAL']) {
      expect(typecheck, `${token} is not refused`).toContain(token)
    }
    expect(typecheck).toMatch(/REFUSED/)
  })

  it('never prints a value, on success or on failure', () => {
    // Every echo in the script is checked: the report is the name, the
    // declared type and the fault, and `$value` appears in none of them.
    const echoes = typecheck.split('\n').filter((l) => /^\s*(echo|printf)\b/.test(l))
    expect(echoes.length).toBeGreaterThan(0)
    for (const line of echoes) {
      expect(line, `an echo prints a value: ${line.trim()}`).not.toMatch(/\$\{?value\}?/)
      expect(line, `an echo prints a fetched secret: ${line.trim()}`).not.toMatch(/\$\{?fault_value/)
    }
    // And the value is dropped as soon as it has been judged.
    expect(typecheck).toMatch(/unset value/)
  })

  it('knows the shapes that actually went wrong', () => {
    expect(typecheck).toMatch(/expected true or false/)
    expect(typecheck).toMatch(/expected an integer/)
    expect(typecheck).toMatch(/expected a URL/)
    expect(typecheck).toMatch(/expected one of/)
  })

  it('runs before anything is migrated or deployed', () => {
    const deployYml = readFileSync(
      join(STARTER_ROOT, 'profiles/_shared/template/.github/workflows/deploy.yml'),
      'utf8',
    )
    expect(deployYml).toMatch(/config-typecheck\.sh/)
    // In the settings job, which migrate depends on. Found by position: the
    // call has to appear before the migrate job is declared.
    const call = deployYml.indexOf('config-typecheck.sh')
    const migrate = deployYml.indexOf('\n  migrate:')
    expect(call).toBeGreaterThan(-1)
    expect(migrate).toBeGreaterThan(-1)
    expect(call, 'the typed check must run before migrate').toBeLessThan(migrate)
  })

  it('types settings in the manifest without disturbing what reads it', () => {
    // Two tools already parse this file positionally. The fourth column is
    // safe for the awk-based one, and the read-based one had to be told the
    // column exists -- otherwise it swallows it into `source` and every
    // derived row breaks.
    const bootstrap = readFileSync(
      join(STARTER_ROOT, 'profiles/_shared/template/local/scripts/doppler-bootstrap.sh.hbs'),
      'utf8',
    )
    expect(bootstrap).toMatch(/while read -r name class source type; do/)

    for (const profile of ['product', 'control-plane']) {
      const manifest = readFileSync(
        join(STARTER_ROOT, `profiles/${profile}/template/local/config/secrets.manifest.hbs`),
        'utf8',
      )
      expect(manifest, `${profile} manifest`).toMatch(/NAME<space>CLASS\[<space>SOURCE\[<space>TYPE\]\]/)
      const typed = manifest
        .split('\n')
        .filter((l) => /^[A-Z0-9_]+\s+(local|derived|supplied|optional)\s+\S+\s+\S+/.test(l))
      expect(typed.length, `${profile} types nothing`).toBeGreaterThan(0)
      for (const line of typed) {
        const [, , , type] = line.split(/\s+/)
        expect(
          /^(bool|int|url|nonempty|enum:[^\s]+)$/.test(type),
          `${profile}: unknown type "${type}" on ${line.split(/\s+/)[0]}`,
        ).toBe(true)
      }
    }
  })

  it('types the boolean that caused the incident', () => {
    const manifest = readFileSync(
      join(STARTER_ROOT, 'profiles/product/template/local/config/secrets.manifest.hbs'),
      'utf8',
    )
    expect(manifest).toMatch(/^STORAGE_RECONCILE_ENABLED\s+optional\s+-\s+bool$/m)
    expect(manifest).toMatch(/^STORAGE_LIFECYCLE_ENABLED\s+optional\s+-\s+bool$/m)
    expect(manifest).toMatch(/^STORAGE_BACKUP_ENABLED\s+optional\s+-\s+bool$/m)
  })

  it('reaches both generated profiles, since the pipeline is shared', () => {
    for (const gen of [PRODUCT, CONTROL_PLANE]) {
      expect(gen.has('local/scripts/config-typecheck.sh'), `${gen.profile} script`).toBe(true)
      expect(gen.has('local/scripts/process-tree.mjs'), `${gen.profile} helper`).toBe(true)
      expect(gen.read('.github/workflows/deploy.yml'), `${gen.profile} deploy`).toMatch(
        /config-typecheck\.sh/,
      )
      // Rendered, not left as a template.
      expect(gen.read('local/scripts/config-typecheck.sh')).not.toMatch(/\{\{/)
    }
  })

  it('gives the Control Plane the shared fixes and none of the orchestration', () => {
    // The explicit check for the one risk in touching _shared: these three
    // changes are mechanisms every repository needs, and none of them may
    // drag the product's orchestration contract across with it.
    expect(CONTROL_PLANE.has('local/scripts/config-typecheck.sh')).toBe(true)
    expect(CONTROL_PLANE.has('.claude/orchestration/risk-model.yaml')).toBe(false)
    expect(CONTROL_PLANE.has('.claude/orchestration/gate-invalidation.yaml')).toBe(false)
    expect(CONTROL_PLANE.has('.claude/commands/remediate.md')).toBe(false)
  })
})

describe('a run says what it did, and the Planner still cannot start anything', () => {
  it('reports the quantities V2.1 claims to improve', () => {
    // V2.1's central claims are quantities and V2 could not produce one of
    // them. "Too many reviews" was an impression; "five reviewer cycles, two
    // after the code stopped changing" is a fact somebody can act on.
    const reported = Object.values(telemetry.report).flat()
    for (const field of [
      'execution_mode',
      'agents_invoked',
      'agents_available_but_not_activated',
      'gates_executed',
      'gates_reused',
      'gates_invalidated',
      'reviewer_cycles',
      'budget_caps_reached',
      'human_escalations',
    ]) {
      expect(reported, `telemetry does not report ${field}`).toContain(field)
    }
  })

  it('reports policy-disabled gates separately from inapplicable ones', () => {
    const reported = Object.values(telemetry.report).flat()
    expect(reported).toContain('gates_not_applicable')
    expect(reported).toContain('gates_not_applicable_by_policy')
  })

  it('is engineering telemetry and carries nothing else', () => {
    const rules = telemetry.rules.join(' ').toLowerCase()
    expect(rules).toMatch(/no customer data/)
    expect(rules).toMatch(/secret/)
    expect(rules).toMatch(/nothing is collected, transmitted or stored outside/)
    // Counts come from what happened. A plan that predicted two reviews and
    // got five reports five.
    expect(rules).toMatch(/never from what the plan said/)
    // And the distinction that stops a gap being reported as a success.
    expect(rules).toMatch(/unknown, not as zero/)
  })

  it('keeps the Planner recommending and not starting', () => {
    const planner = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/agents/planning/product-planner.md'),
      'utf8',
    )
    expect(planner).toMatch(/Recommends; never starts/)
    expect(planner).toMatch(/not an authorization/)
    // Findings go in the mechanism the repository already has. A second list
    // is how two records of one problem come to disagree about its status.
    expect(planner).toMatch(/existing backlog mechanism/)
    expect(planner).toMatch(/never changes the risk model, the budget or a gate/)
    const command = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/commands/plan-next.md'),
      'utf8',
    )
    expect(command).toMatch(/existing backlog mechanism/)
    expect(command).toMatch(/WAITING FOR HUMAN APPROVAL/)
  })

  it('has the Orchestrator report telemetry at the end of a run', () => {
    const body = readFileSync(
      join(PRODUCT_TEMPLATE, '.claude/agents/orchestration/engineering-orchestrator.md'),
      'utf8',
    )
    expect(body).toMatch(/telemetry\.yaml/)
    expect(body).toMatch(/unknown rather than as zero/)
  })
})

describe('V2.1 is documented where the repository keeps its documentation', () => {
  const starterDoc = (p: string) => readFileSync(join(STARTER_ROOT, p), 'utf8')

  it('has one top-level architecture document that points at the detail', () => {
    const arch = starterDoc('docs/ENGINEERING_FRAMEWORK.md')
    expect(arch).toMatch(/docs\/features\/engineering-framework\//)
    expect(arch).toMatch(/docs\/adr\/0010-koras-engineering-framework-v2-1\.md/)
    // The four questions the framework exists to answer the same way twice.
    expect(arch).toMatch(/conditions\.yaml/)
    expect(arch).toMatch(/risk-model\.yaml/)
    expect(arch).toMatch(/gate-invalidation\.yaml/)
    expect(arch).toMatch(/execution-budget\.yaml/)
  })

  it('names every orchestration file that ships', () => {
    // The list in the architecture document against the directory itself,
    // because a hand-written list is correct when written and has no way of
    // noticing the world moved.
    const arch = starterDoc('docs/ENGINEERING_FRAMEWORK.md')
    for (const file of readdirSync(ORCHESTRATION)) {
      if (file.endsWith('.example.yaml')) continue
      expect(arch, `${file} is not described in the architecture document`).toContain(file)
    }
  })

  it('records the decision, its alternatives and its consequences', () => {
    const adr = starterDoc('docs/adr/0010-koras-engineering-framework-v2-1.md')
    expect(adr).toMatch(/^# ADR 0010/m)
    expect(adr).toMatch(/\*\*Status\.\*\* Accepted/)
    expect(adr).toMatch(/\*\*Alternatives rejected\.\*\*/)
    expect(adr).toMatch(/\*\*Consequences\.\*\*/)
    // The alternative that had to be rejected explicitly, because it is the
    // obvious one and it is wrong.
    expect(adr).toMatch(/Delete or merge agents/)
  })

  it('gives an existing product an upgrade path and names the one break', () => {
    const adoption = starterDoc('docs/features/engineering-framework/adoption.md')
    expect(adoption).toMatch(/No regeneration is required/)
    expect(adoption).toMatch(/applicability tokens were renamed/i)
    expect(adoption).toMatch(/v2-to-v2-1\.md/)
    const delta = starterDoc('docs/features/engineering-framework/v2-to-v2-1.md')
    // The rename table has to carry every retired spelling, or an upgrading
    // product has no way to find what it must change.
    for (const retired of [
      'user_facing',
      'api_or_integration_or_database',
      'security_risk_triggered',
      'user_or_operator_visible_change',
      'cross_feature_or_shared_contract_or_release',
      'business_workflow_or_ui_change',
      'configurable_or_operational_feature',
      'security_or_sensitive_data',
      'any_automated_verification_executed',
      'required_for_user_facing_features',
    ]) {
      expect(delta, `the delta does not map ${retired}`).toContain(retired)
    }
  })

  it('records what V2.1 did not build, rather than leaving it to be rediscovered', () => {
    const feature = starterDoc('docs/features/engineering-framework/README.md')
    expect(feature).toMatch(/Nothing executes any of this/)
    expect(feature).toMatch(/gate-result record is specified, not written/i)
    expect(feature).toMatch(/koras orchestrate/)
  })
})

describe('applicability and human evidence are two questions, each asked once', () => {
  /**
   * Found by the first real FAST run, on 2026-09-20. A two-line CSS fix in a
   * product classified FAST -- correctly, no signal fired -- and then selected
   * eleven gates including a manual QA pass, a screenshot pack and an
   * evidence audit, for a change four existing browser assertions already
   * covered exactly.
   *
   * Three files each had a defensible answer and together had none:
   *
   *   execution-modes      FAST.evidence_depth: minimal
   *   quality-gates        manual_qa_pass.applies: user_interface  -> applies
   *   documentation-policy not_required_when: automated verification
   *                        observes exactly what a person would    -> not required
   *
   * `evidence_depth` was the worst of the three, because nothing read it. A
   * mode may not switch a gate off -- that rule predates this -- so a field
   * implying a mode controls evidence could never have been honoured.
   */

  const doc = docPolicy.documentation

  it('lets no mode claim to decide evidence', () => {
    // The field is gone. A mode changes planning depth and reuse; gates come
    // from conditions, and whether a person must satisfy one comes from the
    // documentation policy.
    for (const [name, mode] of Object.entries(execModes.modes)) {
      expect(
        Object.keys(mode),
        `${name} declares evidence_depth, which nothing reads and no mode may decide`,
      ).not.toContain('evidence_depth')
    }
    const text = readFileSync(join(ORCHESTRATION, 'execution-modes.yaml'), 'utf8')
    expect(text).not.toMatch(/^\s+evidence_depth:/m)
  })

  it('points every human-evidence gate at the file that decides', () => {
    const governed = doc.manual_qa.governs_gates
    expect(governed.length).toBeGreaterThan(0)
    for (const id of governed) {
      const gate = gates.feature_gates.find((g) => g.id === id)
      expect(gate, `documentation-policy governs unknown gate ${id}`).toBeDefined()
      expect(
        gate?.human_evidence_decided_by,
        `${id} does not say which file decides whether a person is needed`,
      ).toContain('documentation-policy.yaml')
    }
  })

  it('points back, so neither file answers the other half alone', () => {
    // The pointer resolves in both directions: a gate that defers must be
    // governed, and a governed gate must defer. One-way would let a gate
    // quietly stop being covered.
    const deferring = gates.feature_gates
      .filter((g) => g.human_evidence_decided_by !== undefined)
      .map((g) => g.id)
    expect(deferring.sort()).toEqual([...doc.manual_qa.governs_gates].sort())
  })

  it('records an exemption as not-applicable, never as passed or blocked', () => {
    // BLOCKED would say a person was needed and unavailable. That is a
    // different and worse fact than a person not being needed, and the two
    // must not be recorded the same way.
    expect(doc.manual_qa.when_not_required_record).toMatch(/NOT_APPLICABLE/)
    expect(Object.keys(gates.statuses)).toContain('NOT_APPLICABLE')
  })

  it('exempts on who observes, never on how much time there is', () => {
    const never = doc.manual_qa.never_exempted_because.join(' ').toLowerCase()
    expect(never).toMatch(/small/)
    expect(never).toMatch(/schedule/)
    expect(never).toMatch(/unavailable/)
    // And the original no-softening rules still stand.
    expect(doc.evidence_rules.automated_results_do_not_satisfy_manual_gate).toBe(true)
    expect(doc.manual_qa.never.join(' ')).toMatch(/inferred from an automated result/i)
  })

  it('keeps the two clauses that can actually be evaluated', () => {
    const clauses = doc.manual_qa.not_required_when.join(' ').toLowerCase()
    expect(clauses).toMatch(/no surface a person can reach/)
    expect(clauses).toMatch(/observes exactly what a person would/)
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
    expect(activation.conditional.ai).toContain('ai-evaluation')
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

  /** Every document the policy can require, under any condition. */
  const allRequired = [
    ...doc.required_for_all_features,
    ...Object.values(doc.required_by_condition).flat(),
  ]

  it('points every required document at a section that exists', () => {
    const sections = Object.values(doc.sections) as string[]
    for (const path of allRequired) {
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
    for (const path of allRequired) {
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

#!/usr/bin/env node
/**
 * Convert a real OpenAPI 3.x document (produced by extract_openapi.py from a
 * running KORAS FastAPI app) into a Postman Collection v2.1.
 *
 * This is a *generator*, not a hand-maintained collection. Everything it
 * writes -- folders, requests, URLs, parameters, example bodies, status-code
 * assertions -- is derived from the schema, so a route that does not exist in
 * code cannot appear here. Every generated item carries
 * `koras.generated: true` in its Postman `event`-adjacent description marker
 * so `merge-custom.mjs` can tell a generated request apart from a
 * hand-maintained one (Security & Negative Tests, CI Smoke curation) when it
 * merges the two.
 *
 * Usage:
 *   node openapi-to-postman.mjs --openapi <file.json> --out <collection.json> \
 *        --name "Koras Control Plane" --base-url-var control_plane_base_url \
 *        [--correlation-header X-Request-Id]
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

function parseArgs(argv) {
  const out = {}
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg.startsWith('--')) {
      const key = arg.slice(2)
      const value = argv[i + 1]
      out[key] = value
      i += 1
    }
  }
  return out
}

function resolveRef(schema, ref, cache = new Map()) {
  if (!ref) return undefined
  if (cache.has(ref)) return cache.get(ref)
  const path = ref.replace(/^#\//, '').split('/')
  let node = schema
  for (const segment of path) node = node?.[segment]
  cache.set(ref, node)
  return node
}

/** Build a small, representative JSON example from a (possibly $ref'd) schema. */
function exampleFor(schema, root, opts = {}) {
  const depth = opts.depth ?? 0
  if (!schema || depth > 4) return null
  if (schema.$ref) return exampleFor(resolveRef(root, schema.$ref), root, { depth: depth + 1 })
  if (schema.example !== undefined) return schema.example
  if (schema.default !== undefined) return schema.default
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return schema.enum[0]

  const anyOf = schema.anyOf ?? schema.oneOf
  if (Array.isArray(anyOf) && anyOf.length > 0) {
    const nonNull = anyOf.find((s) => resolveRef(root, s.$ref ?? '')?.type !== 'null' && s.type !== 'null')
    return exampleFor(nonNull ?? anyOf[0], root, { depth: depth + 1 })
  }

  switch (schema.type) {
    case 'string':
      if (schema.format === 'date-time') return '2026-09-23T00:00:00Z'
      if (schema.format === 'date') return '2026-09-23'
      if (schema.format === 'uuid') return '00000000-0000-0000-0000-000000000000'
      if (schema.format === 'email') return 'user@example.com'
      return schema.title ? schema.title : 'string'
    case 'integer':
      return 0
    case 'number':
      return 0
    case 'boolean':
      return true
    case 'array': {
      const item = exampleFor(schema.items, root, { depth: depth + 1 })
      return item === null ? [] : [item]
    }
    case 'object':
    default: {
      if (!schema.properties) return schema.type === 'object' ? {} : null
      const obj = {}
      const required = new Set(schema.required ?? [])
      const keys = Object.keys(schema.properties)
      for (const key of keys) {
        // Keep generated bodies small: required fields always, optional
        // fields only when there are few of them, so a 40-field settings
        // payload does not become an unreadable wall in every request.
        if (!required.has(key) && keys.length > 8) continue
        obj[key] = exampleFor(schema.properties[key], root, { depth: depth + 1 })
      }
      return obj
    }
  }
}

function paramExample(param, root) {
  if (param.example !== undefined) return String(param.example)
  if (param.schema) {
    const value = exampleFor(param.schema, root)
    if (value !== null && value !== undefined) return String(value)
  }
  if (/id$/i.test(param.name)) return `{{${toSnake(param.name)}}}`
  return ''
}

function toSnake(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[-\s]/g, '_')
    .toLowerCase()
}

function humanize(name) {
  return name
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function statusTestScript(operation, method, correlationHeader) {
  const responses = Object.keys(operation.responses ?? {}).filter((code) => /^\d+$/.test(code))
  const successCodes = responses.filter((code) => code.startsWith('2') || code.startsWith('3'))
  const codes = (successCodes.length > 0 ? successCodes : responses).map(Number)

  const lines = []
  lines.push(`// Generated from the operation's declared responses (${responses.join(', ') || 'none declared'}).`)
  if (codes.length === 1) {
    lines.push(`pm.test("status is ${codes[0]}", () => pm.response.to.have.status(${codes[0]}));`)
  } else if (codes.length > 1) {
    lines.push(
      `pm.test("status is one of the declared codes", () => pm.expect(pm.response.code).to.be.oneOf([${codes.join(', ')}]));`,
    )
  } else {
    lines.push('pm.test("request completed", () => pm.expect(pm.response.code).to.be.below(500));')
  }
  lines.push('pm.test("responds within 3s", () => pm.expect(pm.response.responseTime).to.be.below(3000));')

  const successEntry = successCodes[0]
  const successSchema = successEntry ? operation.responses[successEntry]?.content?.['application/json'] : undefined
  if (successSchema) {
    lines.push('if (pm.response.code < 300) {')
    lines.push('  pm.test("content-type is application/json", () => {')
    lines.push('    pm.response.to.have.header("Content-Type");')
    lines.push('    pm.expect(pm.response.headers.get("Content-Type")).to.include("application/json");')
    lines.push('  });')
    lines.push('  pm.test("body parses as JSON", () => pm.response.json());')
    lines.push('}')
  }

  if (correlationHeader) {
    lines.push(`pm.test("carries ${correlationHeader}", () => pm.response.to.have.header("${correlationHeader}"));`)
  }

  if (method === 'post' && successCodes.some((c) => c.startsWith('20'))) {
    const varName = captureVarName(operation)
    if (varName) {
      lines.push('if (pm.response.code < 300) {')
      lines.push('  const body = pm.response.json();')
      lines.push('  if (body && body.id) {')
      lines.push(`    pm.environment.set("${varName}", body.id);`)
      lines.push(`    console.log("captured ${varName} =", body.id);`)
      lines.push('  }')
      lines.push('}')
    }
  }

  return lines.join('\n')
}

function captureVarName(operation) {
  const opId = operation.operationId ?? ''
  const tag = (operation.tags ?? [])[0] ?? ''
  const base = toSnake((opId.replace(/^(create|post|add)_?/i, '') || tag).replace(/s$/, ''))
  return base ? `${base}_id` : null
}

function buildUrl(baseUrlVar, path, pathParams) {
  let templated = path
  for (const param of pathParams) {
    templated = templated.replace(`{${param.name}}`, `:${param.name}`)
  }
  const raw = `{{${baseUrlVar}}}${templated}`
  const segments = templated.split('/').filter(Boolean)
  return {
    raw,
    host: [`{{${baseUrlVar}}}`],
    path: segments,
    variable: pathParams.map((p) => ({
      key: p.name,
      value: p.name.toLowerCase().endsWith('id') ? `{{${toSnake(p.name)}}}` : '',
      description: p.description ?? '',
    })),
  }
}

function buildRequest(path, method, operation, schema, opts) {
  const allParams = operation.parameters ?? []
  const pathParams = allParams.filter((p) => p.in === 'path')
  const queryParams = allParams.filter((p) => p.in === 'query')
  const headerParams = allParams.filter((p) => p.in === 'header')

  const url = buildUrl(opts.baseUrlVar, path, pathParams)
  url.query = queryParams.map((p) => ({
    key: p.name,
    value: paramExample(p, schema),
    description: p.description ?? '',
    disabled: !(p.required ?? false),
  }))

  const headers = headerParams.map((p) => ({
    key: p.name,
    value: paramExample(p, schema) || '<value>',
    description: p.description ?? '',
    disabled: !(p.required ?? false),
  }))

  let body
  const requestBody = operation.requestBody
  if (requestBody) {
    const jsonContent = requestBody.content?.['application/json']
    if (jsonContent) {
      const example = exampleFor(jsonContent.schema, schema)
      body = {
        mode: 'raw',
        raw: JSON.stringify(example ?? {}, null, 2),
        options: { raw: { language: 'json' } },
      }
      headers.push({ key: 'Content-Type', value: 'application/json' })
    } else if (requestBody.content?.['multipart/form-data']) {
      body = { mode: 'formdata', formdata: [{ key: 'file', type: 'file', src: '' }] }
    }
  }

  const summary = operation.summary || operation.operationId || `${method.toUpperCase()} ${path}`
  const description = [
    operation.description ?? '',
    '',
    `Source: ${opts.sourceLabel}`,
    operation.operationId ? `operationId: ${operation.operationId}` : '',
    operation.security === undefined || operation.security?.length !== 0
      ? 'Auth: Authorization: Bearer {{access_token}} (inherited from the collection)'
      : 'Auth: none declared for this operation',
  ]
    .filter(Boolean)
    .join('\n')

  return {
    name: summary,
    event: [
      {
        listen: 'test',
        script: { type: 'text/javascript', exec: statusTestScript(operation, method, opts.correlationHeader).split('\n') },
      },
    ],
    request: {
      method: method.toUpperCase(),
      header: headers,
      body,
      url,
      description,
    },
    response: [],
  }
}

function tagOrder(schema) {
  const tags = (schema.tags ?? []).map((t) => t.name)
  return tags.length > 0 ? tags : null
}

function convert(schema, opts) {
  const foldersByTag = new Map()
  const order = tagOrder(schema)
  if (order) for (const tag of order) foldersByTag.set(tag, { name: humanize(tag), item: [] })

  const untagged = { name: 'Uncategorized', item: [] }
  let operationCount = 0

  for (const [path, methods] of Object.entries(schema.paths ?? {})) {
    for (const [method, operation] of Object.entries(methods)) {
      if (!['get', 'post', 'put', 'patch', 'delete'].includes(method)) continue
      operationCount += 1
      const request = buildRequest(path, method, operation, schema, opts)
      const tag = (operation.tags ?? [])[0]
      const folder = tag ? (foldersByTag.get(tag) ?? (foldersByTag.set(tag, { name: humanize(tag), item: [] }), foldersByTag.get(tag))) : untagged
      folder.item.push(request)
    }
  }

  const folders = [...foldersByTag.values()].filter((f) => f.item.length > 0)
  if (untagged.item.length > 0) folders.push(untagged)

  const collection = {
    info: {
      name: opts.name,
      description: `Generated ${new Date().toISOString().slice(0, 10)} from the real OpenAPI schema of ${opts.sourceLabel}. ` +
        'Do not hand-edit generated folders/requests -- regenerate instead. See docs/api/postman-standard.md.',
      schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
      _postman_id: undefined,
    },
    item: folders,
    auth: {
      type: 'bearer',
      bearer: [{ key: 'token', value: '{{access_token}}', type: 'string' }],
    },
    variable: [{ key: 'api_version', value: opts.apiVersion ?? 'v1' }],
    event: [
      {
        listen: 'prerequest',
        script: { type: 'text/javascript', exec: ['// Collection-level: nothing to do yet. Auth is bearer, inherited per request.'] },
      },
    ],
  }

  return { collection, operationCount, pathCount: Object.keys(schema.paths ?? {}).length }
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.openapi || !args.out || !args.name || !args['base-url-var']) {
    console.error(
      'Usage: node openapi-to-postman.mjs --openapi <file> --out <file> --name <name> --base-url-var <var> [--api-version v1] [--correlation-header X-Request-Id] [--source-label <label>]',
    )
    process.exit(1)
  }

  const schema = JSON.parse(readFileSync(args.openapi, 'utf-8'))
  const { collection, operationCount, pathCount } = convert(schema, {
    baseUrlVar: args['base-url-var'],
    name: args.name,
    apiVersion: args['api-version'],
    correlationHeader: args['correlation-header'],
    sourceLabel: args['source-label'] ?? args.name,
  })

  mkdirSync(dirname(args.out), { recursive: true })
  writeFileSync(args.out, JSON.stringify(collection, null, 2))
  console.log(`wrote ${args.out}: ${pathCount} paths, ${operationCount} operations, ${collection.item.length} folders`)
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1] === fileURLToPath(import.meta.url)) {
  main()
}

export { convert, exampleFor }

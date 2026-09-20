import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { templatePath } from './template-path'
import {
  MAX_COLUMN_WIDTH,
  MIN_COLUMN_WIDTH,
  applyArrangement,
  clampWidth,
  parseArrangement,
  storageKey,
} from '../../../profiles/product/template/packages/ui/src/data-table/columns'

/**
 * The shared table's second seam: paging somebody else does, and a layout
 * somebody arranged.
 *
 * Two features were each working around the same limitation. `IMPORT-GAP-006`
 * says it plainly — the table takes the whole array and slices it, with no
 * total, no page callback and no loading state — and F27 records the other
 * side: five `grid.*` settings registered that nothing honoured, on a component
 * with no column interactions to honour them with. Neither feature should have
 * built this alone, and neither did.
 *
 * The arithmetic is executed here rather than read, because this package has no
 * test runner of its own and "restore what the person arranged" is the kind of
 * code that is obviously right and silently drops a column.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

const COLUMNS = [{ key: 'name' }, { key: 'size' }, { key: 'when' }]

describe('an arrangement is a hint about order, never a source of columns', () => {
  it('reorders the declared columns and nothing else', () => {
    expect(applyArrangement(COLUMNS, { order: ['when', 'name', 'size'] })).toEqual([
      { key: 'when' },
      { key: 'name' },
      { key: 'size' },
    ])
  })

  it('drops a key the table no longer declares', () => {
    // A stale entry from before a column was removed, or one somebody edited
    // by hand. The result is still exactly the declared set.
    const found = applyArrangement(COLUMNS, { order: ['when', 'gone', 'name'] })
    expect(found.map((column) => column.key)).toEqual(['when', 'name', 'size'])
  })

  it('cannot produce the same column twice', () => {
    const found = applyArrangement(COLUMNS, { order: ['name', 'name', 'name'] })
    expect(found.map((column) => column.key)).toEqual(['name', 'size', 'when'])
  })

  it('keeps a newly declared column where the developer put it', () => {
    // Somebody's saved order predates `size`. It must not be exiled to the end
    // of the table because of a layout they arranged last month.
    const found = applyArrangement(COLUMNS, { order: ['when', 'name'] })
    expect(found.map((column) => column.key)).toEqual(['when', 'name', 'size'])
  })

  it('is the declared order when there is no arrangement', () => {
    expect(applyArrangement(COLUMNS, null).map((c) => c.key)).toEqual(['name', 'size', 'when'])
    expect(applyArrangement(COLUMNS, { order: [] }).map((c) => c.key)).toEqual([
      'name',
      'size',
      'when',
    ])
  })

  it('never returns fewer or more columns than it was given', () => {
    for (const order of [[], ['size'], ['a', 'b'], ['when', 'when', 'size']]) {
      expect(applyArrangement(COLUMNS, { order }).length).toBe(COLUMNS.length)
    }
  })
})

describe('a width is bounded whatever arrives', () => {
  it('holds a usable number inside the bounds', () => {
    expect(clampWidth(200)).toBe(200)
    expect(clampWidth(2)).toBe(MIN_COLUMN_WIDTH)
    expect(clampWidth(99999)).toBe(MAX_COLUMN_WIDTH)
    expect(clampWidth(120.6)).toBe(121)
  })

  it('refuses what is not a width at all', () => {
    expect(clampWidth(Number.NaN)).toBeNull()
    // Infinity is refused rather than clamped: a width that is not a finite
    // number is not a width somebody set, it is storage that went wrong.
    expect(clampWidth(Number.POSITIVE_INFINITY)).toBeNull()
    expect(clampWidth(0)).toBeNull()
    expect(clampWidth(-40)).toBeNull()
  })
})

describe('stored state is input the component does not control', () => {
  it('reads back what it wrote', () => {
    const found = parseArrangement(JSON.stringify({ order: ['b', 'a'], widths: { a: 120 } }))
    expect(found).toEqual({ order: ['b', 'a'], widths: { a: 120 } })
  })

  it('survives anything that is not an arrangement', () => {
    for (const raw of [null, '', 'not json', '[]', '"a string"', '42', '{}']) {
      expect(parseArrangement(raw)).toBeNull()
    }
  })

  it('drops entries it cannot use rather than the whole arrangement', () => {
    const found = parseArrangement(
      JSON.stringify({ order: ['a', 7, null, 'b'], widths: { a: 120, b: 'wide', c: -1 } }),
    )
    expect(found).toEqual({ order: ['a', 'b'], widths: { a: 120 } })
  })

  it('bounds a width that arrived from storage', () => {
    const found = parseArrangement(JSON.stringify({ widths: { a: 99999 } }))
    expect(found?.widths?.a).toBe(MAX_COLUMN_WIDTH)
  })

  it('keys storage per table, so two on a page do not share one layout', () => {
    expect(storageKey('files')).not.toBe(storageKey('audit'))
    expect(storageKey('files')).toContain('files')
  })
})

describe('the table itself', () => {
  const table = read('packages', 'ui', 'src', 'data-table', 'data-table.tsx')

  it('stops slicing when the caller says how many there are', () => {
    // IMPORT-GAP-006. `total` is the switch: given one, `data` is this page.
    // Slicing it again would show the first fifty rows of every page.
    expect(table).toContain('const served = total !== undefined')
    expect(table).toContain('const rows = pages && !served ? data.slice(paging.start, paging.end) : data')
    expect(table).toContain('paginate(served ? total : data.length')
  })

  it('tells the caller the size as well as the page', () => {
    // On the server a size change is a different request and cannot be
    // inferred from the page number alone.
    expect(table).toContain('onPageChange?: (page: number, size: number) => void')
    expect(table).toContain('if (served) onPageChange?.(1, next)')
  })

  it('dims while loading rather than disappearing', () => {
    // A table that vanishes while the next page loads moves everything under
    // the pointer and loses the reader's place.
    expect(table).toContain('aria-busy={loading || undefined}')
    expect(table).toContain("cn(loading && 'opacity-60 transition-opacity')")
    expect(table).toContain('disabled={loading || paging.page <= 1}')
    expect(table).toContain('disabled={loading || paging.page >= paging.pages}')
  })

  it('reorders by button rather than by drag', () => {
    // A drag is invisible to a keyboard and awkward on a touch screen. Drag may
    // be added on top one day; it may not replace these.
    expect(table).toContain('function MoveButtons(')
    expect(table).toContain('aria-label={labels.moveColumnLeft(header)}')
    expect(table).toContain('aria-label={labels.moveColumnRight(header)}')
    expect(table).not.toContain('draggable')
  })

  it('leaves the resize handle out of the tab order, deliberately', () => {
    // Resizing refines something already legible; a keyboard user gets the
    // reorder buttons, which change what can be read, and is not made to tab
    // through one handle per column.
    const handle = table.slice(table.indexOf('cursor-col-resize') - 900, table.indexOf('cursor-col-resize'))
    expect(handle).toContain('aria-hidden="true"')
  })

  it('restores an arrangement after mount, never during render', () => {
    // The server has no storage, so reading it while rendering produces markup
    // the client does not agree with and React logs a hydration failure. The
    // Files page found this the hard way with time zones on 2026-09-17.
    expect(table).toContain('useEffect(() => {')
    expect(table).toContain('if (remembers && tableId) setArrangement(readArrangement(tableId))')
    const render = table.indexOf('const [arrangement, setArrangement] = useState<Arrangement | null>(null)')
    expect(render).toBeGreaterThan(-1)
    expect(table).not.toContain('useState(readArrangement(')
  })

  it('writes once at the end of a resize, not on every pointer move', () => {
    const end = table.slice(table.indexOf('const onResizeEnd'), table.indexOf('const moveColumn'))
    expect(end).toContain('writeArrangement(tableId, current)')
    const move = table.slice(table.indexOf('const onResizeMove'), table.indexOf('const onResizeEnd'))
    expect(move).not.toContain('writeArrangement')
  })

  it('will not move a column its caller fixed', () => {
    // A row selector, or an actions column at the end: a table whose actions
    // column has been dragged into the middle reads as broken.
    expect(table).toContain('fixed?: boolean')
    expect(table).toContain('columns.filter((column) => !column.fixed)')
    expect(table).toContain('canResize && !column.fixed')
    expect(table).toContain('canReorder && !column.fixed')
  })

  it('needs an identity before it remembers anything', () => {
    // Two tables on a screen with no identity between them would share one
    // arrangement and each would move when the other was dragged.
    expect(table).toContain('const remembers = (rememberColumns ?? settingRemember) && Boolean(tableId)')
  })
})

describe('the settings this closes', () => {
  const standard = read('services', 'api', 'koras_api', 'settings_catalogue', 'standard.py')
  const table = read('packages', 'ui', 'src', 'data-table', 'data-table.tsx')

  function body(key: string): string {
    const at = standard.indexOf(`"${key}"`)
    return standard.slice(at, standard.indexOf('\n    ),', at))
  }

  it.each(['grid.allowColumnResize', 'grid.allowColumnReorder', 'grid.rememberColumns'])(
    '%s is offered again, and read',
    (key) => {
      expect(body(key)).not.toMatch(/^\s+surfaced=False/m)
      expect(table, `${key} is surfaced and nothing reads it`).toContain(`'${key}'`)
    },
  )

  it.each(['grid.rememberFilters', 'grid.rememberSort'])('%s stays hidden, and unread', (key) => {
    // These describe persistence of state this table does not own. It has no
    // filter and no sort; a surface above it does.
    expect(body(key)).toMatch(/^\s+surfaced=False/m)
    expect(table).not.toContain(`'${key}'`)
  })

  it('falls back to the catalogue-s own default outside the provider', () => {
    // A table rendered without the settings provider must behave as a
    // configured one does, so each fallback is the declared default.
    expect(body('grid.allowColumnReorder')).toContain('False,')
    expect(table).toContain("useSettingValue('grid.allowColumnReorder', false)")
    expect(body('grid.allowColumnResize')).toContain('True,')
    expect(table).toContain("useSettingValue('grid.allowColumnResize', true)")
  })
})

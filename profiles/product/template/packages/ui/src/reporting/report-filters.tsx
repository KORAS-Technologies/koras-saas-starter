import { Button } from '../primitives/button'
import { SelectField, TextField } from '../primitives/field'
import type { FilterViewData, ReportingLabels } from './types'

/**
 * A report's filters, as a form that puts them in the URL.
 *
 * A plain GET form and no JavaScript: submitting it navigates to the same
 * page with the filters as query parameters, which is what makes a
 * filtered report a URL somebody can bookmark or send. The fields are the
 * ones the report declared -- a date range, a choice from a fixed list, a
 * bounded number -- rendered from the definition the API answered, so a
 * product's own report gets its filters with no page of its own.
 */
export function ReportFilters({
  action,
  filters,
  values,
  labels,
  testId,
}: {
  /** The page's own path. */
  action: string
  filters: FilterViewData[]
  /** The current query, so the form opens showing what applies. */
  values: Record<string, string>
  labels: ReportingLabels
  testId?: string
}) {
  if (filters.length === 0) return null
  return (
    <form
      method="get"
      action={action}
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end"
      data-testid={testId ?? 'report-filters'}
    >
      {filters.map((filter) => {
        if (filter.kind === 'date_range') {
          return (
            <FilterRange key={filter.key} values={values} labels={labels} />
          )
        }
        if (filter.kind === 'choice') {
          return (
            <SelectField
              key={filter.key}
              id={`filter-${filter.key}`}
              name={filter.key}
              label={filter.label}
              defaultValue={values[filter.key] ?? String(filter.default ?? '')}
            >
              <option value="">—</option>
              {filter.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </SelectField>
          )
        }
        return (
          <TextField
            key={filter.key}
            id={`filter-${filter.key}`}
            name={filter.key}
            label={filter.label}
            type="number"
            inputMode="numeric"
            min={filter.minimum ?? undefined}
            max={filter.maximum ?? undefined}
            defaultValue={values[filter.key] ?? String(filter.default ?? '')}
          />
        )
      })}
      <div>
        <Button type="submit" variant="secondary">
          {labels.filters.apply}
        </Button>
      </div>
    </form>
  )
}

function FilterRange({
  values,
  labels,
}: {
  values: Record<string, string>
  labels: ReportingLabels
}) {
  return (
    <>
      <TextField
        id="filter-from"
        name="from"
        label={labels.filters.from}
        type="date"
        defaultValue={values.from ?? ''}
      />
      <TextField
        id="filter-to"
        name="to"
        label={labels.filters.to}
        type="date"
        defaultValue={values.to ?? ''}
      />
    </>
  )
}

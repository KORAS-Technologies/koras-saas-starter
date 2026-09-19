'use client'

import { useId } from 'react'
import { cn } from '../lib/cn'
import { SubmitButton } from '../primitives/submit-button'
import {
  describeValue,
  optionLabel,
  type SettingField,
  type SettingGroup,
  type SettingsFormLabels,
} from './fields'

/**
 * One scope's settings, grouped by category, with what each one was given.
 *
 * Used by both customer surfaces. The organisation's page passes the tenant's
 * stored values and the platform's as the inherited ones; My preferences passes
 * the person's and the organisation's. Neither page knows how a control is
 * drawn, and this knows nothing about which scope it is editing — the two
 * differences that matter, `isSet` and `inherited`, are data.
 *
 * **One form per category, and a reset button per field inside it.** A page
 * with one form for twenty-seven settings makes every save a twenty-seven-field
 * write, and an administrator who changed the upload limit gets an audit entry
 * for everything they looked at. A form per category matches how people think
 * about the page and keeps the audit trail readable.
 *
 * The reset is a `formAction` on a button rather than a second form, because a
 * form inside a form is not HTML and the alternative — a form beside it,
 * positioned to look inside — breaks the moment anything reflows.
 */
export function SettingsForm({
  groups,
  labels,
  save,
  reset,
  testId = 'settings-form',
}: {
  groups: SettingGroup[]
  labels: SettingsFormLabels
  /** Takes the whole category's fields. */
  save: (form: FormData) => void | Promise<void>
  /**
   * Takes one `key`, and means different things at the two scopes: the
   * organisation takes the platform's current value, a person stops holding
   * one at all. The API decides which; this only names the key.
   */
  reset: (form: FormData) => void | Promise<void>
  testId?: string
}) {
  return (
    <div className="space-y-6" data-testid={testId}>
      {groups.map((group) => (
        <section
          key={group.category}
          data-category={group.category}
          className="rounded-lg border border-line p-6"
        >
          <h2 className="font-display text-lg font-bold text-ink">{group.title}</h2>
          <form action={save} className="mt-4 space-y-5">
            {/* Which category is being saved, so the action writes only these. */}
            <input type="hidden" name="category" value={group.category} />
            {group.fields.map((field) => (
              <Field key={field.key} field={field} labels={labels} reset={reset} />
            ))}
            <div className="pt-1">
              <SubmitButton busy={labels.saving} testId={`save-${group.category}`}>
                {labels.save}
              </SubmitButton>
            </div>
          </form>
        </section>
      ))}
    </div>
  )
}

function Field({
  field,
  labels,
  reset,
}: {
  field: SettingField
  labels: SettingsFormLabels
  reset: (form: FormData) => void | Promise<void>
}) {
  const id = useId()
  const describedBy = `${id}-description`

  return (
    <div className="border-t border-line/60 pt-4 first:border-0 first:pt-0" data-setting={field.key}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm font-semibold text-ink">
          {field.label}
        </label>
        <span
          className={cn(
            'text-xs',
            field.isSet ? 'text-ink' : 'text-ink-muted',
          )}
          data-state={field.isSet ? 'modified' : 'inherited'}
        >
          {field.isSet
            ? labels.modified
            : `${labels.inheritedFrom}: ${readable(field, field.inherited, labels)}`}
        </span>
      </div>

      <p id={describedBy} className="mt-1 text-sm leading-6 text-ink-muted">
        {field.description}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Control field={field} id={id} describedBy={describedBy} labels={labels} />
        {field.isSet ? (
          <button
            type="submit"
            formAction={reset}
            name="key"
            value={field.key}
            data-testid={`reset-${field.key}`}
            className="rounded-md border border-line px-2 py-1 text-xs text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            // Said in full, because "Reset" alone next to twenty-seven fields
            // does not say which one, and a screen reader reads the buttons in
            // a list with nothing else around them.
            aria-label={`${labels.reset}: ${field.label}`}
            title={labels.resetTo(readable(field, field.inherited, labels))}
          >
            {labels.reset}
          </button>
        ) : null}
      </div>
    </div>
  )
}

function readable(field: SettingField, value: unknown, labels: SettingsFormLabels): string {
  return field.options.length > 0
    ? optionLabel(field, value as never)
    : describeValue(value as never, labels)
}

const CONTROL = 'rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'

function Control({
  field,
  id,
  describedBy,
  labels,
}: {
  field: SettingField
  id: string
  describedBy: string
  labels: SettingsFormLabels
}) {
  if (field.ui === 'toggle') {
    return (
      <input
        id={id}
        type="checkbox"
        name={field.key}
        defaultChecked={field.value === true}
        aria-describedby={describedBy}
        className="h-4 w-4 accent-[var(--brand-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      />
    )
  }

  if (field.ui === 'select') {
    return (
      <select
        id={id}
        name={field.key}
        defaultValue={String(field.value)}
        aria-describedby={describedBy}
        className={CONTROL}
      >
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    )
  }

  if (field.ui === 'number') {
    return (
      <input
        id={id}
        type="number"
        name={field.key}
        defaultValue={String(field.value)}
        // The definition's own bounds, so the browser refuses what the API
        // would refuse. Belt as well as braces: the API checks again, because a
        // browser control is a convenience and not a guard.
        min={field.minimum ?? undefined}
        max={field.maximum ?? undefined}
        step={field.dataType === 'decimal' ? 'any' : 1}
        aria-describedby={describedBy}
        className={cn(CONTROL, 'w-32')}
      />
    )
  }

  if (field.ui === 'chips') {
    return (
      <input
        id={id}
        type="text"
        name={field.key}
        defaultValue={Array.isArray(field.value) ? field.value.join(', ') : String(field.value)}
        aria-describedby={describedBy}
        placeholder={labels.listHint}
        className={cn(CONTROL, 'w-72')}
      />
    )
  }

  return (
    <input
      id={id}
      type="text"
      name={field.key}
      defaultValue={String(field.value)}
      aria-describedby={describedBy}
      className={cn(CONTROL, 'w-72')}
    />
  )
}

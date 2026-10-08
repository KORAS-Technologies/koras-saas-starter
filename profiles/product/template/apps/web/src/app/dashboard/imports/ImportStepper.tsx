import { STAGES, stepState } from './run-stage'
import type { Stage } from './run-stage'

export interface StepperLabels {
  nav: string
  steps: Record<Stage, string>
  current: string
  done: string
}

/**
 * The seven stages, in order, as an ordered list: the step the run is in is
 * `aria-current="step"` and said in words (colour never carries it alone), the
 * earlier ones say they are done. It is a status display, not navigation --
 * a step is not a control, because a stage is a fact about the run and the
 * server decides it; there is nothing to jump to that the panel's own buttons
 * do not already offer.
 */
export function ImportStepper({ stage, labels }: { stage: Stage | null; labels: StepperLabels }) {
  return (
    <div data-testid="imports-stepper" data-stage={stage ?? 'ended'}>
      <ol aria-label={labels.nav} className="flex flex-wrap gap-x-2 gap-y-2 text-sm">
        {STAGES.map((step, index) => {
          const state = stepState(step, stage)
          return (
            <li
              key={step}
              data-step={step}
              data-state={state}
              aria-current={state === 'current' ? 'step' : undefined}
              className={
                'flex min-h-8 items-center gap-2 rounded-brand border px-3 py-1 ' +
                (state === 'current'
                  ? 'border-brand bg-surface-muted font-semibold text-ink'
                  : state === 'done'
                    ? 'border-line text-ink'
                    : 'border-line text-ink-muted')
              }
            >
              <span aria-hidden="true" className="tabular-nums">
                {state === 'done' ? '✓' : index + 1}
              </span>
              <span>{labels.steps[step]}</span>
              {state === 'current' ? <span className="sr-only">{labels.current}</span> : null}
              {state === 'done' ? <span className="sr-only">{labels.done}</span> : null}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

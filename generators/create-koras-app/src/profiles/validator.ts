import type { ProfileManifest, ComponentSelections, ProfileDefaults } from './types.js'

/**
 * Merges defaults and manifest to produce the initial component selection state.
 * Required components are always true; optional components fall back to defaults.
 */
export function resolveSelections(
  manifest: ProfileManifest,
  defaults: ProfileDefaults,
): ComponentSelections {
  const applications: Record<string, boolean> = {}
  for (const [name, app] of Object.entries(manifest.applications)) {
    applications[name] = app.required || (defaults.applications?.[name] ?? false)
  }

  const services: Record<string, boolean> = {}
  for (const [name, svc] of Object.entries(manifest.services)) {
    services[name] = svc.required || (defaults.services?.[name] ?? false)
  }

  const capabilities: Record<string, boolean> = {}
  for (const [name, enabled] of Object.entries(manifest.capabilities)) {
    capabilities[name] = enabled
  }

  return { applications, services, capabilities }
}

/**
 * Validates that required manifest components are enabled in the given selections.
 * Throws if any required component has been disabled.
 */
export function validateSelections(
  manifest: ProfileManifest,
  selections: ComponentSelections,
): void {
  for (const [name, app] of Object.entries(manifest.applications)) {
    if (app.required && !selections.applications[name]) {
      throw new Error(
        `Application "${name}" is required for profile "${manifest.profile}" and cannot be disabled.`,
      )
    }
  }

  for (const [name, svc] of Object.entries(manifest.services)) {
    if (svc.required && !selections.services[name]) {
      throw new Error(
        `Service "${name}" is required for profile "${manifest.profile}" and cannot be disabled.`,
      )
    }
  }
}

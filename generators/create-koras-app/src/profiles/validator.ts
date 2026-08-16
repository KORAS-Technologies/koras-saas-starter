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

  // A capability the manifest does not support can never be enabled by defaults;
  // a supported capability may be switched off by the profile defaults.
  const capabilities: Record<string, boolean> = {}
  for (const [name, supported] of Object.entries(manifest.capabilities)) {
    const override = defaults.capabilities?.[name]
    capabilities[name] = supported && (typeof override === 'boolean' ? override : true)
  }

  return { applications, services, capabilities }
}

/**
 * Applies `--with` / `--without` component overrides onto resolved selections.
 * Component names are manifest keys (applications, services, or capabilities).
 * Throws with an actionable message when a name is unknown to the profile.
 */
export function applyComponentOverrides(
  manifest: ProfileManifest,
  selections: ComponentSelections,
  overrides: { with?: string[]; without?: string[] },
): void {
  const apply = (name: string, enabled: boolean) => {
    if (name in manifest.applications) {
      selections.applications[name] = enabled
    } else if (name in manifest.services) {
      selections.services[name] = enabled
    } else if (name in manifest.capabilities) {
      selections.capabilities[name] = enabled
    } else {
      const known = [
        ...Object.keys(manifest.applications),
        ...Object.keys(manifest.services),
        ...Object.keys(manifest.capabilities),
      ].sort()
      throw new Error(
        `Unknown component "${name}" for profile "${manifest.profile}".\n` +
          `  Known components: ${known.join(', ')}`,
      )
    }
  }

  for (const name of overrides.with ?? []) apply(name, true)
  for (const name of overrides.without ?? []) apply(name, false)
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

  for (const [name, enabled] of Object.entries(selections.capabilities)) {
    if (enabled && manifest.capabilities[name] !== true) {
      throw new Error(
        `Capability "${name}" is not supported by profile "${manifest.profile}" and cannot be enabled.`,
      )
    }
  }
}

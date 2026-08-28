/**
 * Tailwind's PostCSS plugin.
 *
 * Without this file Next handles `@import "tailwindcss"` with its own CSS
 * pipeline: it inlines the package's stylesheet and ships it verbatim, so the
 * built bundle carries a literal, uncompiled `@tailwind utilities` directive
 * and not one utility class exists at runtime.
 *
 * Nothing reveals this while an application styles itself by hand, which a
 * freshly generated one does -- Tailwind is declared, imported, and silently
 * inert. It surfaces the first time somebody writes a utility class and the
 * element renders unstyled, by which point the obvious suspect is their class
 * name rather than the build.
 */
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
}

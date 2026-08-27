# Frontend rules

- Use Vue 3 Composition API, TypeScript, and explicit feature modules.
- Vue Query owns server state; Pinia owns client state.
- Use PrimeVue components according to their current API and preserve accessible labels.
- Put every user-facing message in both locale files and run the i18n key check.
- Generate API types from OpenAPI; do not hand-maintain duplicate transport contracts.
- Treat an authentication `401` during session restoration as guest state, and do not mount
  protected queries until restoration completes.
- Send unsafe requests through the shared API client so its CSRF middleware cannot be bypassed.
- Keep the browser API base URL same-origin; configure gateway/Vite upstreams instead of bypassing
  the cookie and CSRF boundary.
- Validate authentication fields locally with localized messages, but keep strict backend DTOs
  authoritative and never trim passwords.
- Persist only client-owned selections. Revalidate a stored workspace ID against the authenticated
  workspace query before using it.
- Keep `<html lang>` and PrimeVue locale synchronized with the active application locale.

---
name: frontend-primevue
description: Add or modify Vue 3, TypeScript, PrimeVue, Vue Query, Pinia, API client, or i18n frontend code in this generated project.
---

Before editing PrimeVue components, read the bundled
[primevue-skilld](../primevue-skilld/SKILL.md) and its relevant local references. That snapshot
documents PrimeVue 4.5.4; verify patch-level differences against the installed 4.5.5 types. Keep
PrimeVue 4, PrimeUIX Themes 1, and PrimeIcons 7 on their MIT-licensed lines. PrimeVue 5 requires a
separate license and migration decision.

Keep features self-contained. Put remote state in Vue Query and client-only state in Pinia. Verify
PrimeVue component props and accessibility, add both locale translations, avoid raw transport models
inside views when mapping is needed, and create UUIDs through the shared `createUuid` adapter so
non-secure LAN development origins do not depend on `crypto.randomUUID()`. Run typecheck, unit tests,
i18n checks, and build.

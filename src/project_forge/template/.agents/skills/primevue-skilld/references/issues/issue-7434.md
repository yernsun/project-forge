---
number: 7434
title: Error with Form import
type: other
state: closed
created: 2025-03-12
url: "https://github.com/primefaces/primevue/issues/7434"
reactions: 41
comments: 44
labels: "[Status: Pending Review]"
---

# Error with Form import

### Describe the bug

Version 4.2.5 fails to launch with this error:

`tryout-2 on  main [!] via ⬢ v20.18.0 using ☁️  default/ 
➜ yarn run dev
yarn run v1.22.17
$ nuxt dev
[ nuxi  11:50:28 AM] Nuxt 3.16.0 with Nitro 2.11.6
[11:50:28 AM] 
  ➜ Local:    http://localhost:3000/
  ➜ Network:  use --host to expose

[nuxt:tailwindcss 11:50:29 AM] ℹ Using default Tailwind CSS file
[11:50:29 AM]   ➜ DevTools: press Shift + Option + D in the browser (v2.2.1)

[11:50:30 AM] ℹ Re-optimizing dependencies because lockfile has changed
[11:50:30 AM] ✔ Vite client built in 38ms
[11:50:30 AM] ✔ Vite server built in 301ms

[11:50:30 AM]  ERROR  Pre-transform error: Failed to resolve import "@primevue/forms/form?nuxt_component=async&nuxt_component_name=Form&nuxt_component_export=default" from "virtual:nuxt:%2FUsers%2Fjcham%2FGit%2FML%2Ftryout-2%2F.nuxt%2Fcomponents.plugin.mjs". Does the file exist?
  Plugin: vite:import-analysis
  File: virtual:nuxt:%2FUsers%2Fjcham%2FGit%2FML%2Ftryout-2%2F.nuxt%2Fcomponents.plugin.mjs:122:23
  120|  import LazyTag from 'primevue/tag?nuxt_component=async&nuxt_component_name=Tag&nuxt_component_export=default';
  121|  import LazyTerminal from 'primevue/terminal?nuxt_component=async&nuxt_component_name=Terminal&nuxt_component_export=default';
  122|  import LazyForm from '@primevue/forms/form?nuxt_component=async&nuxt_component_name=Form&nuxt_component_export=default';
     |                        ^
  123|  import LazyFormField from '@primevue/forms/formfield?nuxt_component=async&nuxt_component_name=FormField&nuxt_component_export=default';
  124|  const lazyGlobalComponents = [


[11:50:31 AM]  WARN  "@primevue/forms/formfield/style" is imported by "virtual:#primevue-style", but could not be resolved – treating it as an external dependency.


[11:50:31 AM]  WARN  "@primevue/forms/form/style" is imported by "virtual:#primevue-style", but could not be resolved – treating it as an external dependency.

...

---

## Top Comments

**@Willen17** (+31):

@jcham I also got this error. Solved it by installing the @primevue/forms lib too, ```npm install @primevue/forms```

Temporary solution, but feels like the should add it as a dependency of primevue if it has to be used.

**@wangziling** (+19):

> [@jcham](https://github.com/jcham) I also got this error. Solved it by installing the @primevue/forms lib too, `npm install @primevue/forms`
> 
> Temporary solution, but feels like the should add it as a dependency of primevue if it has to be used.

And if you didn't use its `` or `<FormField />` components, you can set `excludes` subproperty of the `primevue` property in the `nuxt.config.ts`.



I thought maybe I can yield a PR for this.

**@sbruegel**:

Same since updating to nuxt 3.16.0 not sure if it is related to this issue in nuxt
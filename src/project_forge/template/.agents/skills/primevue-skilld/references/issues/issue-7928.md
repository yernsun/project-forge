---
number: 7928
title: Support Nuxt 4
type: feature
state: closed
created: 2025-07-18
url: "https://github.com/primefaces/primevue/issues/7928"
reactions: 68
comments: 11
labels: "[Type: Enhancement]"
---

# Support Nuxt 4

Hi PrimeVue team 

First of all, thank you for the great work on this project — we really enjoy using PrimeVue!

I’d like to ask if Nuxt 4 compatibility is planned or already in progress. Do you have any roadmap or updates regarding official support for Nuxt 4?

It would be helpful to know:

If there are any known compatibility issues with Nuxt 4 (e.g., hydration, SSR, composables, etc.)

Whether an updated version of the primevue/nuxt module is expected

Any suggested workarounds for developers who want to start experimenting with Nuxt 4

Thanks in advance, and keep up the great work! 

---

## Top Comments

**@daniil4udo** (+21):

If you're concerned about breaking production, please release at least a major beta version of the Nuxt module. PrimeVue is currently the only blocker preventing us from migrating."

**@EntertainmentPortal** (+5):

For the timebeing, you can use the base PrimeVue package.

1. install nuxt as normal
2. upgrade nuxt to V4 as described in their upgrade guides
3. `npm install primevue` (not primevue/nuxt or nuxt-primevue!)
4. In app/plugins create a file **primevue.js**
5. Paste this code:
```
import PrimeVue from "primevue/config";
import Button from "primevue/button";

export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.vueApp.use(PrimeVue, {
    ripple: true,
    pt: {
      button: {
        label: {
          style: {
            backgroundColor: "red",
            color: "white",
            padding: "10px",
            borderRadius: "5px",
            fontSize: "16px",
            fontWeight: "bold",
            textAlign: "center",
            textTransform: "uppercase",
            letterSpacing: "1px",
          },
        },
      },
    },
  });

  nuxtApp.vueApp.component("Button", Button);
});

...

**@tugcekucukoglu** [maintainer]:

Related issue is: https://github.com/primefaces/primevue/issues/7918
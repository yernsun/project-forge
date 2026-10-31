---
number: 7151
title: PrimeVue 2 documentation removed?
type: other
state: closed
created: 2025-01-27
url: "https://github.com/primefaces/primevue/issues/7151"
reactions: 26
comments: 16
---

# PrimeVue 2 documentation removed?

We're currently using PrimeVue 2, converting all of our components over to it from BootstrapVue ahead of our planned migration to Vue3 - since PrimeVue is compatible with Vue3 but BoostrapVue is not.

To access PrimeVue 2 specific documentation, we've been using this link: https://www.primefaces.org/primevue-v2.  However, as of this morning, that link returns a 404 error.

Would it be possible for one of the following resolutions:

- Provide an alternative link for PrimeVue 2 documentation.
- If it has been removed, reinstate the PrimeVue 2 documentation.
- If the above is not possible, provide the source code of the PrimeVue 2 documentation site so we can self-host.

Thank you in advance.

---

## Top Comments

**@pedrociarlini** (+21):

> @Oliver-Saer The documentation is still in the repo, there is a 2.x branch and a tag for 2.10.4. You should be able to use these to selfhost the documentation locally.

Yeah... thats the way.

To help others to self host:
```
# git clone https://github.com/primefaces/primevue.git
# cd primevue
# git switch 2.x
# npm install
# npm run serve
```


**@MelkorCC** (+10):

> You have to remember in companies, it can take time to build a plan to swap out older tech for the newer version. Often it's heavily embedded and can't just be ripped out and swapped quickly and easily. Two years is not a long time in that respect.

I totally agree that migrations take time, but to be fair the Vue 2 EOL was not announced in 2023, but at the beginning of 2022 when Vue 3 became the default version. So it is not like people were surprised in 2023 when Vue 2 had it's EOL. Given that we are now at the beginning of 2025 people actually had 3 years to migrate from Vue 2 to Vue 3.

...

**@MelkorCC** (+8):

> If the above is not possible, provide the source code of the PrimeVue 2 documentation site so we can self-host.

@Oliver-Saer The documentation is still in the repo, there is a 2.x branch and a tag for 2.10.4. You should be able to use these to selfhost the documentation locally.

...
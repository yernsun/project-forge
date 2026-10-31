---
number: 3995
title: "All components: Improve type support"
type: other
state: open
created: 2023-05-27
url: "https://github.com/primefaces/primevue/issues/3995"
reactions: 22
comments: 18
labels: "[Status: Pending Review]"
---

# All components: Improve type support

### Describe the feature you would like to see added

Vue 3.3 introduced generic components. Using these, it is now possible to provide precise, high-quality types for props, events and slots with generic parameters. (For props this was already possible though quite cumbersome.)

### Is your feature request related to a problem?

It is frustrating to deal with untyped or insufficiently typed components in an application. In such cases autocompletion stops working leading to worse DX but also, and for the resulting product more important, it is no longer possible to check correctness of the code.

This is most often the case when working with events, slots and complex components like data tables.

### Describe the solution you'd like

It would be great if this project could utilize the new generic capabilities from Vue 3.3. It is possible to use this within .d.ts files, however, in the long term it will likely be beneficial to consider moving to typescript which would automate a lot of this stuff and can also be used for automatic and precise API/documentation generation.

### Describe alternatives you have considered

Not adding generic support: This is the status quo which comes with drawbacks in DX and type safety.

### Additional context

Vue 3.3 announcement blog post: https://blog.vuejs.org/posts/vue-3-3#script-setup-typescript-dx-improvements

---

I am not sure if/how this can be applied to the current API for data tables where columns are their own component. Other components already have support for typed column definitions as they are passed to the table component and can thus be typed together with knowledge of the passed values. (This is also possible with earlier Vue versions though a bit more convoluted).
As the table and columns are different components in primevue I am not sure if this can be supported without API changes.

Regardless, it would still be possible to offer this support for other components.
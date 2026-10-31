---
number: 7838
title: "Form: Generic type is not inferred from `resolver` prop, causing type errors"
type: other
state: open
created: 2025-06-19
url: "https://github.com/primefaces/primevue/issues/7838"
reactions: 13
comments: 3
labels: "[Status: Pending Review]"
---

# Form: Generic type is not inferred from `resolver` prop, causing type errors

### Describe the bug

With PrimeVue `v4.3.3`, the generic type `T` of the `Form` component is not correctly inferred in the template when a strongly-typed `resolver` is provided. This was partially addressed in https://github.com/primefaces/primevue/pull/7287 but the core issue persists, making it impossible to create a fully type-safe form.

This appears to be the same underlying problem as reported in issue https://github.com/primefaces/primevue/issues/7338, which was closed when the related PR was merged.

**The Problem**

The root of the issue is that the `Form` component's generic type `T` is not correctly inferred within the template, leading to a fallback to the default `Record<string, any>`.

This is most evident when using a `resolver`. When a strongly-typed `resolver` prop is provided (e.g., `yupResolver<FormData>`), Vue's template compiler fails to infer that `T` should be `FormData`. This is a bug because the typed `resolver` is the intended way to inform the component of the form's data structure.

As a result, a type mismatch error occurs when the `@submit` handler in `<script>` is strongly typed (e.g., `(event: FormSubmitEvent<FormData>) => ...`), because the template expects a handler that accepts the default `FormSubmitEvent<Record<string, any>>`.

**TypeScript Error:**

```text
Type '(event: FormSubmitEvent<FormData>) => Promise<void>' is not assignable to type '(event: FormSubmitEvent<Record<string, any>>) => void'.
  Types of parameters 'event' and 'event' are incompatible.
    Type 'FormSubmitEvent<Record<string, any>>' is not assignable to type 'FormSubmitEvent<FormData>'.
      Type 'Record<string, any>' is missing the following properties from type 'FormData': email, password 
ts-plugin(2322)
```

For the component to be truly type-safe, the generic `T` inferred from the `resolver` must be applied to the `@submit` event and the `$form` slot property.

**Example Code:**

...
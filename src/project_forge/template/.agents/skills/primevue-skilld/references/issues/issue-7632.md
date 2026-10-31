---
number: 7632
title: initialValues reactive
type: other
state: open
created: 2025-04-22
url: "https://github.com/primefaces/primevue/issues/7632"
reactions: 18
comments: 3
labels: "[Status: Pending Review]"
---

# initialValues reactive

Currently, the initialValues prop on PrimeVue Forms is not reactive. Once it's set, it cannot be updated dynamically. As a workaround, I’ve been using v-if to force re-rendering of the form when values change. This approach is not ideal and introduces unnecessary complexity, especially in larger or dynamic forms.

The setValues method isn't a sufficient replacement, as it throws errors when trying to set values for fields that are not yet rendered or do not exist. This is particularly problematic when working with dynamic or conditionally loaded form components.

It would be much more flexible if the  component supported two-way binding with v-model, allowing reactive form value updates without relying on workarounds.

In my use case, I’ve built a DynamicFormTab component that loads tabbed form sections asynchronously. Using PrimeVue Forms in combination with Zod validation becomes challenging because:

Fields rendered conditionally (e.g., in drawers or tabs) are not always available in the DOM at validation time.

Zod fails to validate correctly unless all fields are already rendered.

This limitation makes working with dynamic forms, especially those using async data or complex UI patterns like drawers/tabs, very difficult.

for instance, check how regle does this, complete form validation bundle
https://reglejs.dev/



---

## Top Comments

**@IgorKha**:

same! +1

You can still partially solve the problem by setting `:key` for `Form`.
In my case, I load the form data from a json file (device settings), in which case I need to output the form again.
But `:key` doesn't solve the problem of implementing a reset button. when the user has fixed the form and needs to reset the values back to the original values, since there is no callback from the form.

```vue
<template>
...
  <Form
            v-else
            :key="formResetKey"
            :initialValues="initialValues"
            :resolver="formResolver"
            @submit="onSubmit"
          >
  ...
  </Form>
...
</template>
<script setup lang="ts">
const formResetKey = ref(0)
const isFormChanged = ref(false)

...

**@mjamro**:

# Workaround 

I use a workaround - a wrapper component that updates the `` by modifying 'key' whenever initial values changes. 

If this ticket will be resolved in future you can simply remove the wrapper with minimal impact on your code. 

## ResetOnChange.vue

```vue
<template>
    <slot :key="key" />
</template>

import { ref, watch } from 'vue';

const key = ref(0)

const props = defineProps<{
    value: any
}>()


watch(
    () => props.value,
    () => {
        key.value += 1; // Whenever watched value changes increment the key
    },
    { deep: true, immediate: true }
)

...

**@starredev** (+1):

I switched too https://vue-formify.matenagy.me

https://vue-formify.matenagy.me/docs/examples/third-party-components/

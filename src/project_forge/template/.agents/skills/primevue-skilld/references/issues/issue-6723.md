---
number: 6723
title: Cannot read `$form` form field states with TypeScript
type: bug
state: closed
created: 2024-11-04
url: "https://github.com/primefaces/primevue/issues/6723"
reactions: 21
comments: 10
labels: "[Type: Bug]"
---

# Cannot read `$form` form field states with TypeScript

### Describe the bug

I'm using the new forms API, and I get TypeScript errors when I try to access form field states on the `$form` object.

This code reproduces it. The template is just a copy/paste of some sample code in the Forms docs.

Accessing `$form.username` produces this error:

`Property 'username' does not exist on type '{ register: (field: string, options: any) => any; reset: () => void; valid: boolean; states: Record<string, FormFieldState>; }'`


```vue
<script setup lang="ts">
import { Form } from '@primevue/forms'
import Button from 'primevue/button'
</script>

<template>
  <Form v-slot="$form" class="flex flex-col gap-4 w-full sm:w-56">
    <div class="flex flex-col gap-1">
      <InputText name="username" type="text" placeholder="Username" fluid />
      <Message v-if="$form.username?.invalid" severity="error" size="small" variant="simple">
        {{ $form.username.error?.message }}
      </Message>
    </div>
    <Button type="submit" severity="secondary" label="Submit" />
  </Form>
</template>
```

### Reproducer

https://stackblitz.com/edit/primevue-4-ts-vite-issue-template-kef9dg?file=src%2FApp.vue

### PrimeVue version

4.2.1

### Vue version

3.x

### Language

TypeScript

### Build / Runtime

Vite

### Browser(s)

_No response_

### Steps to reproduce the behavior

_No response_

### Expected behavior

_No response_

---

## Top Comments

**@jackytank** (+14):

I have the same issue

**@fgrzesiak** (+4):

I have the same issue as well.

**@SimonOyaneder** (+3):

Same issue here
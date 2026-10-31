---
number: 6803
title: "Form field: Unable to build complex form field"
type: other
state: open
created: 2024-11-18
url: "https://github.com/primefaces/primevue/issues/6803"
reactions: 13
comments: 10
labels: "[Status: Pending Review]"
---

# Form field: Unable to build complex form field

### Describe the bug

I have a form with a complex field. By "complex" I mean that it consists of multiple inputs but logicaly it's one field with an object or array as a value. For example, I have a form with field "list". The value of that field should be an array of 2 elements. I implemented a component ListInput using primevue inputs and wrapped it with FormField. I bound my component value with `$field.value` but it doesn't work. Each input inside ListInput overwrites the value of the form field. So, when I type e.g. "foo" in the first input, I have form field value "foo" instead of `["foo", "..."]` 
I see in the source code of primevue how each component writes to the parent form field value:

```
methods: {
        writeValue(value, event) {
            if (this.controlled) {
                this.d_value = value;
                this.$emit('update:modelValue', value);
            }

            this.$emit('value-change', value);

            this.formField.onChange?.({ originalEvent: event, value }); // <-- each component overwrites parent form field value
        }
    },
``` 
But how can I then build a complex form field with prime vue components?

### Reproducer

https://stackblitz.com/edit/vitejs-vite-6ltjro?file=src%2FApp.vue

### PrimeVue version

4.2.2

### Vue version

3.x

### Language

ES6

### Build / Runtime

Vite

### Browser(s)

Chrome

### Steps to reproduce the behavior

1. Go to https://stackblitz.com/edit/vitejs-vite-6ltjro?file=src%2FApp.vue
2. Type "foo" in the very first input

Result: $form.list.value = "foo"


### Expected behavior

$form.list.value = ["foo", ""]
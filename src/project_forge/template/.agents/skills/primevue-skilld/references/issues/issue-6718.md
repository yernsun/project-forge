---
number: 6718
title: "SelectButton: allowEmpty does not stop unselecting"
type: bug
state: closed
created: 2024-11-02
url: "https://github.com/primefaces/primevue/issues/6718"
reactions: 18
comments: 6
labels: "[Type: Bug]"
---

# SelectButton: allowEmpty does not stop unselecting

### Describe the bug

When using the `SelectButton` and `:allow-empty="false"` a user can still deselect the currently selected item by clicking it again.

### Reproducer

https://stackblitz.com/edit/primevue-4-vite-issue-template-htijut?file=src%2FApp.vue

### PrimeVue version

4.0.4

### Vue version

4.x

### Language

TypeScript

### Build / Runtime

Vue CLI App

### Browser(s)

Chrome

### Steps to reproduce the behavior

1. Specify `:allow-empty="false"` on `SelectButton`
2. Try to deselect the value

### Expected behavior

`:allow-empty="false"` should restrict the user from deselecting
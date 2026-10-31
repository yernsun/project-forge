---
number: 7339
title: "DataTable: \"Row Group\" doesn't work correctly with virtual scrolling"
type: other
state: open
created: 2025-02-27
url: "https://github.com/primefaces/primevue/issues/7339"
reactions: 14
comments: 3
labels: "[Resolution: Needs Upvote :+1:]"
---

# DataTable: "Row Group" doesn't work correctly with virtual scrolling

### Describe the bug

DataTable's "Row Group" doesn't work correctly with virtual scrolling, past the initial list of items loaded, it breaks and apparently tries to inset the group header after each item, also there's a slight spacing between the group header and table header under which items scrolling up can be partially seen, but that seems like a general style issue and not related to virtual scrolling per se.

### Pull Request Link

_No response_

### Reason for not contributing a PR

- [x] Lack of time
- [x] Unsure how to implement the fix/feature
- [ ] Difficulty understanding the codebase
- [ ] Other

### Other Reason

_No response_

### Reproducer

https://stackblitz.com/edit/primevue-4-vite-issue-template-6kwoifer?file=src%2FTable.vue

### Environment

Windows 11, Visual studio code 

### Vue version

3.5.13

### PrimeVue version

4.3.1

### Node version

23.6.0

### Browser(s)

_No response_

### Steps to reproduce the behavior

NA

### Expected behavior

Same behavior as a table with virtual scroll disabled
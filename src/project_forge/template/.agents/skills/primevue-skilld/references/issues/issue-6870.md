---
number: 6870
title: "DataTable: Issue with VirtualScroller and Scrollable Property"
type: question
state: open
created: 2024-11-26
url: "https://github.com/primefaces/primevue/issues/6870"
reactions: 10
comments: 6
labels: "[Resolution: Help Wanted, Resolution: Needs Upvote :+1:]"
---

# DataTable: Issue with VirtualScroller and Scrollable Property

### Describe the bug

I encountered an issue when adding elements to a DataTable with virtualScrollerOptions defined and scrollable set to true. The new items are not displayed as expected.

### Reproducer

https://stackblitz.com/edit/rhdwyc-uvkxvq?file=src%2FApp.vue

### PrimeVue version

4.2.3

### Vue version

4.x

### Language

ALL

### Build / Runtime

Vite

### Browser(s)

Firefox, Chrome, Edge

### Steps to reproduce the behavior

- Define virtualScrollerOptions in a DataTable.
- Set scrollable to true
- Set scrollHeight to flex
- Add new items to the DataTable.
- Observe that the new items are not displayed.

### Expected behavior

Newly added items should be displayed in the DataTable even when virtualScrollerOptions are defined and scrollable is set to true.
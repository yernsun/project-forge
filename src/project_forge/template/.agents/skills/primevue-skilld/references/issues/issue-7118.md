---
number: 7118
title: "DataTable onRowClick should support \"Open Link in New Tab\" and right-click context menu functionality."
type: other
state: open
created: 2025-01-20
url: "https://github.com/primefaces/primevue/issues/7118"
reactions: 12
comments: 3
labels: "[Resolution: Needs Upvote :+1:]"
---

# DataTable onRowClick should support "Open Link in New Tab" and right-click context menu functionality.

### Describe the bug

Currently, the onRowClick event in the PrimeVue DataTable does not support the browser's default behavior for:

Ctrl + Click (Windows/Linux) or Cmd + Click (macOS) to open a link in a new tab.
Right-clicking to access the browser's context menu, which includes options like "Open link in new tab.

This limitation forces us to create workarounds, such as overlaying tags styled with position: absolute to cover the row or implementing custom context menus, both of which result in a ugly way.



### Pull Request Link

_No response_

### Reason for not contributing a PR

- [x] Lack of time
- [ ] Unsure how to implement the fix/feature
- [ ] Difficulty understanding the codebase
- [ ] Other

### Other Reason

_No response_

### Reproducer

https://stackblitz.com/edit/primevue-4-vite-issue-template-9xe3khwc?file=src%2FApp.vue

### Environment

4.2.5 primevue version, 

### Vue version

3.5.13

### PrimeVue version

4.2.5

### Node version

20.9.0

### Browser(s)

chrome, safari

### Steps to reproduce the behavior

Create a DataTable with an onRowClick event.
Attempt to:
Ctrl + Click (Windows/Linux) or Cmd + Click (macOS) a row → It does not open in a new tab.
Right-click on a row → The browser's context menu does not provide the "Open link in new tab" option.


### Expected behavior

it should allow for the right click "open link in new tab" without the need to add <a> links in each row
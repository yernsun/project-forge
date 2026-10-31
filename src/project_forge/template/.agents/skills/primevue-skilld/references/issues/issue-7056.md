---
number: 7056
title: DataTable row selection slow on larger tables
type: question
state: open
created: 2025-01-08
url: "https://github.com/primefaces/primevue/issues/7056"
reactions: 6
comments: 2
labels: "[Resolution: Help Wanted]"
---

# DataTable row selection slow on larger tables

### Describe the bug

When rendering a `DataTable` that has more than a few columns or a larger amount of rows, it leads to slow rendering of the `DataTable` and very slow responding checkboxes when selecting a row. The underlying issue seems to be that a row selection re-renders the whole table, and the rendering itself being slow.



I assume the re-render of the whole table when selecting a row is a bug. Possibly related to https://github.com/primefaces/primevue/issues/5309

### Pull Request Link

_No response_

### Reason for not contributing a PR

- [ ] Lack of time
- [x] Unsure how to implement the fix/feature
- [X] Difficulty understanding the codebase
- [ ] Other

### Other Reason

_No response_

### Reproducer

https://stackblitz.com/edit/ui2jyp9p-v9bun1mf

### Environment

-

### Vue version

3.5

### PrimeVue version

4.2.x

### Node version

_No response_

### Browser(s)

_No response_

### Steps to reproduce the behavior

Create any table with row selection. As soon as there are around 1000 cells (height * width) the delay between click and selection becomes very noticable.

### Expected behavior

Row-selection feels instantaneous and there is no re-rendering of all cells in the row, let alone all rows, necessary.
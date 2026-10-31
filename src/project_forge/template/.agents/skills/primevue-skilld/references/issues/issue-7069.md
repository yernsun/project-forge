---
number: 7069
title: Custom filter model causes error when inside a column group
type: feature
state: open
created: 2025-01-09
url: "https://github.com/primefaces/primevue/issues/7069"
reactions: 22
comments: 7
labels: "[Type: Enhancement, Resolution: Needs Upvote :+1:]"
---

# Custom filter model causes error when inside a column group

### Describe the bug

When the ColumnGroup type attribute is set on the columngroup, it is possible to filter using displayFilter: row. However, we need to use displayFilter: menu as our filters are slightly more complex. This is currently not working as of PrimeVue v4.2.4
<img width="1650" alt="image" src="https://github.com/user-attachments/assets/44b813c0-a72e-4293-9c25-3e2fc2931b12" />

### Pull Request Link

_No response_

### Reason for not contributing a PR

- [X] Lack of time
- [X] Unsure how to implement the fix/feature
- [ ] Difficulty understanding the codebase
- [ ] Other

### Other Reason

_No response_

### Reproducer

https://stackblitz.com/edit/vitejs-vite-m3gnvfyz?file=src%2FApp.vue

### Environment

vite version 5.4.2

### Vue version

3.2.25

### PrimeVue version

4.2.4

### Node version

_No response_

### Browser(s)

_No response_

### Steps to reproduce the behavior

1. Create a DataTable
2. Add Column Grouping to the data table
3. Add a filter template to the data table
4. On the ColumnGroup component tag add `type="header"`
5. See the Grouping header disappear and not having any filter

### Expected behavior

We expect having Column group and the menu filter on the group headers 
<img width="582" alt="image" src="https://github.com/user-attachments/assets/c03c342a-de08-48db-adc0-aad552f294b5" />


---

## Top Comments

**@Emily-ejag** (+7):

This bug did not exist on `version 3.43.0` @tugcekucukoglu @cagataycivici 

**@jo87jimmy** (+9):

I have the same problem

**@jyeatman** (+3):

I'm having the same issue
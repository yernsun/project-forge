---
number: 7630
title: "feat(datatable): add generateCSV() to separate CSV generation from export logic"
type: feature
state: open
created: 2025-04-22
url: "https://github.com/primefaces/primevue/issues/7630"
reactions: 17
comments: 3
labels: "[Type: Enhancement, Resolution: Needs Upvote :+1:]"
---

# feat(datatable): add generateCSV() to separate CSV generation from export logic

### Describe the bug

We need to separate the concerns of CSV generation and file download in PrimeVue’s DataTable. The new generateCSV(options, data) method returns the raw CSV string so that consumers can access and manipulate the CSV content directly (for previewing, sending via API, copying to clipboard, etc.) instead of immediately triggering a download. The existing exportCSV(options, data) is updated to simply call generateCSV(...) and then handle the final download step, preserving backward‑compatible behavior.

### Pull Request Link

https://github.com/primefaces/primevue/pull/7629

### Reason for not contributing a PR

- [ ] Lack of time
- [ ] Unsure how to implement the fix/feature
- [ ] Difficulty understanding the codebase
- [ ] Other

### Other Reason

_No response_

### Reproducer

https://stackblitz.com/edit/3zpwcehb?file=src%2FApp.vue

### Environment

Tested on Windows with Chrome.

### Vue version

3.5.13

### PrimeVue version

4.3.3

### Node version

22.13.0

### Browser(s)

_No response_

### Steps to reproduce the behavior

Go to stackblitz url and run te code

### Expected behavior

When calling the DataTable’s export routine, the CSV‑generation step is factored out into a new generateCSV(options, data) method that returns the raw CSV string without triggering a download. The existing exportCSV(options, data) should simply invoke generateCSV(...) and then perform the file‑download step. This allows me to call generateCSV() directly to retrieve the CSV content (for previewing, converting to Excel, sending via API, etc.) and preserves the original download behavior in exportCSV().

---

## Top Comments

**@LuisCasanova11**:

[https://github.com/orgs/primefaces/discussions/444#discussion-5843556](url)

**@github-actions**:

Thanks a lot for this issue! PrimeTek's own vision for PrimeVue is demanding, but community feedback is crucial in prioritization. The more upvotes help ensure this fix can be addressed quickly or the related PR can be merged soon.

**@nneto**:

Was just looking for this and I saw it's included in the 4.3.5 release. Thank you!
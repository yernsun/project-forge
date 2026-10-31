---
number: 7218
title: Add appendTo property to Toast
type: other
state: open
created: 2025-02-07
url: "https://github.com/primefaces/primevue/issues/7218"
reactions: 19
comments: 2
labels: "[Resolution: Needs Upvote :+1:]"
---

# Add appendTo property to Toast

### Describe the bug

Despite being added to the react version of Prime, this does not appear to be present in PrimeVue.

As the issue previously mentioned, as an overlay component, the Toast component _should_ have an ability to append the toast message to the root html element.

Especially now that PrimeVue 4 puts the toasts inside of the body, this causes Toasts to shift significantly when dialog windows are opened and closed, and the toast is still visible.

The layout shift issue mentioned in #6089 which is caused by the --scrollbar-width not being defined (which we've resolved ourselves), is the culprit here since it adds scrollbar-width padding to the right side of the body. I am almost certain once #6089 is fixed (which it appears to be, and will be in the next release) is implemented, people will being to notice this shifting bug in the toasts. Toasts are very common upon dialog close/opens, and the shifting that occurs on the toasts is very jarring.

It would be fantastic if these two issues could be fixed simultaneously in the next release. 

### Pull Request Link

_No response_

### Reason for not contributing a PR

- [ ] Lack of time
- [x] Unsure how to implement the fix/feature
- [ ] Difficulty understanding the codebase
- [ ] Other

### Other Reason

_No response_

### Reproducer

https://stackblitz.com/edit/primevue-4-vite-issue-template-46nw9c1j?file=src%2FApp.vue

### Environment

n/a

### Vue version

3.4.29

### PrimeVue version

4.2.5

### Node version

20

### Browser(s)

_No response_

### Steps to reproduce the behavior

1. Trigger a Toast when the dialog window opens or closes

### Expected behavior

The ability for Toasts to have an appendTo option, OR revert back to the Toasts being in the root html element. These were not issues in PrimeVue 3.

---

## Top Comments

**@agarny**:

I have used `Dialog`'s `appendTo` prop in the past and I needed to do something similar for `Toast`, but... to my surprise, I found out that `Toast` doesn't have an `appendTo` prop. Why is that? This seems inconsistent to me, especially if it is present in PrimeReact.

**@github-actions**:

Thanks a lot for this issue! PrimeTek's own vision for PrimeVue is demanding, but community feedback is crucial in prioritization. The more upvotes help ensure this fix can be addressed quickly or the related PR can be merged soon.
---
number: 7737
title: "DatePicker: Clear button not working"
type: bug
state: closed
created: 2025-05-20
url: "https://github.com/primefaces/primevue/issues/7737"
reactions: 18
comments: 10
resolvedIn: 4.3.10
labels: "[Type: Bug]"
---

# DatePicker: Clear button not working

### Describe the bug

The clear button in the DatePicker component is not resetting the selected date.

### Pull Request Link

fix(DatePicker): update clear button to use defaultValue instead of formDefaultValue #7736

### Reproducer

https://primevue.org/datepicker/#button

### Environment

Latest PrimeVue 4.3.4

### Vue version

3

### PrimeVue version

4.3.4

### Node version

22.15.0

### Browser(s)

Chrome

### Steps to reproduce the behavior

Use DatePicker with "showButtonBar" and try to click on the "clear" button.

### Expected behavior

It should clear the input field.

---

## Top Comments

**@cagataycivici** [maintainer] (+2):

We'll discuss for 4.3.10, thank you for the feedback.

**@msg-jstren** (+6):

Waiting for it too. Would be great if the clear button works as expected. On the usability site it is useless like this

**@livanovvisma** (+5):

Any chance this is going to be merged soon?
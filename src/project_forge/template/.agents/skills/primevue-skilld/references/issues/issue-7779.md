---
number: 7779
title: Datatable component documentation (v4) scrolling was uncontrollable when scroll reached to 'Scroll' topic
type: bug
state: closed
created: 2025-06-02
url: "https://github.com/primefaces/primevue/issues/7779"
reactions: 18
comments: 6
labels: "[Type: Bug]"
---

# Datatable component documentation (v4) scrolling was uncontrollable when scroll reached to 'Scroll' topic

### Describe the bug

Datatable documentation (https://primevue.org/datatable/) scrolling is uncontrollable. when scroll has reached 'Scroll' content, page scrolling automatically reached to the bottom of the page



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

https://primevue.org/datatable/#rowgroup_subheader

### Environment

UI issue has found in the Chrome & Edge browser

### Vue version

4.0.0

### PrimeVue version

4.0.0

### Node version

_No response_

### Browser(s)

Chrome 136

### Steps to reproduce the behavior

1. Go to https://primevue.org/datatable/
2. Scroll the documentation content upto "scroll" topic
3. you can see auto-scrolling and page has reached down. I am unable to see the content of "Row Group" due to this scroll issue

### Expected behavior

Scrolling should be under human control and able to see entire documentation content without any hectic



---

## Top Comments

**@CodaKris** (+1):

If I zoom out to 90% or less I don't get the issue - tested in FF and Safari.

**@lukas-pierce**:

Currently, I'm using a debugger trick to freeze the scroll. 



**@Hassanbhb**:

The issue seems to be related to the right navigation, the scroll works as intended as long as I am withing the visible navigation links, the moment i go lower than the visible part of the right nav, the bug happens. 

found this out when i tried to zoom out ( in my case had to zoom out to 70%)
---
number: 6616
title: "Popover: Popover position is not relatively calculated when using append-to=self. This causes aligment problems in a fixed element."
type: bug
state: open
created: 2024-10-21
url: "https://github.com/primefaces/primevue/issues/6616"
reactions: 20
comments: 14
labels: "[Type: Bug]"
---

# Popover: Popover position is not relatively calculated when using append-to=self. This causes aligment problems in a fixed element.

### Describe the bug

When using Popover in a fixed element and setting append-to=self, the position of the Popover is calculated absolutely. This causes the Popover to appear in the wrong place. (See the reproducer)  I think the solution to this problem is quite simple if you look at how this problem was solved in the Select Component:
```
   //Select.vue
   alignOverlay() {
            if (this.appendTo === 'self') {
                relativePosition(this.overlay, this.$el);
            } else {
                this.overlay.style.minWidth = getOuterWidth(this.$el) + 'px';
                absolutePosition(this.overlay, this.$el);
            }
        },
```
Here, the relative position is used to determine the position of the overlay when using appendTo=self, which results in correct positioning.

### Reproducer

https://stackblitz.com/edit/primevue-4-vite-issue-template-gak546?file=src%2FApp.vue

### PrimeVue version

4.1.0

### Vue version

4.x

### Language

TypeScript

### Build / Runtime

Vue CLI App

### Browser(s)

_No response_

### Steps to reproduce the behavior

Create a fixed div element and put a Popover Component inside. Set append-to="self". Add enough content outside of the fixed element to allow for scrolling.

### Expected behavior

The Popover should appear next to the target.

---

## Top Comments

**@arthaud-proust** (+7):

Hi, concerned by this issue too
It would be very helpful to append Popover to target element rather than on body 

**@mourad1081** (+4):

This bug is pending for almost a year now. Is it part of a future release?

**@nyerslaszlo** (+1):

> > Just ran into this. Does anyone know a hack or workaround?
> 
> I have already tried a few things, but unfortunately nothing has been successful. The only “solution” for me now was to omit append-to=“self”. Then the popover is displayed in the right place first. But of course it doesn't work when the user scrolls.

It isn't just the popover. Tooltips, menus, and other overlay elements that are appended to the body can move away on fixed elements when the body scrolled. A workaround could be the following:

...
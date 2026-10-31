---
number: 7133
title: Tailwind 4 support
type: other
state: closed
created: 2025-01-23
url: "https://github.com/primefaces/primevue/issues/7133"
reactions: 48
comments: 32
labels: "[Status: Pending Review]"
---

# Tailwind 4 support

### Describe the bug

Tailwind 4 has been released. It does not use postcss anymore but Vite plugin and does not use .js file for config but all config goes in .css file. The instructions on PrimeVue Tailwind are wrong now with Tailwind 4. Lots of things have changed in Tailwind 4, including classes, layers, variables etc. Also the instructions on tailwind.primevue.org is out of date now.

https://tailwind.primevue.org/nuxt/



### Pull Request Link

_No response_

### Reason for not contributing a PR

- [ ] Lack of time
- [ ] Unsure how to implement the fix/feature
- [ ] Difficulty understanding the codebase
- [ ] Other

### Other Reason

_No response_

### Reproducer

https://tailwind.primevue.org/nuxt/

### Environment

n/a

### Vue version

3.5.13

### PrimeVue version

4.2.5

### Node version

20

### Browser(s)

_No response_

### Steps to reproduce the behavior

n/a

### Expected behavior

n/a

---

## Top Comments

**@martinszeltins** (+7):

> According to upgrade guide, you can still use a js config file. The automated upgrade process will destroy your existing tailwind.config.js, but one can easily revert the deletion in git.

The tailwind.config.js is now depracated and you shouldn't be using it. You should instead use a .css file for all your config.



**@martinszeltins** (+4):

@OscarRaizer These styles do not look right with Tailwind 4 - https://tailwind.primevue.org/nuxt/#styles

**@janderegg** (+1):

I've got a Tailwind 4 version working using the official upgrade tool:
**npx @tailwindcss/upgrade@next**

First, I've got this error:

_ERROR  Cannot start nuxt:  It looks like you're trying to use tailwindcss directly as a PostCSS plugin. The PostCSS plugin has moved to a separate package, so to continue using Tailwind CSS with PostCSS you'll need to install @tailwindcss/postcss and update your PostCSS configuration._


Fixed that by installing @tailwindcss/postcss:
**npm install tailwindcss @tailwindcss/postcss postcss**
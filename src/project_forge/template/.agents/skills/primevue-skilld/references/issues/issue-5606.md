---
number: 5606
title: "Editor: `v-model` not updating with Quill v2.0"
type: bug
state: closed
created: 2024-04-17
url: "https://github.com/primefaces/primevue/issues/5606"
reactions: 25
comments: 43
labels: "[Type: Bug]"
---

# Editor: `v-model` not updating with Quill v2.0

### Describe the bug

Quill v2.0 is now officially released (see https://github.com/quilljs/quill/releases). PrimeVue's docs state to simply run
```
npm install quill
```
to make the Editor component work. Displaying and editing the text inside the editor works just fine, but directly manipulating the `v-model` value does not. This issue was mentioned here as well:
- #5381 

I know that there are plans to replace Quill with a custom solution (mentioned in a discussion here), but until then a fix for this issue would be very appreciated.

### Reproducer

https://stackblitz.com/edit/primevue-create-vue-issue-template-fsd4z9

### PrimeVue version

3.51.0

### Vue version

3.x

### Language

ALL

### Build / Runtime

Vite

### Browser(s)

_No response_

### Steps to reproduce the behavior

1. Use the Editor component
2. Set/update the `v-model` value

### Expected behavior

The content of the Editor should change. It does not.

---

## Top Comments

**@agm1984** (+21):

> What you guys did? i cant understand, im already using quill 2.0.0, and still not working the getting the value

I left quill at version 1.3.7 until v2 is supported.

```
$ npm uninstall --save quill
$ npm install --save quill@^1.3.7
```


**@arikardnoir** (+8):

> > What you guys did? i cant understand, im already using quill 2.0.0, and still not working the getting the value
> 
> I left quill at version 1.3.7 until v2 is supported.
> 
> ```
> $ npm uninstall --save quill
> $ npm install --save quill@^1.3.7
> ```

Many thanks @agm1984, it works for me

**@pedrodruviaro** (+15):

Same thing here. The editor works to write new texts. To edit something is not working
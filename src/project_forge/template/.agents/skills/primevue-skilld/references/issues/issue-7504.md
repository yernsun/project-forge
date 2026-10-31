---
number: 7504
title: InputNumber behaviour .fill in playwright
type: question
state: open
created: 2025-03-25
url: "https://github.com/primefaces/primevue/issues/7504"
reactions: 8
comments: 4
labels: "[Resolution: Help Wanted]"
---

# InputNumber behaviour .fill in playwright

### Describe the bug

We discovered flacky behaviour during end to end tests with playwright in our application, that occurs when filling out forms with InputNumber component fields using `.fill` method via `playwright`.

Especially this can be seen , if a form is prefilled with values, e.g. when editing data, and then the test performs changes and fills out fields. While this works reliable for input text, number fields are not always updated accordingly to the specified value triggered by `.fill`. 

It seems like this is a behaviour that is related to this ticket we found created in playwright from another user: https://github.com/microsoft/playwright/issues/33623#issuecomment-2479146808. 
Maybe it is also related to this: https://github.com/primefaces/primevue/issues/3851#issuecomment-2029097386

The reason is that the component itself seems to not listen on the "native" browser events, so filling it out automatically with `.fill` or even emulating user typing behaviour with something like `.press` or `.pressSequentially` did not help either and leads to flacky behaviour as well (looks like sometimes the input is not ready to accept all key binding events, like Controll keys).

Since this is flacky and also this seems to be a specific decision to design the component like it currently is, it was hard for us to create a PR. But the current situation makes it hard or nearly impossible to reliably integrate end to end tests for our application. 

### Pull Request Link

...
---
number: 7289
title: SSR with Vite – Styles Are Not Included in Server-Rendered HTML
type: other
state: open
created: 2025-02-20
url: "https://github.com/primefaces/primevue/issues/7289"
reactions: 17
comments: 7
labels: "[Status: Pending Review]"
---

# SSR with Vite – Styles Are Not Included in Server-Rendered HTML

#### **Issue Description**  
When using **PrimeVue 4 with Vite SSR**, styles are not included in the **server-rendered HTML**. Since PrimeVue components inject their styles when mounted, this works fine for CSR. However, in SSR, the styles are missing until hydration occurs, causing a **flash of unstyled content (FOUC)**.  

Unlike Nuxt (which has a module for handling this), **there’s no documented solution for Vite SSR**.  

#### **Expected Behavior**  
PrimeVue should provide an **official method** for injecting styles into the server-rendered output so that the page is **fully styled upon initial load**.  

#### **Current Workaround**  
To avoid FOUC, I manually extract and inject styles **after `renderToString`**, like this:  

```javascript
/// Imports
import { Theme } from '@primeuix/styled'
import { Base, BaseStyle } from '@primevue/core'

/// Before renderToString
let usedStyles = new Set()
Base.setLoadedStyleName = async (name) => usedStyles.add(name)

/// After renderToString
const styleSheets = []
styleSheets.push(`<style type="text/css" data-primevue-style-id="layer-order">${
  BaseStyle.getLayerOrderThemeCSS()}</style>`)
BaseStyle.getLayerOrderThemeCSS()

styleSheets.push(Theme.getCommonStyleSheet())
for(const name of usedStyles) {
  styleSheets.push(Theme.getStyleSheet(name))
  const styleModule = await import(`primevue/${name}/style`)
  styleSheets.push(styleModule.default.getThemeStyleSheet())
}
styleSheets.push(BaseStyle.getThemeStyleSheet())

renderedHead.headTags += styleSheets.join('\n')
```


Would love to hear if there’s an official approach to handling this!   


---

## Top Comments

**@ashniazi** (+3):

@tugcekucukoglu Touching base, this still seems to still be an issue.

I'm on Inertia, Tailwind, PrimeVue, Vite and had issues with the FOUC for SSR as well. The above solutions by @MLaszczewski and @gquittet really helped me getting it somewhat resolved albeit too much trial and error, and source diving... For context I'm using a custom style that extends the aura preset.

...

**@gquittet**:

@tugcekucukoglu  @cagataycivici @mertsincan 

Based on the above solution, I wrote this workaound to fix the issue but I can't load the CSS variables.
I had to use `ts-expect-error` because some JavaScript parts are wrongly typed.

...

**@gquittet** (+1):

> Is there an ETA on this?

@CMeyerOS 

Not at all. The issue is still in review as I can see but I don't think anyone is working on it.

What you can do is to use one of the suggested workarounds (see above answers) or make a PR.

Unfortunately, my knowledge of primevue is very limited and because of that I can't write a PR myself to help the project.
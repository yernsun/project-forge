---
number: 1888
title: "Tree and TreeTable: Scroll performance (big amount data) (virtual scrolling)"
type: question
state: open
created: 2021-12-14
url: "https://github.com/primefaces/primevue/issues/1888"
reactions: 14
comments: 14
labels: "[Resolution: Help Wanted, Resolution: Needs Upvote :+1:]"
---

# Tree and TreeTable: Scroll performance (big amount data) (virtual scrolling)

This is true for all components that are currently in place.
Especially for Tree

Add virtual scrolling for Tree

The problem is that there are a lot of objects in my tree. There are a lot of objects in the DOM when nodes are open. Because of this, the entire UI starts to slow down terribly.

It is necessary to make scrolling virtualization for all components that have scrolling and display data

i.e. do something like this: https://vuejsexamples.com/a-vue-component-support-big-amount-data-list-with-high-scroll-performance/

This is very critical for me.
Please do something as quickly as possible.
Paginator is not always available for specific tasks

You can take another component for virtualization and apply it to your components
(https://www.vuescript.com/best-virtual-scrolling/)




EDIT: 
https://primefaces.org/primevue/showcase/#/virtualscroller

As I understand it, you already have a virtual scroll.

Use it in the component Tree and TreeTable please.

This is a very high priority.


Ideally, wherever there are lists and scroll to use it
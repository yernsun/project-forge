---
number: 6076
title: "DataView & DataTable: pass type of value prop into slotProps etc."
type: other
state: open
created: 2024-07-17
url: "https://github.com/primefaces/primevue/issues/6076"
reactions: 19
comments: 0
---

# DataView & DataTable: pass type of value prop into slotProps etc.

Would it be possible to pass the type of the `value` prop to the slot props?

### Example

In this example, the DataView component has knowledge about the type of its `value` prop, which is the type of `products` (`Array<Product>`), so I imagine it could be possible to pass this type to the list slots's `items` prop.



I am pretty sure in the case of the DataView component that this should be possible. Same with DataTable's own slots `groupheader`, `groupfooter`, `expansion` aswell as DataTable's `DataTableExportFunctionOptions` and own Events `DataTableRowClickEvent`, `DataTableRowSelectEvent` etc.

In case of the Column component I am not sure because it being a separate component. Ideally the `data` prop of the Column's `body`, `editor` and `loading` slots should get passed the type of a single array element of the parent DataTable's `value` prop.

BTW: the list of components, slot props, events etc. I mentioned in this issue, where this could possibly be implemented, is not exhaustive.
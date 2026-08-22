# Frontend and i18n

Vue Query owns remote data and invalidation. Pinia owns browser-only state such as the chosen locale.
OpenAPI generates transport types; feature adapters map those DTOs into view models when necessary.

Both `zh-CN` and `en-US` must contain identical key sets. Locale selection is persisted, updates the
document language, and synchronizes PrimeVue's locale object from the same source.

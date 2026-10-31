---
number: 6739
title: "DatePicker: manual input not working"
type: bug
state: closed
created: 2024-11-07
url: "https://github.com/primefaces/primevue/issues/6739"
reactions: 22
comments: 10
labels: "[Type: Bug]"
---

# DatePicker: manual input not working

### Describe the bug

The DatePicker default behaviour is manualnput true, which, if I'm understanding correctly, is supposed to allow typing the date with the keyboard. That is not working. Directly in the examples exposed in the documentation happens. 

### Reproducer

https://stackblitz.com/edit/u9znrf-r6br5k?file=src%2FApp.vue

### PrimeVue version

4.2.1

### Vue version

3.x

### Language

TypeScript

### Build / Runtime

Vite

### Browser(s)

_No response_

### Steps to reproduce the behavior

Try to introduce a date in the datepicker with the manualInput set to true (or not specified, as the default is true)

### Expected behavior

Allow user to introduce the dates manually

---

## Top Comments

**@KumJungMin** (+6):

If no one is working on fixing this bug, would it be okay for me to fix it? :)

**@eyal-egf** (+2):

> I have a requirement for the manual input to work in mobile as well... does anyone know if this feature is supposed to work or is planned to work for mobile devices? (currently it does not)

If anyone else needs the manual input to work in mobile, I was able to have it working by add the inputmode attr to the inner input component >>
```
<DatePicker
              :name="field.name"
              :showIcon="true"
              class="w-full"
              id="date_of_birth"
              iconDisplay="input"
              placeholder="DD/MM/YYYY"
              :pt="{
                pcinputtext: {
                  root: {
                    inputmode: 'text'
                  }
                }
              }"
            />
```...

**@viniciusNoleto**:

Same issue here 🏻

- **Vue:** `3.4.10`
- **Nuxt:** `3.10.2`
- **Primevue:** `4.2.1`
- **Vite:** `5.4.0`
<script setup lang="ts">
import Button from 'primevue/button'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const email = ref('')
const password = ref('')
const loading = ref(false)
const failed = ref(false)

async function login(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.value, password: password.value }),
    })
    if (!response.ok) throw new Error('login failed')
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="content-card auth-card">
    <h2 v-text="t('auth.title')" />
    <form class="create-form" @submit.prevent="login">
      <label class="field">
        <span v-text="t('auth.email')" />
        <input v-model.trim="email" type="email" autocomplete="email" required />
      </label>
      <label class="field">
        <span v-text="t('auth.password')" />
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <Button type="submit" :label="t('auth.login')" :loading="loading" />
    </form>
    <p v-if="failed" class="error-message" v-text="t('auth.loginError')" />
  </section>
</template>

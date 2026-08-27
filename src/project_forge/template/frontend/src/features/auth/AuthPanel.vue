<script setup lang="ts">
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Message from 'primevue/message'
import Password from 'primevue/password'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  ApiRequestError,
  login,
  signup,
  type LoginDto,
  type SessionDto,
  type SignupDto,
} from '@/shared/api/client'

import { applySessionTransition, authErrorTranslationKey } from './session'

type Mode = 'login' | 'signup'

const { t } = useI18n()
const queryClient = useQueryClient()
const mode = ref<Mode>('login')
const email = ref('')
const password = ref('')
const workspaceName = ref('')
const clientErrorKey = ref<string | null>(null)

const loginMutation = useMutation({ mutationFn: (input: LoginDto) => login(input) })
const signupMutation = useMutation({ mutationFn: (input: SignupDto) => signup(input) })
const activeMutation = computed(() => mode.value === 'login' ? loginMutation : signupMutation)
const pending = computed(() => activeMutation.value.isPending.value)
const activeError = computed(() => activeMutation.value.error.value)
const errorMessage = computed(() => {
  if (clientErrorKey.value) return t(clientErrorKey.value)
  const error = activeError.value
  if (!error) return null
  const key = authErrorTranslationKey(error) ?? 'auth.errors.unavailable'
  return t(key, {
    seconds: error instanceof ApiRequestError ? error.retryAfter ?? 0 : 0,
  })
})

watch([email, password, workspaceName], () => {
  clientErrorKey.value = null
})

function validate(): boolean {
  const normalizedEmail = email.value.trim()
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
    clientErrorKey.value = 'auth.errors.email_invalid'
    return false
  }
  if (!password.value) {
    clientErrorKey.value = 'auth.errors.password_required'
    return false
  }
  if (mode.value === 'signup' && password.value.length < 12) {
    clientErrorKey.value = 'auth.errors.password_too_short'
    return false
  }
  if (mode.value === 'signup' && !workspaceName.value.trim()) {
    clientErrorKey.value = 'auth.errors.workspace_required'
    return false
  }
  return true
}

function switchMode(next: Mode): void {
  mode.value = next
  loginMutation.reset()
  signupMutation.reset()
  clientErrorKey.value = null
}

async function acceptSession(session: SessionDto): Promise<void> {
  await applySessionTransition(queryClient, session)
}

async function submit(): Promise<void> {
  clientErrorKey.value = null
  if (!validate()) return
  try {
    if (mode.value === 'login') {
      await loginMutation.mutateAsync({ email: email.value.trim(), password: password.value }).then(acceptSession)
      return
    }
    await signupMutation.mutateAsync({
      email: email.value.trim(),
      password: password.value,
      workspaceName: workspaceName.value.trim(),
    }).then(acceptSession)
  } catch {
    // The active mutation exposes the localized error state in the form.
  }
}
</script>

<template>
  <section class="content-card auth-card" aria-labelledby="auth-title">
    <div class="auth-heading">
      <div>
        <p class="eyebrow" v-text="t('auth.eyebrow')" />
        <h2 id="auth-title" v-text="t(mode === 'login' ? 'auth.loginTitle' : 'auth.signupTitle')" />
      </div>
      <div class="auth-mode" role="group" :aria-label="t('auth.mode')">
        <Button
          data-testid="auth-login-mode"
          :label="t('auth.login')"
          :severity="mode === 'login' ? 'primary' : 'secondary'"
          :variant="mode === 'login' ? undefined : 'text'"
          @click="switchMode('login')"
        />
        <Button
          data-testid="auth-signup-mode"
          :label="t('auth.signup')"
          :severity="mode === 'signup' ? 'primary' : 'secondary'"
          :variant="mode === 'signup' ? undefined : 'text'"
          @click="switchMode('signup')"
        />
      </div>
    </div>
    <form class="auth-form" @submit.prevent="submit">
      <label class="field">
        <span v-text="t('auth.email')" />
        <InputText v-model.trim="email" data-testid="auth-email" type="email" autocomplete="email" aria-describedby="auth-error" required fluid />
      </label>
      <label class="field">
        <span v-text="t('auth.password')" />
        <Password
          v-model="password"
          input-id="auth-password"
          :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
          :minlength="mode === 'signup' ? 12 : 1"
          :feedback="mode === 'signup'"
          toggle-mask
          required
          fluid
          :prompt-label="t('auth.passwordPrompt')"
          :weak-label="t('auth.passwordWeak')"
          :medium-label="t('auth.passwordMedium')"
          :strong-label="t('auth.passwordStrong')"
          aria-describedby="auth-error"
        />
      </label>
      <label v-if="mode === 'signup'" class="field">
        <span v-text="t('auth.workspaceName')" />
        <InputText v-model.trim="workspaceName" data-testid="auth-workspace-name" maxlength="120" aria-describedby="auth-error" required fluid />
      </label>
      <Button
        data-testid="auth-submit"
        type="submit"
        :label="t(mode === 'login' ? 'auth.login' : 'auth.signup')"
        :loading="pending"
        :disabled="pending"
      />
    </form>
    <Message v-if="errorMessage" id="auth-error" severity="error" :closable="false" role="alert">
      {{ errorMessage }}
    </Message>
  </section>
</template>

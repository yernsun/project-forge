<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Message from 'primevue/message'
import Select from 'primevue/select'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  ApiRequestError,
  createWorkspace,
  listWorkspaces,
  logout,
  type SessionDto,
  type WorkspaceDto,
} from '@/shared/api/client'

import { applySessionTransition, authErrorTranslationKey, authQueryKeys } from './session'
import { useWorkspaceStore } from './workspace'

const { t } = useI18n()
const queryClient = useQueryClient()
const workspaceStore = useWorkspaceStore()
const newWorkspaceName = ref('')
const props = defineProps<{ session: SessionDto }>()
const workspaceQueryKey = computed(() => [
  ...authQueryKeys.workspaces,
  props.session.userId,
] as const)
const workspacesQuery = useQuery({
  queryKey: workspaceQueryKey,
  queryFn: listWorkspaces,
  retry: false,
})
const workspaces = computed(() => workspacesQuery.data.value ?? [])

watch(
  [() => props.session.userId, () => workspacesQuery.data.value],
  ([userId, value]) => {
    workspaceStore.activate(userId)
    if (value !== undefined) workspaceStore.reconcile(userId, value)
  },
  { immediate: true },
)

const createMutation = useMutation({
  mutationFn: () => createWorkspace(newWorkspaceName.value),
  onSuccess: (workspace) => {
    queryClient.setQueryData<WorkspaceDto[]>(workspaceQueryKey.value, (current = []) => [
      ...current,
      workspace,
    ])
    workspaceStore.select(workspace.workspaceId)
    newWorkspaceName.value = ''
  },
})
const logoutMutation = useMutation({
  mutationFn: logout,
  onSuccess: async () => {
    await applySessionTransition(queryClient, null)
    queryClient.removeQueries({ queryKey: authQueryKeys.workspaces })
    queryClient.removeQueries({ queryKey: ['items'] })
    workspaceStore.deactivate()
  },
})
const operationError = computed(() => createMutation.error.value ?? logoutMutation.error.value)
const errorMessage = computed(() => {
  const error = operationError.value
  if (!error) return null
  return t(authErrorTranslationKey(error) ?? 'auth.errors.unavailable', {
    seconds: error instanceof ApiRequestError ? error.retryAfter ?? 0 : 0,
  })
})
</script>

<template>
  <section class="content-card workspace-bar" aria-labelledby="workspace-title">
    <div class="workspace-identity">
      <p class="eyebrow" v-text="t('auth.signedInAs')" />
      <h2 id="workspace-title">{{ session.email }}</h2>
    </div>
    <div class="workspace-actions">
      <label class="field workspace-select">
        <span v-text="t('auth.workspace')" />
        <Select
          v-model="workspaceStore.workspaceId"
          data-testid="workspace-select"
          :options="workspaces"
          option-label="name"
          option-value="workspaceId"
          :placeholder="t('auth.selectWorkspace')"
          :loading="workspacesQuery.isPending.value"
          fluid
          @change="workspaceStore.select(workspaceStore.workspaceId)"
        />
      </label>
      <form class="workspace-create" @submit.prevent="createMutation.mutate()">
        <label class="field">
          <span v-text="t('auth.newWorkspace')" />
          <InputText v-model.trim="newWorkspaceName" maxlength="120" required />
        </label>
        <Button
          type="submit"
          icon="pi pi-plus"
          :label="t('auth.createWorkspace')"
          :loading="createMutation.isPending.value"
          :disabled="!newWorkspaceName"
        />
      </form>
      <Button
        data-testid="auth-logout"
        severity="secondary"
        variant="outlined"
        icon="pi pi-sign-out"
        :label="t('auth.logout')"
        :loading="logoutMutation.isPending.value"
        @click="logoutMutation.mutate()"
      />
    </div>
    <Message v-if="workspacesQuery.isError.value" severity="error" :closable="false" role="alert">
      {{ t('auth.errors.workspaces_failed') }}
    </Message>
    <Message v-if="errorMessage" severity="error" :closable="false" role="alert">
      {{ errorMessage }}
    </Message>
  </section>
</template>

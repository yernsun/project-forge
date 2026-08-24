import { type QueryClient, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onMounted, onScopeDispose } from 'vue'

import {
  AUTH_UNAUTHORIZED_EVENT,
  ApiRequestError,
  getSession,
  type SessionDto,
} from '@/shared/api/client'

import { useWorkspaceStore } from './workspace'

export const authQueryKeys = {
  session: ['auth', 'session'] as const,
  workspaces: ['auth', 'workspaces'] as const,
}

export type AuthState = 'loading' | 'guest' | 'authenticated'

const stableAuthErrorCodes = new Set([
  'authentication_required',
  'invalid_credentials',
  'invalid_or_expired_session',
  'origin_not_allowed',
  'csrf_failed',
  'workspace_access_denied',
  'signup_disabled',
  'email_already_exists',
  'auth_rate_limited',
  'request_validation_failed',
])

export function authErrorTranslationKey(error: unknown): string | null {
  if (!(error instanceof ApiRequestError) || !stableAuthErrorCodes.has(error.code)) return null
  return `auth.errors.${error.code}`
}

export async function applySessionTransition(
  queryClient: QueryClient,
  session: SessionDto | null,
): Promise<void> {
  queryClient.setQueryData(authQueryKeys.session, session)
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: authQueryKeys.session, refetchType: 'none' }),
    queryClient.invalidateQueries({ queryKey: authQueryKeys.workspaces, refetchType: 'none' }),
  ])
}

export function useSessionState() {
  const queryClient = useQueryClient()
  const workspaceStore = useWorkspaceStore()
  const sessionQuery = useQuery({
    queryKey: authQueryKeys.session,
    queryFn: getSession,
    retry: false,
    staleTime: 60_000,
  })
  const session = computed<SessionDto | null>(() => sessionQuery.data.value ?? null)
  const state = computed<AuthState>(() => {
    if (sessionQuery.isPending.value) return 'loading'
    return session.value ? 'authenticated' : 'guest'
  })

  function markGuest(): void {
    queryClient.setQueryData(authQueryKeys.session, null)
    queryClient.removeQueries({ queryKey: authQueryKeys.workspaces })
    queryClient.removeQueries({ queryKey: ['items'] })
    workspaceStore.deactivate()
  }

  onMounted(() => window.addEventListener(AUTH_UNAUTHORIZED_EVENT, markGuest))
  onScopeDispose(() => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, markGuest))

  return { sessionQuery, session, state, markGuest }
}

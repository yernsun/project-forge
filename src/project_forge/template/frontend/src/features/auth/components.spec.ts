/* eslint-disable vue/one-component-per-file -- compact local stubs keep mounted behavior tests readable */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue, { usePrimeVue } from 'primevue/config'
import { defineComponent, nextTick, type PropType } from 'vue'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/app/App.vue'
import { i18n, primeLocales } from '@/shared/i18n'
import enUS from '@/shared/i18n/locales/en-US.json'
import zhCN from '@/shared/i18n/locales/zh-CN.json'
import {
  ApiRequestError,
  createWorkspace,
  getSession,
  listWorkspaces,
  login,
  logout,
  signup,
  type SessionDto,
  type WorkspaceDto,
} from '@/shared/api/client'

import AuthPanel from './AuthPanel.vue'
import { authQueryKeys } from './session'
import WorkspaceSwitcher from './WorkspaceSwitcher.vue'
import { useWorkspaceStore } from './workspace'

vi.mock('@/shared/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/shared/api/client')>('@/shared/api/client')
  return {
    ...actual,
    createWorkspace: vi.fn(),
    getSession: vi.fn(),
    listWorkspaces: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    signup: vi.fn(),
  }
})

const createWorkspaceMock = vi.mocked(createWorkspace)
const getSessionMock = vi.mocked(getSession)
const listWorkspacesMock = vi.mocked(listWorkspaces)
const loginMock = vi.mocked(login)
const logoutMock = vi.mocked(logout)
const signupMock = vi.mocked(signup)

const session: SessionDto = {
  userId: '00000000-0000-4000-8000-000000000001',
  email: 'person@example.test',
  expiresAt: '2026-01-02T00:00:00Z',
}

const ButtonStub = defineComponent({
  inheritAttrs: false,
  props: {
    disabled: { type: Boolean, default: false },
    label: { type: String, default: '' },
    loading: { type: Boolean, default: false },
    type: { type: String, default: 'button' },
  },
  emits: ['click'],
  template: `
    <button
      v-bind="$attrs"
      :type="type"
      :disabled="disabled || loading"
      @click="$emit('click', $event)"
    ><span v-text="label" /><slot /></button>
  `,
})

const InputStub = defineComponent({
  inheritAttrs: false,
  props: {
    inputId: { type: String, default: undefined },
    modelValue: { type: String, default: '' },
    type: { type: String, default: 'text' },
  },
  emits: ['update:modelValue'],
  setup(_props, { emit }) {
    const update = (event: Event) => {
      emit('update:modelValue', (event.target as HTMLInputElement).value)
    }
    return { update }
  },
  template: `
    <input
      v-bind="$attrs"
      :id="inputId"
      :type="type"
      :value="modelValue"
      @input="update"
    />
  `,
})

const SelectStub = defineComponent({
  inheritAttrs: false,
  props: {
    modelValue: { type: String, default: null },
    optionLabel: { type: String, required: true },
    optionValue: { type: String, required: true },
    options: {
      type: Array as PropType<Array<Record<string, string>>>,
      default: () => [],
    },
  },
  emits: ['change', 'update:modelValue'],
  setup(_props, { emit }) {
    const change = (event: Event) => {
      const value = (event.target as HTMLSelectElement).value
      emit('update:modelValue', value)
      emit('change', { value })
    }
    return { change }
  },
  template: `
    <select v-bind="$attrs" :value="modelValue ?? ''" @change="change">
      <option
        v-for="option in options"
        :key="option[optionValue]"
        :value="option[optionValue]"
        v-text="option[optionLabel]"
      />
    </select>
  `,
})

const MessageStub = defineComponent({ template: '<div role="alert"><slot /></div>' })
const PrimeLocaleProbe = defineComponent({
  setup() {
    return { primeVue: usePrimeVue() }
  },
  template: `
    <span data-testid="prime-today" v-text="primeVue.config.locale?.today" />
    <span data-testid="prime-zoom-in" v-text="primeVue.config.locale?.aria?.zoomIn" />
  `,
})
const LocaleHarness = defineComponent({
  components: { App, PrimeLocaleProbe },
  template: '<App /><PrimeLocaleProbe />',
})
const uiStubs = {
  Button: ButtonStub,
  InputText: InputStub,
  Message: MessageStub,
  Password: InputStub,
  Select: SelectStub,
}

function testState() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  })
  const pinia = createPinia()
  setActivePinia(pinia)
  const testI18n = createI18n({
    legacy: false,
    locale: 'en-US',
    messages: { 'en-US': enUS, 'zh-CN': zhCN },
  })
  return { pinia, queryClient, testI18n }
}

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
})

describe('mounted authentication components', () => {
  it('submits login credentials and settles the remote session boundary', async () => {
    loginMock.mockResolvedValue(session)
    const { pinia, queryClient, testI18n } = testState()
    const wrapper = mount(AuthPanel, {
      global: {
        plugins: [pinia, testI18n, [VueQueryPlugin, { queryClient }]],
        stubs: uiStubs,
      },
    })

    await wrapper.get('[data-testid="auth-email"]').setValue(session.email)
    await wrapper.get('#auth-password').setValue('correct horse battery staple')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(loginMock).toHaveBeenCalledWith({
      email: session.email,
      password: 'correct horse battery staple',
    })
    expect(queryClient.getQueryData(authQueryKeys.session)).toEqual(session)
    wrapper.unmount()
    queryClient.clear()
  })

  it('renders a stable authentication error code with localized copy', async () => {
    loginMock.mockRejectedValue(
      new ApiRequestError(401, 'invalid_credentials', 'backend prose must stay hidden'),
    )
    const { pinia, queryClient, testI18n } = testState()
    const wrapper = mount(AuthPanel, {
      global: {
        plugins: [pinia, testI18n, [VueQueryPlugin, { queryClient }]],
        stubs: uiStubs,
      },
    })

    await wrapper.get('[data-testid="auth-email"]').setValue(session.email)
    await wrapper.get('#auth-password').setValue('incorrect password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain(
      enUS.auth.errors.invalid_credentials,
    )
    expect(wrapper.text()).not.toContain('backend prose must stay hidden')
    wrapper.unmount()
    queryClient.clear()
  })

  it('switches to registration and submits the initial workspace', async () => {
    signupMock.mockResolvedValue(session)
    const { pinia, queryClient, testI18n } = testState()
    const wrapper = mount(AuthPanel, {
      global: {
        plugins: [pinia, testI18n, [VueQueryPlugin, { queryClient }]],
        stubs: uiStubs,
      },
    })

    await wrapper.get('[data-testid="auth-signup-mode"]').trigger('click')
    await wrapper.get('[data-testid="auth-email"]').setValue(session.email)
    await wrapper.get('#auth-password').setValue('correct horse battery staple')
    await wrapper.get('[data-testid="auth-workspace-name"]').setValue('Initial Workspace')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(signupMock).toHaveBeenCalledWith({
      email: session.email,
      password: 'correct horse battery staple',
      workspaceName: 'Initial Workspace',
    })
    expect(queryClient.getQueryData(authQueryKeys.session)).toEqual(session)
    wrapper.unmount()
    queryClient.clear()
  })

  it('reconciles workspace selection and clears it on logout', async () => {
    listWorkspacesMock.mockResolvedValue([
      {
        workspaceId: '00000000-0000-4000-8000-000000000010',
        name: 'First',
        createdAt: '2026-01-01T00:00:00Z',
      },
      {
        workspaceId: '00000000-0000-4000-8000-000000000020',
        name: 'Second',
        createdAt: '2026-01-01T00:00:00Z',
      },
    ])
    logoutMock.mockResolvedValue(undefined)
    const { pinia, queryClient, testI18n } = testState()
    queryClient.setQueryData(authQueryKeys.session, session)
    const wrapper = mount(WorkspaceSwitcher, {
      props: { session },
      global: {
        plugins: [pinia, testI18n, [VueQueryPlugin, { queryClient }]],
        stubs: uiStubs,
      },
    })

    await flushPromises()
    await nextTick()
    const workspaceStore = useWorkspaceStore()
    expect(workspaceStore.workspaceId).toBe('00000000-0000-4000-8000-000000000010')

    await wrapper.get('[data-testid="workspace-select"]').setValue(
      '00000000-0000-4000-8000-000000000020',
    )
    expect(workspaceStore.workspaceId).toBe('00000000-0000-4000-8000-000000000020')

    await wrapper.get('[data-testid="auth-logout"]').trigger('click')
    await flushPromises()

    expect(logoutMock).toHaveBeenCalledOnce()
    expect(queryClient.getQueryData(authQueryKeys.session)).toBeNull()
    expect(workspaceStore.activeUserId).toBeNull()
    expect(workspaceStore.workspaceId).toBeNull()
    wrapper.unmount()
    queryClient.clear()
  })

  it('submits workspace creation, updates the remote cache, and activates it', async () => {
    const firstWorkspace: WorkspaceDto = {
      workspaceId: '00000000-0000-4000-8000-000000000010',
      name: 'First',
      createdAt: '2026-01-01T00:00:00Z',
    }
    const createdWorkspace: WorkspaceDto = {
      workspaceId: '00000000-0000-4000-8000-000000000020',
      name: 'Created Workspace',
      createdAt: '2026-01-02T00:00:00Z',
    }
    listWorkspacesMock.mockResolvedValue([firstWorkspace])
    createWorkspaceMock.mockResolvedValue(createdWorkspace)
    const { pinia, queryClient, testI18n } = testState()
    const wrapper = mount(WorkspaceSwitcher, {
      props: { session },
      global: {
        plugins: [pinia, testI18n, [VueQueryPlugin, { queryClient }]],
        stubs: uiStubs,
      },
    })

    await flushPromises()
    await wrapper.get('.workspace-create input').setValue(createdWorkspace.name)
    await wrapper.get('.workspace-create').trigger('submit')
    await flushPromises()

    const workspaceStore = useWorkspaceStore()
    expect(createWorkspaceMock).toHaveBeenCalledWith(createdWorkspace.name)
    expect(workspaceStore.activeUserId).toBe(session.userId)
    expect(workspaceStore.workspaceId).toBe(createdWorkspace.workspaceId)
    expect(
      queryClient.getQueryData<WorkspaceDto[]>([
        ...authQueryKeys.workspaces,
        session.userId,
      ]),
    ).toEqual([firstWorkspace, createdWorkspace])
    expect((wrapper.get('.workspace-create input').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
    queryClient.clear()
  })

  it('preserves a persisted workspace while the workspace list is pending', async () => {
    const firstWorkspaceId = '00000000-0000-4000-8000-000000000010'
    const secondWorkspaceId = '00000000-0000-4000-8000-000000000020'
    const serverWorkspaces: WorkspaceDto[] = [
      {
        workspaceId: firstWorkspaceId,
        name: 'First',
        createdAt: '2026-01-01T00:00:00Z',
      },
      {
        workspaceId: secondWorkspaceId,
        name: 'Second',
        createdAt: '2026-01-01T00:00:00Z',
      },
    ]
    let resolveWorkspaces: (value: WorkspaceDto[]) => void = () => undefined
    listWorkspacesMock.mockReturnValue(
      new Promise((resolve) => {
        resolveWorkspaces = resolve
      }),
    )
    const { pinia, queryClient, testI18n } = testState()
    const workspaceStore = useWorkspaceStore()
    workspaceStore.activate(session.userId)
    workspaceStore.select(secondWorkspaceId)
    const storageKey = localStorage.key(0)
    workspaceStore.deactivate()

    const wrapper = mount(WorkspaceSwitcher, {
      props: { session },
      global: {
        plugins: [pinia, testI18n, [VueQueryPlugin, { queryClient }]],
        stubs: uiStubs,
      },
    })

    await nextTick()
    expect(listWorkspacesMock).toHaveBeenCalledOnce()
    expect(workspaceStore.workspaceId).toBe(secondWorkspaceId)
    expect(storageKey).not.toBeNull()
    expect(localStorage.getItem(storageKey!)).toBe(secondWorkspaceId)

    resolveWorkspaces(serverWorkspaces)
    await flushPromises()
    await nextTick()

    expect(workspaceStore.workspaceId).toBe(secondWorkspaceId)
    expect(localStorage.getItem(storageKey!)).toBe(secondWorkspaceId)
    wrapper.unmount()
    queryClient.clear()
  })

  it('renders restoring then guest state when no session can be restored', async () => {
    let resolveSession: (value: SessionDto | null) => void = () => undefined
    getSessionMock.mockReturnValue(new Promise((resolve) => { resolveSession = resolve }))
    const { pinia, queryClient, testI18n } = testState()
    const wrapper = mount(App, {
      global: {
        plugins: [
          pinia,
          testI18n,
          [VueQueryPlugin, { queryClient }],
          [PrimeVue, { locale: {} }],
        ],
        stubs: {
          ...uiStubs,
          AuthPanel: defineComponent({ template: '<div data-testid="mounted-auth-panel" />' }),
          ItemsPage: defineComponent({ template: '<div data-testid="mounted-items" />' }),
          ProgressSpinner: defineComponent({ template: '<div data-testid="session-loading" />' }),
          WorkspaceSwitcher: defineComponent({ template: '<div data-testid="mounted-workspace" />' }),
        },
      },
    })

    await nextTick()
    expect(wrapper.find('[data-testid="session-loading"]').exists()).toBe(true)
    resolveSession(null)
    await flushPromises()

    expect(wrapper.find('[data-testid="mounted-auth-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="mounted-workspace"]').exists()).toBe(false)
    wrapper.unmount()
    queryClient.clear()
  })

  it('restores an authenticated session before mounting protected content', async () => {
    let resolveSession: (value: SessionDto | null) => void = () => undefined
    getSessionMock.mockReturnValue(new Promise((resolve) => { resolveSession = resolve }))
    const { pinia, queryClient, testI18n } = testState()
    const wrapper = mount(App, {
      global: {
        plugins: [
          pinia,
          testI18n,
          [VueQueryPlugin, { queryClient }],
          [PrimeVue, { locale: {} }],
        ],
        stubs: {
          ...uiStubs,
          AuthPanel: defineComponent({ template: '<div data-testid="mounted-auth-panel" />' }),
          ItemsPage: defineComponent({ template: '<div data-testid="mounted-items" />' }),
          ProgressSpinner: defineComponent({ template: '<div data-testid="session-loading" />' }),
          WorkspaceSwitcher: defineComponent({
            props: { session: { type: Object, required: true } },
            template: '<div data-testid="mounted-workspace" />',
          }),
        },
      },
    })

    await nextTick()
    expect(wrapper.find('[data-testid="session-loading"]').exists()).toBe(true)
    resolveSession(session)
    await flushPromises()

    expect(wrapper.find('[data-testid="mounted-workspace"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="mounted-auth-panel"]').exists()).toBe(false)
    wrapper.unmount()
    queryClient.clear()
  })

  it('synchronizes vue-i18n, html lang, storage, and PrimeVue after locale switching', async () => {
    getSessionMock.mockResolvedValue(null)
    i18n.global.locale.value = 'en-US'
    document.documentElement.lang = 'en-US'
    const { pinia, queryClient } = testState()
    const primeLocale = {
      ...primeLocales['en-US'],
      aria: { ...primeLocales['en-US'].aria },
    }
    const wrapper = mount(LocaleHarness, {
      global: {
        plugins: [
          pinia,
          i18n,
          [VueQueryPlugin, { queryClient }],
          [PrimeVue, { locale: primeLocale }],
        ],
        stubs: {
          ...uiStubs,
          AuthPanel: defineComponent({ template: '<div data-testid="mounted-auth-panel" />' }),
          ItemsPage: defineComponent({ template: '<div data-testid="mounted-items" />' }),
          ProgressSpinner: defineComponent({ template: '<div data-testid="session-loading" />' }),
          WorkspaceSwitcher: defineComponent({ template: '<div data-testid="mounted-workspace" />' }),
        },
      },
    })

    await flushPromises()
    expect(wrapper.get('[data-testid="prime-today"]').text()).toBe('Today')
    await wrapper.get('.locale-control select').setValue('zh-CN')
    await nextTick()

    expect(i18n.global.locale.value).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(localStorage.getItem('app.locale')).toBe('zh-CN')
    expect(wrapper.get('[data-testid="prime-today"]').text()).toBe('今天')
    expect(wrapper.get('[data-testid="prime-zoom-in"]').text()).toBe('放大')
    expect(wrapper.text()).toContain(zhCN.app.language)
    wrapper.unmount()
    queryClient.clear()
    i18n.global.locale.value = 'en-US'
    document.documentElement.lang = 'en-US'
  })
})

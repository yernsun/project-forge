import { describe, expect, it, vi } from 'vitest'

import {
  ApiRequestError,
  createItem,
  listItems,
  resolveApiBaseUrl,
  type ItemDto,
} from '@/shared/api/client'

const workspaceId = '00000000-0000-4000-8000-000000000001'
const item: ItemDto = {
  itemId: '00000000-0000-4000-8000-000000000002',
  name: 'Example',
  description: null,
  status: 'ACTIVE',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  version: 1,
  workspaceId: null,
}

describe('generated API contract', () => {
  it('keeps item identifiers as strings at the transport boundary', () => {
    const item: Pick<ItemDto, 'itemId' | 'status'> = { itemId: 'id', status: 'ACTIVE' }
    expect(item.status).toBe('ACTIVE')
  })

  it('keeps configured API paths on the browser gateway origin', () => {
    expect(resolveApiBaseUrl('', 'http://172.20.0.10:8173')).toBe(
      'http://172.20.0.10:8173',
    )
    expect(resolveApiBaseUrl('/gateway/', 'http://172.20.0.10:8173')).toBe(
      'http://172.20.0.10:8173/gateway',
    )
    expect(() => resolveApiBaseUrl(
      'http://172.20.0.11:8000',
      'http://172.20.0.10:8173',
    )).toThrow('must resolve to the browser origin')
  })

  it('lists and creates items through the generated OpenAPI client', async () => {
    const requests: Request[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
      requests.push(request)
      return new Response(
        JSON.stringify(request.method === 'POST' ? item : { items: [item] }),
        {
          status: request.method === 'POST' ? 201 : 200,
          headers: { 'Content-Type': 'application/json' },
        },
      )
    }))

    await expect(listItems(workspaceId)).resolves.toEqual([item])
    await expect(createItem({ name: 'Example', description: null }, workspaceId)).resolves.toEqual(item)
    expect(requests).toHaveLength(2)
    expect(requests[0]?.url).toContain('/api/v1/')
    expect(requests[0]?.url).toContain('/items')
    expect(requests[0]?.credentials).toBe('include')
    expect(requests[1]?.method).toBe('POST')
  })

  it('preserves stable API error details and retry timing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ code: 'items_unavailable', message: 'Items are unavailable' }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '7' },
      },
    )))

    const request = listItems(workspaceId)
    await expect(request).rejects.toBeInstanceOf(ApiRequestError)
    await expect(request).rejects.toMatchObject({
      status: 503,
      code: 'items_unavailable',
      retryAfter: 7,
    })
  })
})

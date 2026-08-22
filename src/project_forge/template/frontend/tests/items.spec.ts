import { describe, expect, it } from 'vitest'

import type { ItemDto } from '@/shared/api/client'

describe('generated API contract', () => {
  it('keeps item identifiers as strings at the transport boundary', () => {
    const item: Pick<ItemDto, 'itemId' | 'status'> = { itemId: 'id', status: 'ACTIVE' }
    expect(item.status).toBe('ACTIVE')
  })
})

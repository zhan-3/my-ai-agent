import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Button } from '@/components/ui/button'

describe('工具链冒烟', () => {
  it('shadcn Button 可渲染', () => {
    render(<Button>晓问</Button>)
    expect(screen.getByRole('button', { name: '晓问' })).toBeInTheDocument()
  })
})

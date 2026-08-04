import { describe, expect, it } from 'vitest'

const sourceModules = import.meta.glob('./**/*.tsx', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>

function inputTags(source: string): string[] {
  return source.match(/<(?:Input|Textarea|input|textarea)\b[\s\S]*?\/>/g) ?? []
}

describe('form autocomplete convention', () => {
  const tags = Object.entries(sourceModules)
    .filter(([path]) => !path.includes('/components/ui/') && !path.endsWith('.test.tsx'))
    .flatMap(([, source]) => inputTags(source))

  it('declares autocomplete on every application input', () => {
    expect(tags).not.toHaveLength(0)
    for (const tag of tags) expect(tag).toMatch(/\bautoComplete=/)
  })

  it('uses password-manager semantics for password fields', () => {
    const passwordTags = tags.filter((tag) => /\btype=["']password["']/.test(tag))

    expect(passwordTags).not.toHaveLength(0)
    for (const tag of passwordTags) {
      expect(tag).toMatch(/\bautoComplete=["'](?:current-password|new-password)["']/)
    }
  })
})

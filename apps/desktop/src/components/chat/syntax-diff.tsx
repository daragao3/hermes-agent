'use client'

/**
 * The Shiki-highlighted compact diff body, split out of diff-lines.tsx so the
 * `react-shiki` static import (and the multi-MB shiki chunk behind it) loads
 * lazily on first use instead of on the cold-start path. diff-lines.tsx
 * reaches this through `React.lazy` with a plain `DiffBody` fallback.
 */
import type { ReactNode } from 'react'
import { useMemo } from 'react'
import { useShikiHighlighter } from 'react-shiki/core'

import { DiffBody, type DiffLine, diffLineTransformer } from '@/components/chat/diff-lines'
import { type CuratedHighlighter, normalizeShikiLang, useCuratedHighlighter } from '@/lib/shiki-core'
import { SHIKI_THEME } from '@/components/chat/shiki-highlighter'

export default function SyntaxDiff({ language, lines }: { language: string; lines: DiffLine[] }) {
  const highlighter = useCuratedHighlighter()
  return highlighter
    ? <SyntaxDiffReady highlighter={highlighter} language={language} lines={lines} />
    : <DiffBody lines={lines} />
}

function SyntaxDiffReady({highlighter, language, lines}: {
  highlighter: CuratedHighlighter; language: string; lines: DiffLine[]
}) {
  const code = useMemo(() => lines.map(line => line.text).join('\n'), [lines])
  const transformers = useMemo(() => [diffLineTransformer(lines.map(line => line.kind))], [lines])

  const highlighted = useShikiHighlighter(code, normalizeShikiLang(language), SHIKI_THEME, {
    highlighter,
    defaultColor: 'light-dark()',
    transformers
  })

  // Until Shiki resolves, show the plain colored diff so there's no flash.
  return (highlighted as ReactNode) ?? <DiffBody lines={lines} />
}

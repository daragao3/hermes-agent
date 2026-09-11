import { cleanup, render, screen } from '@testing-library/react'
import { createElement } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { SidebarSessionRow } from '@/app/chat/sidebar/session-row'
import { ja } from '@/i18n/ja'
import { zh } from '@/i18n/zh'
import type { SessionInfo } from '@/types/hermes'

import {
  bridgeSidebarStateLabel,
  bridgeSidebarStateSearchTerms,
  isMessagingSource,
  LOCAL_SESSION_SOURCE_IDS,
  MESSAGING_SESSION_SOURCE_IDS,
  sessionDriverLabel,
  sessionSourceLabel,
  sessionSourceSearchTerms
} from './session-source'

function makeSession(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    archived: false,
    cwd: '/home/user/projects/hermes-agent',
    ended_at: null,
    id: 'claude:native-one',
    input_tokens: 0,
    is_active: false,
    last_active: 1_000,
    message_count: 2,
    model: 'claude',
    output_tokens: 0,
    preview: 'Continue in either harness',
    source: 'claude',
    started_at: 1_000,
    title: 'Cross-harness session',
    tool_call_count: 0,
    ...overrides
  }
}

afterEach(cleanup)

describe('Claude session source metadata', () => {
  it('treats Claude as a named local source', () => {
    expect(sessionSourceLabel('claude')).toBe('Claude')
    expect(LOCAL_SESSION_SOURCE_IDS).toContain('claude')
    expect(isMessagingSource('claude')).toBe(false)
  })

  it('exposes Claude Code and Anthropic aliases', () => {
    expect(sessionSourceSearchTerms('claude')).toEqual(
      expect.arrayContaining(['claude', 'Claude', 'claude code', 'anthropic'])
    )
  })
})

describe('Codex sidebar delivery metadata', () => {
  it('uses the exact public sidebar labels', () => {
    expect(bridgeSidebarStateLabel('pending')).toBe('Pending')
    expect(bridgeSidebarStateLabel('visible')).toBe('Visible in Codex')
    expect(bridgeSidebarStateLabel('retrying')).toBe('Retrying')
    expect(bridgeSidebarStateLabel('failed')).toBe('Failed')
    expect(bridgeSidebarStateLabel('unknown')).toBeNull()
  })

  it('adds the generic Codex sidebar term to every public state', () => {
    for (const state of ['pending', 'visible', 'retrying', 'failed']) {
      expect(bridgeSidebarStateSearchTerms(state)).toEqual(
        expect.arrayContaining(['codex sidebar', state])
      )
    }
  })
})

describe('Session driver attribution', () => {
  it('maps driver slugs to harness labels', () => {
    expect(sessionDriverLabel('claude-code')).toBe('Claude')
    expect(sessionDriverLabel('codex')).toBe('Codex')
    expect(sessionDriverLabel(null)).toBeNull()
    expect(sessionDriverLabel(undefined)).toBeNull()
    expect(sessionDriverLabel('some-agent')).toBe('Some Agent')
  })

  it('renders a driven-by badge for agent-driven local sessions', () => {
    render(
      createElement(SidebarSessionRow, {
        isPinned: false,
        isSelected: false,
        unread: false,
        onToggleUnread: () => {},
        onArchive: () => {},
        onDelete: () => {},
        onPin: () => {},
        onResume: () => {},
        session: makeSession({ driver: 'claude-code', source: 'cli' })
      })
    )

    const badge = screen.getByText('Claude')
    expect(badge.getAttribute('title')).toBe('Driven by Claude')
    expect(screen.getByLabelText('Driven by Claude')).toBe(badge)
  })

  it('suppresses the driver badge when a bridge provider badge is shown', () => {
    render(
      createElement(SidebarSessionRow, {
        isPinned: false,
        isSelected: false,
        unread: false,
        onToggleUnread: () => {},
        onArchive: () => {},
        onDelete: () => {},
        onPin: () => {},
        onResume: () => {},
        session: makeSession({
          bridge_provider: 'claude',
          driver: 'claude-code',
          source: 'cli'
        })
      })
    )

    expect(screen.getAllByText('Claude')).toHaveLength(1)
    expect(screen.queryByLabelText('Driven by Claude')).toBeNull()
  })
})

describe('SidebarSessionRow bridge metadata', () => {
  it('renders provider and mirror state as visible accessible metadata', () => {
    render(
      createElement(SidebarSessionRow, {
        isPinned: false,
        isSelected: false,
        unread: false,
        onToggleUnread: () => {},
        onArchive: () => {},
        onDelete: () => {},
        onPin: () => {},
        onResume: () => {},
        session: makeSession({
          bridge_mirror_state: 'continued',
          bridge_provider: 'claude'
        })
      })
    )

    const providerBadge = screen.getByText('Claude')
    const stateIndicator = screen.getByText('Continued')

    expect(providerBadge.getAttribute('title')).toBe('Provider: Claude')
    expect(screen.getByLabelText('Provider: Claude')).toBe(providerBadge)
    expect(stateIndicator.getAttribute('title')).toBe('Mirror state: Continued')
    expect(screen.getByLabelText('Mirror state: Continued')).toBe(stateIndicator)
  })

  it('uses localized bridge metadata copy', () => {
    expect(ja.sidebar.row.bridgeProvider('Claude')).toBe('プロバイダー: Claude')
    expect(ja.sidebar.row.bridgeMirrorState(ja.sidebar.row.bridgeFailed)).toBe('ミラー状態: 失敗')
    expect(zh.sidebar.row.bridgeProvider('Codex')).toBe('提供方：Codex')
    expect(zh.sidebar.row.bridgeMirrorState(zh.sidebar.row.bridgeQueued)).toBe('镜像状态：已排队')
  })

  it('uses the semantic destructive token for failed bridge state', () => {
    render(
      createElement(SidebarSessionRow, {
        isPinned: false,
        isSelected: false,
        unread: false,
        onToggleUnread: () => {},
        onArchive: () => {},
        onDelete: () => {},
        onPin: () => {},
        onResume: () => {},
        session: makeSession({
          bridge_mirror_state: 'failed',
          bridge_provider: 'codex'
        })
      })
    )

    const stateIndicator = screen.getByLabelText('Mirror state: Failed')
    expect(stateIndicator.className).toContain('text-destructive')
    expect(stateIndicator.className).not.toContain('text-red-500')
  })
})

// Regression guard for #46761 / PR #47395: Photon (iMessage) must keep its own
// sidebar section. refreshMessagingSessions() filters rows through
// isMessagingSource(), so this entry is the sole condition that keeps Photon
// sessions out of generic recents. A silent removal would regress the feature
// with no test failure — these asserts pin the contract.
describe('photon messaging source registration', () => {
  it('treats photon as a messaging source (own sidebar section)', () => {
    expect(isMessagingSource('photon')).toBe(true)
  })

  it('is case/space insensitive on the source id', () => {
    expect(isMessagingSource('PHOTON')).toBe(true)
    expect(isMessagingSource('  photon ')).toBe(true)
  })

  it('exposes the iMessage/messages search aliases so Photon sessions are findable', () => {
    const terms = sessionSourceSearchTerms('photon')
    expect(terms).toContain('imessage')
    expect(terms).toContain('messages')
  })

  it('is registered in the messaging source id list', () => {
    expect(MESSAGING_SESSION_SOURCE_IDS).toContain('photon')
  })

  it('does not flag local/CLI-ish sources as messaging (guard sanity)', () => {
    expect(isMessagingSource('cli')).toBe(false)
    expect(isMessagingSource(null)).toBe(false)
    expect(isMessagingSource(undefined)).toBe(false)
  })
})

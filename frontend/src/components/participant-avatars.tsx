import { useState } from 'react'
import type { RequirementRow } from '@/lib/api'
import { UserAvatar } from './user-avatar'

export function ParticipantAvatars({ participants }: Pick<RequirementRow, 'participants'>) {
  const [opened, setOpened] = useState<string | null>(null)
  if (!participants?.length) return null
  return (
    <div role="group" aria-label="参与者" className="flex max-w-full flex-wrap items-center gap-y-1 pl-1">
      {participants.map(person => (
        <button key={person.id} type="button" aria-label={person.name}
          aria-expanded={opened === person.id}
          className="participant-chip -ml-1 inline-flex max-w-full items-center rounded-full bg-background p-0.5 outline-offset-1 focus-visible:outline-2"
          onPointerDown={event => event.stopPropagation()}
          onPointerEnter={event => { if (event.pointerType === 'mouse') setOpened(person.id) }}
          onPointerLeave={event => { if (event.pointerType === 'mouse') setOpened(null) }}
          onFocus={event => { if (event.currentTarget.matches(':focus-visible')) setOpened(person.id) }}
          onBlur={() => setOpened(null)}
          onClick={event => { if (event.detail === 0 || !window.matchMedia('(hover: hover)').matches) setOpened(current => current === person.id ? null : person.id) }}
          onKeyDown={event => { if (event.key === 'Escape') setOpened(null) }}>
          <UserAvatar user={{ id: person.id, username: person.name, avatar: person.avatar }} className="size-6" />
          <span aria-hidden="true" className="participant-name">
            <span className="min-w-0 overflow-hidden"><span className="block max-w-36 truncate px-1.5 text-xs">{person.name}</span></span>
          </span>
        </button>
      ))}
    </div>
  )
}

import { useState } from 'react'
import { Icon } from '../../../components/Icon'
import './ToolTraceDisclosure.css'

/** S11: only rendered on request, not raw SQL by default. Field names match the real backend
 * payload (`ChatToolCallSummaryView` in `backend/app/views/chat.py`): `tool_name` + `summary` —
 * never `tool`/`arguments`/`result`, which don't exist on the wire. */
export function ToolTraceDisclosure({ toolCalls }) {
  const [expanded, setExpanded] = useState(false)

  if (!toolCalls || toolCalls.length === 0) {
    return null
  }

  return (
    <div className="tu-tool-trace">
      <button
        type="button"
        className="tu-tool-trace__toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <span>How this was answered</span>
        <Icon name={expanded ? 'chevron-up' : 'chevron-down'} />
      </button>
      {expanded && (
        <div className="tu-tool-trace__list">
          {toolCalls.map((call, index) => (
            <div key={`${call.tool_name}-${index}`}>
              {call.tool_name}: {call.summary}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

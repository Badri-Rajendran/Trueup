import { useState } from 'react'
import { Icon } from '../../../components/Icon'
import './ToolTraceDisclosure.css'

// The only two tools the assistant can call (chat_orchestration_service.py's system prompt names
// them explicitly). Mapped to plain phrases so a Python identifier never reaches a customer on a
// financial platform's own surface; an unrecognized future tool_name still falls back to itself
// rather than rendering nothing.
const TOOL_LABELS = {
  get_database_schema: 'Looked up what data is available',
  execute_read_only_sql: 'Looked up your data',
}

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
            <div key={`${call.tool_name}-${index}`} className="tu-tool-trace__item">
              <span className="tu-tool-trace__item-label">
                {TOOL_LABELS[call.tool_name] || call.tool_name}
              </span>
              <span className="tu-tool-trace__item-summary">{call.summary}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

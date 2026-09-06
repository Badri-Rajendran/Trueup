import { useState } from 'react'
import './ToolTraceDisclosure.css'

/** S11: only rendered on request, not raw SQL by default. */
export function ToolTraceDisclosure({ toolCalls }) {
  const [expanded, setExpanded] = useState(false)

  if (!toolCalls || toolCalls.length === 0) {
    return null
  }

  return (
    <div className="tu-tool-trace">
      <button type="button" className="tu-tool-trace__toggle" onClick={() => setExpanded((prev) => !prev)}>
        {expanded ? 'Hide' : 'Show'} how this was answered
      </button>
      {expanded && (
        <div className="tu-tool-trace__list">
          {toolCalls.map((call, index) => (
            <div key={`${call.tool}-${index}`}>
              {call.tool}({JSON.stringify(call.arguments)}) → {call.result}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Minimal Markdown renderer for streamed assistant chat replies — bold/italic/inline-code/lists/
 * GFM pipe tables, matching `structure.md`'s framing of this surface as short-form streamed text,
 * not documents. Hand-rolled instead of a library (e.g. react-markdown + remark/rehype): a reply
 * here is a sentence or two, occasionally a short list or table, never headings/nested blocks, so
 * a full CommonMark pipeline is a lot of dependency weight for a handful of inline/block rules.
 * Output is plain React elements — never `dangerouslySetInnerHTML` — so it can't become an XSS
 * vector no matter what the model returns, and partially-streamed text (an unclosed `**`/`` ` ``,
 * or a table whose closing rows haven't arrived yet) just renders as literal characters or a
 * plain paragraph until enough of it exists to parse.
 *
 * Table support exists because the chat system prompt (chat_orchestration_service.py's
 * `_SYSTEM_PROMPT_TEMPLATE`, rule 6) asks the model to format multi-row results -- holdings,
 * transactions, tax lots -- as a table, and gpt-4o-mini reliably does this unprompted anyway for
 * tabular data. Tables render through the app's real `Table` compound component
 * (`components/Table/`), not bespoke markup, so a chat table looks like every other table.
 */

import { Table } from '../../../components/Table'

const INLINE_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g
// GFM separator row: one or more `-`-runs (each side optionally `:` for alignment), pipe-joined,
// with optional leading/trailing pipes -- e.g. `| --- | :--- | ---: |` or `--- | ---`.
const TABLE_SEPARATOR_PATTERN = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/

function splitTableRow(line) {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((cell) => cell.trim())
}

function renderInline(text, keyPrefix) {
  return text
    .split(INLINE_PATTERN)
    .filter((part) => part !== '')
    .map((part, index) => {
      const key = `${keyPrefix}-${index}`
      if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
        return <strong key={key}>{part.slice(2, -2)}</strong>
      }
      if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
        return <code key={key}>{part.slice(1, -1)}</code>
      }
      if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
        return <em key={key}>{part.slice(1, -1)}</em>
      }
      return part
    })
}

/** Renders `text` as an array of block-level React nodes — paragraphs (line breaks preserved) and
 * `-`/`*`/`1.` lists — each with inline bold/italic/code applied. */
export function renderMarkdown(text) {
  if (!text) return null

  const lines = text.split('\n')
  const blocks = []
  let listType = null
  let listItems = null
  let paraLines = []

  const flushParagraph = () => {
    if (paraLines.length === 0) return
    const blockKey = `p-${blocks.length}`
    blocks.push(
      <p key={blockKey} className="tu-markdown__para">
        {paraLines.flatMap((line, index) => [
          ...renderInline(line, `${blockKey}-${index}`),
          index < paraLines.length - 1 ? <br key={`${blockKey}-br-${index}`} /> : null,
        ])}
      </p>,
    )
    paraLines = []
  }

  const flushList = () => {
    if (!listItems) return
    const ListTag = listType
    const blockKey = `list-${blocks.length}`
    blocks.push(
      <ListTag key={blockKey} className="tu-markdown__list">
        {listItems.map((item, index) => (
          <li key={`${blockKey}-${index}`}>{renderInline(item, `${blockKey}-${index}`)}</li>
        ))}
      </ListTag>,
    )
    listItems = null
    listType = null
  }

  const pushTable = (headerCells, rows) => {
    const blockKey = `table-${blocks.length}`
    blocks.push(
      <Table key={blockKey} className="tu-markdown__table">
        <Table.Header>
          {headerCells.map((cell, index) => (
            <Table.HeaderCell key={`${blockKey}-h-${index}`}>
              {renderInline(cell, `${blockKey}-h-${index}`)}
            </Table.HeaderCell>
          ))}
        </Table.Header>
        <Table.Body>
          {rows.map((row, rowIndex) => (
            <Table.Row key={`${blockKey}-r-${rowIndex}`}>
              {row.map((cell, cellIndex) => (
                <Table.Cell key={`${blockKey}-r-${rowIndex}-c-${cellIndex}`}>
                  {renderInline(cell, `${blockKey}-r-${rowIndex}-c-${cellIndex}`)}
                </Table.Cell>
              ))}
            </Table.Row>
          ))}
        </Table.Body>
      </Table>,
    )
  }

  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const nextLine = lines[i + 1]

    // A table needs its header row to actually contain a pipe and its very next line to be a
    // real separator row -- otherwise a stray `|` in prose (e.g. "cash | investable") must never
    // be mistaken for a table.
    if (line.includes('|') && nextLine !== undefined && TABLE_SEPARATOR_PATTERN.test(nextLine)) {
      flushList()
      flushParagraph()
      const headerCells = splitTableRow(line)
      const rows = []
      i += 2
      while (i < lines.length && lines[i].trim() !== '' && lines[i].includes('|')) {
        rows.push(splitTableRow(lines[i]))
        i += 1
      }
      pushTable(headerCells, rows)
      continue
    }

    const bulletMatch = /^\s*[-*]\s+(.+)/.exec(line)
    const orderedMatch = /^\s*\d+\.\s+(.+)/.exec(line)

    if (bulletMatch) {
      flushParagraph()
      if (listType !== 'ul') {
        flushList()
        listType = 'ul'
        listItems = []
      }
      listItems.push(bulletMatch[1])
    } else if (orderedMatch) {
      flushParagraph()
      if (listType !== 'ol') {
        flushList()
        listType = 'ol'
        listItems = []
      }
      listItems.push(orderedMatch[1])
    } else if (line.trim() === '') {
      flushList()
      flushParagraph()
    } else {
      flushList()
      paraLines.push(line)
    }
    i += 1
  }
  flushList()
  flushParagraph()

  return blocks
}

/**
 * Minimal Markdown renderer for streamed assistant chat replies — bold/italic/inline-code/lists
 * only, matching `structure.md`'s framing of this surface as short-form streamed text, not
 * documents. Hand-rolled instead of a library (e.g. react-markdown + remark/rehype): a reply here
 * is a sentence or two, occasionally a short list, never headings/tables/nested blocks, so a full
 * CommonMark pipeline is a lot of dependency weight for four inline/block rules. Output is plain
 * React elements — never `dangerouslySetInnerHTML` — so it can't become an XSS vector no matter
 * what the model returns, and partially-streamed text (an unclosed `**`/`` ` ``) just renders as a
 * literal character until the closing marker arrives on a later token.
 */

const INLINE_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g

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

  for (const line of lines) {
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
  }
  flushList()
  flushParagraph()

  return blocks
}
